"""Tests for the Claude Code CLI bridge client and panel runner.

These tests pin the two value-add pieces the provider ships with:
  * ClaudeBridgeClient.generate_panel returns one response per persona and
    doesn't let a single persona failure drop the whole panel.
  * complete_with_panel is a transparent pass-through for every provider
    except claude_code_cli + mini/full, and in the panel path it runs N
    drafts in parallel plus one merge call.

respx stubs the bridge's HTTP surface so these stay deterministic and
offline — no real `claude` CLI is invoked.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from app.services.claude_bridge_client import (
    PANEL_PERSONAS,
    ClaudeBridgeClient,
)


BRIDGE = "http://127.0.0.1:11435"


@respx.mock
async def test_generate_returns_content() -> None:
    respx.post(f"{BRIDGE}/generate").mock(
        return_value=httpx.Response(200, json={"content": "hi", "model": "sonnet", "elapsed_ms": 1})
    )
    client = ClaudeBridgeClient(BRIDGE)
    assert await client.generate("test") == "hi"


@respx.mock
async def test_generate_raises_on_non_200() -> None:
    respx.post(f"{BRIDGE}/generate").mock(
        return_value=httpx.Response(502, text="bridge exploded")
    )
    client = ClaudeBridgeClient(BRIDGE)
    with pytest.raises(RuntimeError, match="502"):
        await client.generate("test")


@respx.mock
async def test_generate_panel_mini_runs_all_three_personas() -> None:
    # Each POST returns a different body so we can confirm the panel maps
    # responses to persona names rather than accidentally de-duping.
    call_count = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            200,
            json={"content": f"draft-{call_count['n']}", "model": "sonnet", "elapsed_ms": 1},
        )

    respx.post(f"{BRIDGE}/generate").mock(side_effect=_handler)

    client = ClaudeBridgeClient(BRIDGE)
    out = await client.generate_panel("task", depth="mini")

    assert set(out.keys()) == set(PANEL_PERSONAS["mini"])
    assert len(out) == 3
    # Fired 3 parallel calls, one per persona.
    assert call_count["n"] == 3


@respx.mock
async def test_generate_panel_marks_failed_persona_without_dropping_others() -> None:
    # First call 500s, rest return normally.
    state = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(500, text="nope")
        return httpx.Response(
            200, json={"content": "ok", "model": "sonnet", "elapsed_ms": 1}
        )

    respx.post(f"{BRIDGE}/generate").mock(side_effect=_handler)

    client = ClaudeBridgeClient(BRIDGE)
    out = await client.generate_panel("task", depth="mini")

    assert set(out.keys()) == set(PANEL_PERSONAS["mini"])
    failed = [name for name, text in out.items() if text.startswith("[")]
    assert len(failed) == 1
    successes = [text for text in out.values() if text == "ok"]
    assert len(successes) == 2


class _FakeConfig:
    """Mirror of LLMConfig for the fields complete_with_panel reads."""

    def __init__(self, provider: str, model: str = "sonnet", api_base: str | None = BRIDGE) -> None:
        self.provider = provider
        self.model = model
        self.api_base = api_base
        self.api_key = ""
        self.reasoning_effort = None


@respx.mock
async def test_complete_with_panel_light_delegates_to_plain_complete() -> None:
    from app.services import panel as panel_mod

    with (
        patch.object(panel_mod, "get_llm_config", return_value=_FakeConfig("claude_code_cli")),
        patch.object(panel_mod, "_active_panel_depth", return_value="light"),
        patch.object(panel_mod, "complete") as mock_complete,
    ):
        mock_complete.return_value = "just one"
        out = await panel_mod.complete_with_panel("prompt", system_prompt="sys")
    assert out == "just one"
    mock_complete.assert_awaited_once()


@respx.mock
async def test_complete_with_panel_mini_runs_three_plus_merge() -> None:
    from app.services import panel as panel_mod

    state = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(
            200,
            json={"content": f"text-{state['n']}", "model": "sonnet", "elapsed_ms": 1},
        )

    respx.post(f"{BRIDGE}/generate").mock(side_effect=_handler)

    with (
        patch.object(panel_mod, "get_llm_config", return_value=_FakeConfig("claude_code_cli")),
        patch.object(panel_mod, "_active_panel_depth", return_value="mini"),
    ):
        out = await panel_mod.complete_with_panel("the task", system_prompt="sys")

    # 3 drafts + 1 merge call = 4 bridge POSTs.
    assert state["n"] == 4
    assert out.startswith("text-")


async def test_complete_with_panel_non_claude_uses_plain_complete() -> None:
    from app.services import panel as panel_mod

    with (
        patch.object(panel_mod, "get_llm_config", return_value=_FakeConfig("ollama")),
        patch.object(panel_mod, "complete") as mock_complete,
    ):
        mock_complete.return_value = "from ollama"
        out = await panel_mod.complete_with_panel("prompt")
    assert out == "from ollama"
    mock_complete.assert_awaited_once()
