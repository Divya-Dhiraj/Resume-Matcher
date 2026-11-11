#!/usr/bin/env python3
"""Claude Code CLI bridge — tiny HTTP shim.

Runs on the host (macOS) so the Resume-Matcher backend (inside Docker) can
reach the user's `claude` CLI via `host.docker.internal:11435`. Mirrors the
same pattern Ollama uses (:11434).

Why a bridge:
  - The Docker container has no `claude` binary and no access to the user's
    ~/.claude auth files.
  - Running the bridge on the host lets Claude Code use the user's logged-in
    session; no API key, no Anthropic paid-API spend.

Contract:
  POST /generate
    { "prompt": "...", "system_prompt": "...", "model": "sonnet"|"opus"|"haiku" }
    -> { "content": "...", "model": "sonnet", "elapsed_ms": 1234 }
  GET /health
    -> { "status": "ok", "claude_version": "2.1.317" }

Safety:
  - Binds to 127.0.0.1 only (Docker still reaches it via host.docker.internal
    because the Docker daemon maps that name to the host loopback).
  - Hard timeout per request (default 180s).
  - No shell interpolation: subprocess is invoked with argv, prompt is piped
    on stdin, never embedded in the command string.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("claude-bridge")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser(
    "~/.local/bin/claude"
)
GEMINI_BIN = (
    os.environ.get("GEMINI_BIN")
    or shutil.which("gemini")
    or "/opt/homebrew/bin/gemini"
)
DEFAULT_TIMEOUT_S = int(os.environ.get("BRIDGE_TIMEOUT_S", "180"))

CLIProvider = Literal["claude", "gemini"]
ClaudeModel = Literal["sonnet", "opus", "haiku"]
GeminiModel = Literal[
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "auto",
]
BridgeModel = Literal[
    "sonnet",
    "opus",
    "haiku",
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "auto",
]


class GenerateRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    model: BridgeModel = "sonnet"
    cli: CLIProvider | None = None
    api_key: str | None = None
    timeout_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=5, le=600)


class GenerateResponse(BaseModel):
    content: str
    model: str
    elapsed_ms: int


def _resolve_cli(req_cli: CLIProvider | None, model: str) -> CLIProvider:
    if req_cli in ("claude", "gemini"):
        return req_cli
    if model.startswith("gemini") or model == "auto":
        return "gemini"
    return "claude"


async def _run_claude(prompt: str, system_prompt: str | None, model: str, timeout_s: int) -> str:
    """Invoke `claude -p` with the prompt piped on stdin.

    Using stdin instead of positional arg avoids shell-quoting pitfalls and
    sidesteps argv length limits on long prompts (full resume + JD).
    """
    args = [CLAUDE_BIN, "-p", "--model", model]
    if system_prompt:
        args.extend(["--append-system-prompt", system_prompt])

    log.info(
        "claude call model=%s prompt_chars=%d system_chars=%d",
        model,
        len(prompt),
        len(system_prompt or ""),
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"claude CLI not found at {CLAUDE_BIN}")

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"claude CLI exceeded {timeout_s}s timeout")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:2000]
        log.error("claude exit=%d stderr=%s", proc.returncode, err)
        raise HTTPException(status_code=502, detail=f"claude CLI failed (exit {proc.returncode}): {err}")

    return stdout.decode("utf-8", errors="replace").strip()


async def _run_gemini(
    prompt: str,
    system_prompt: str | None,
    model: str,
    timeout_s: int,
    api_key: str | None = None,
) -> str:
    """Invoke `gemini -p` with the prompt piped on stdin.

    If `api_key` is provided (or GEMINI_API_KEY is set), call the Gemini REST API
    directly for instant, non-hanging headless completions while still falling
    back to the `gemini` CLI binary if needed.
    """
    gemini_model = model if (model.startswith("gemini") or model == "auto") else "gemini-3.5-flash"
    if gemini_model == "auto":
        gemini_model = "gemini-3.5-flash"

    effective_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()

    log.info(
        "gemini call model=%s prompt_chars=%d system_chars=%d has_key=%s",
        gemini_model,
        len(prompt),
        len(system_prompt or ""),
        bool(effective_key),
    )

    # Fast path when GEMINI_API_KEY is configured: avoids gemini-cli Node.js
    # TTY/EventLoop hangs when spawned inside a background daemon without a pty.
    if effective_key:
        import httpx

        # Free-tier Gemini models each have an independent 20 RPD quota bucket.
        # If the selected Gemini model hits 429/503/404, automatically rotate
        # across the remaining Gemini free-tier models in the same family.
        fallback_models = [
            gemini_model,
            "gemini-3-flash-preview",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.5-flash",
        ]
        candidate_models: list[str] = []
        for m in fallback_models:
            if m not in candidate_models:
                candidate_models.append(m)

        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }
        if system_prompt and system_prompt.strip():
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt.strip()}]
            }
        last_status = 502
        last_body = ""
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                for candidate_model in candidate_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent"
                    resp = await client.post(
                        url, params={"key": effective_key}, json=body
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates") or []
                        if not candidates:
                            last_body = f"gemini returned no candidates: {resp.text[:500]}"
                            continue
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_parts = [
                            p.get("text", "")
                            for p in parts
                            if "text" in p and not p.get("thought")
                        ]
                        if not text_parts:
                            text_parts = [p.get("text", "") for p in parts if "text" in p]
                        if candidate_model != gemini_model:
                            log.info(
                                "gemini quota fallback succeeded with model=%s (requested=%s)",
                                candidate_model,
                                gemini_model,
                            )
                        return "\n".join(t for t in text_parts if t).strip()

                    last_status = resp.status_code
                    last_body = resp.text[:1000]
                    log.warning(
                        "gemini model=%s status=%d; trying next Gemini model if available",
                        candidate_model,
                        resp.status_code,
                    )
                    if resp.status_code not in (429, 503, 404):
                        break

            raise HTTPException(
                status_code=502,
                detail=f"gemini failed ({last_status}): {last_body}",
            )
        except HTTPException:
            raise
        except Exception as e:
            log.error("gemini direct call failed: %s", e)
            raise HTTPException(status_code=502, detail=f"gemini failed: {e}")

    instruction = (system_prompt or "Follow the instructions provided on stdin.").strip()
    args = [
        GEMINI_BIN,
        "-p",
        instruction,
        "-m",
        gemini_model,
    ]

    env = dict(os.environ)
    env["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '/usr/bin:/bin')}"

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"gemini CLI not found at {GEMINI_BIN}")

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(status_code=504, detail=f"gemini CLI exceeded {timeout_s}s timeout")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:2000]
        out_err = stdout.decode("utf-8", errors="replace")[:2000]
        combined_err = (err or out_err).strip()
        log.error("gemini exit=%d stderr=%s", proc.returncode, combined_err)
        raise HTTPException(
            status_code=502,
            detail=f"gemini CLI failed (exit {proc.returncode}): {combined_err}",
        )

    return stdout.decode("utf-8", errors="replace").strip()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail loud at startup if the binary isn't where we expect — easier to
    # debug than a 500 on first request.
    if not CLAUDE_BIN or not os.path.exists(CLAUDE_BIN):
        log.warning("claude CLI not found at %r; claude requests will fail until installed", CLAUDE_BIN)
    else:
        log.info("claude bridge up; claude_bin=%s", CLAUDE_BIN)
    if not GEMINI_BIN or not os.path.exists(GEMINI_BIN):
        log.warning("gemini CLI not found at %r; gemini requests will fail until installed", GEMINI_BIN)
    else:
        log.info("gemini bridge up; gemini_bin=%s", GEMINI_BIN)
    yield


app = FastAPI(title="Claude & Gemini CLI Bridge", lifespan=lifespan)


@app.get("/health")
async def health(cli: CLIProvider = "claude") -> dict[str, str]:
    if cli == "gemini":
        if not GEMINI_BIN or not os.path.exists(GEMINI_BIN):
            raise HTTPException(status_code=503, detail=f"gemini CLI not at {GEMINI_BIN}")
        proc = await asyncio.create_subprocess_exec(
            GEMINI_BIN, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        version = out.decode().strip()
        return {"status": "ok", "gemini_version": version, "claude_version": f"gemini-cli {version}"}

    if not CLAUDE_BIN or not os.path.exists(CLAUDE_BIN):
        raise HTTPException(status_code=503, detail=f"claude CLI not at {CLAUDE_BIN}")
    proc = await asyncio.create_subprocess_exec(
        CLAUDE_BIN, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    return {"status": "ok", "claude_version": out.decode().strip()}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    t0 = time.time()
    cli = _resolve_cli(req.cli, req.model)
    if cli == "gemini":
        content = await _run_gemini(
            req.prompt, req.system_prompt, req.model, req.timeout_s, api_key=req.api_key
        )
    else:
        content = await _run_claude(req.prompt, req.system_prompt, req.model, req.timeout_s)
    elapsed = int((time.time() - t0) * 1000)
    return GenerateResponse(content=content, model=req.model, elapsed_ms=elapsed)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BRIDGE_PORT", "11435"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
