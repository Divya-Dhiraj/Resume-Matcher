"""Panel-aware completion wrapper.

When the active provider is ``claude_code_cli`` AND the stored panel depth
is ``mini`` or ``full``, calls fan out to multiple reviewer personas in
parallel (via the host bridge) and are merged into one final response by
one extra synthesis call. For every other provider, or for depth ``light``,
this is a plain pass-through to ``llm.complete``.

Total call count per generation:
    - light:  1
    - mini:   3 drafts + 1 merge = 4
    - full:   7 drafts + 1 merge = 8

All personas run in parallel so wall-clock latency is roughly
``max(persona_time) + merge_time`` rather than ``sum``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import load_config_file
from app.llm import complete, get_llm_config
from app.services.claude_bridge_client import (
    PANEL_PERSONAS,
    PERSONAS,
    ClaudeBridgeClient,
    PanelDepth,
)
from app.llm import _claude_bridge_base_url, _claude_model_from_config  # type: ignore

logger = logging.getLogger(__name__)


def _active_panel_depth() -> PanelDepth:
    """Read the stored panel_depth from config.json, defaulting to 'light'."""
    cfg = load_config_file()
    depth = cfg.get("panel_depth", "light")
    if depth not in ("light", "mini", "full"):
        return "light"
    return depth  # type: ignore[return-value]


async def complete_with_panel(
    prompt: str,
    *,
    system_prompt: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    merge_instruction: str | None = None,
) -> str:
    """Drop-in replacement for ``llm.complete`` that transparently runs the
    panel when the active provider+depth call for it.

    ``merge_instruction`` controls how the final synthesis call phrases the
    merge; callers pass something like "Merge these three drafts into one
    final cover letter in the user's voice" — tailored to their output shape.
    When omitted, a generic merger is used.
    """
    config = get_llm_config()
    depth = _active_panel_depth() if config.provider == "claude_code_cli" else "light"

    if config.provider != "claude_code_cli" or depth == "light":
        # Fast path: single provider call, personas don't apply.
        return await complete(
            prompt,
            system_prompt=system_prompt,
            config=config,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # Panel path: parallel reviewer drafts, then one merge call.
    personas = PANEL_PERSONAS[depth]
    client = ClaudeBridgeClient(
        _claude_bridge_base_url(config.api_base),
        timeout_s=180,
    )
    model = _claude_model_from_config(config.model)

    async def one(persona: str) -> tuple[str, str]:
        sys = (system_prompt or "").strip()
        persona_prompt = PERSONAS[persona]
        full_system = f"{sys}\n\n{persona_prompt}" if sys else persona_prompt
        try:
            return persona, await client.generate(prompt, system_prompt=full_system, model=model)
        except Exception as e:
            logger.warning("panel persona %s failed: %s", persona, e)
            return persona, ""

    drafts: list[tuple[str, str]] = await asyncio.gather(*[one(p) for p in personas])
    non_empty = [(name, text) for name, text in drafts if text.strip()]
    if not non_empty:
        raise ValueError("Every panel persona failed; see server logs")
    if len(non_empty) == 1:
        # Only one survived — skip the merge call, nothing to synthesize.
        return non_empty[0][1]

    merger = merge_instruction or (
        "You will be given several drafts of the same piece of writing, each "
        "produced by a reviewer with a different perspective. Merge them into "
        "ONE final version that keeps each reviewer's strongest point and "
        "drops the weakest. Output only the final text, no commentary."
    )
    merge_prompt_parts: list[str] = []
    for name, text in non_empty:
        merge_prompt_parts.append(f"--- Draft from {name} ---\n{text}\n")
    merge_prompt = "\n".join(merge_prompt_parts) + "\n--- End of drafts ---"

    return await client.generate(merge_prompt, system_prompt=merger, model=model)
