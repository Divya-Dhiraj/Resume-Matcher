"""Client for the host-side Claude Code CLI bridge.

The bridge is a tiny FastAPI shim running on the user's host at
`host.docker.internal:11435` (same pattern as Ollama's `:11434`). The
backend posts a prompt there and gets back the Claude response, having
spent the user's Claude Code subscription — no Anthropic API key, no
per-token spend.

Panel-depth personas (`light` / `mini` / `full`) are implemented here
too: `light` is a single call, `mini` runs 3 reviewer personas in
parallel, `full` runs the 7-persona panel. Each persona's response is
the LLM's own output; merging them into one final answer is the
caller's job (in improver.py / cover_letter.py), not the bridge's.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

PanelDepth = Literal["light", "mini", "full"]
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

# Personas layered on top of the task prompt. "Light" is the fast default;
# "mini" and "full" are run in parallel and whose outputs merged by callers.
# Phrased to make the model push back on vague copy, not to generate seven
# polished drafts.
PERSONAS: dict[str, str] = {
    "hiring_manager": (
        "You are the hiring manager for this role. Judge the resume/letter "
        "against the JD specifics. Reject vague phrasing. Prefer concrete "
        "metrics, named tools, and outcomes the JD actually asks for."
    ),
    "recruiter": (
        "You are the recruiter doing a 20-second scan. Flag anything that "
        "wastes the first screen: buried keywords, generic opener, missing "
        "must-have from the JD."
    ),
    "skeptic": (
        "You are a skeptical senior reader. Challenge any claim without "
        "evidence. If a bullet could be true of anyone, mark it weak."
    ),
    "domain_expert": (
        "You are a senior practitioner in the role's domain. Call out "
        "shallow usage of a technology: a 'used Airflow' line should name "
        "the operator, scale, or schedule it drove."
    ),
    "ats_screener": (
        "You are the ATS / automated screen. Score keyword coverage of the "
        "JD's required skills section and flag any exact-phrase matches "
        "the resume misses."
    ),
    "peer_engineer": (
        "You are a peer who would work with this person. Does the resume "
        "say what they actually did (vs. what the team did)? Flag passive "
        "voice and team-authorship ambiguity."
    ),
    "exec_reader": (
        "You are the hiring VP / department head doing a 2-minute read. "
        "Would you call this person back? Why or why not — in one line."
    ),
}

PANEL_PERSONAS: dict[PanelDepth, list[str]] = {
    "light": ["hiring_manager"],
    "mini": ["hiring_manager", "recruiter", "skeptic"],
    "full": list(PERSONAS.keys()),
}


class ClaudeBridgeClient:
    """Thin async client for the bridge. Instances are cheap; one per call."""

    def __init__(self, base_url: str, *, timeout_s: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def health(self, *, cli: CLIProvider = "claude") -> dict[str, str]:
        async with httpx.AsyncClient(timeout=5) as client:
            params = {"cli": cli} if cli != "claude" else None
            resp = await client.get(f"{self.base_url}/health", params=params)
            resp.raise_for_status()
            return resp.json()

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: BridgeModel = "sonnet",
        cli: CLIProvider | None = None,
        api_key: str | None = None,
    ) -> str:
        """One call, one response. Raises on non-200 or timeout."""
        payload: dict[str, str | int | None] = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "model": model,
            "timeout_s": int(self.timeout_s),
        }
        if cli is not None:
            payload["cli"] = cli
        if api_key:
            payload["api_key"] = api_key
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/generate",
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"cli bridge {resp.status_code}: {resp.text[:400]}"
                )
            return resp.json()["content"]

    async def generate_panel(
        self,
        prompt: str,
        *,
        base_system_prompt: str | None = None,
        depth: PanelDepth = "light",
        model: BridgeModel = "sonnet",
        cli: CLIProvider | None = None,
    ) -> dict[str, str]:
        """Run every persona in the chosen panel in parallel.

        Returns {persona_name: response}. Caller merges them — the panel
        is a critique/perspective generator, not a voting ensemble.
        A single-persona `light` call still goes through this path so the
        return shape is uniform.
        """
        personas = PANEL_PERSONAS[depth]
        sys_base = (base_system_prompt or "").strip()

        async def one(name: str) -> tuple[str, str]:
            sys = PERSONAS[name]
            if sys_base:
                sys = f"{sys_base}\n\n{sys}"
            try:
                content = await self.generate(
                    prompt, system_prompt=sys, model=model, cli=cli
                )
                return name, content
            except Exception as e:
                logger.warning("persona %s failed: %s", name, e)
                return name, f"[{name} failed: {e}]"

        results = await asyncio.gather(*[one(p) for p in personas])
        return dict(results)
