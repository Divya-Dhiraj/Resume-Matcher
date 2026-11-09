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
DEFAULT_TIMEOUT_S = int(os.environ.get("BRIDGE_TIMEOUT_S", "180"))


class GenerateRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    model: Literal["sonnet", "opus", "haiku"] = "sonnet"
    timeout_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=5, le=600)


class GenerateResponse(BaseModel):
    content: str
    model: str
    elapsed_ms: int


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Fail loud at startup if the binary isn't where we expect — easier to
    # debug than a 500 on first request.
    if not CLAUDE_BIN or not os.path.exists(CLAUDE_BIN):
        log.warning("claude CLI not found at %r; requests will fail until installed", CLAUDE_BIN)
    else:
        log.info("claude bridge up; binary=%s", CLAUDE_BIN)
    yield


app = FastAPI(title="Claude Code Bridge", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
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
    content = await _run_claude(req.prompt, req.system_prompt, req.model, req.timeout_s)
    elapsed = int((time.time() - t0) * 1000)
    return GenerateResponse(content=content, model=req.model, elapsed_ms=elapsed)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BRIDGE_PORT", "11435"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
