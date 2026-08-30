"""LLM audit ring buffer + LiteLLM callback.

Captures every LLM request and its response into an in-memory ring so the
frontend `/debug/llm` panel can show what the model was asked and what it
returned each time. Intentionally in-memory only: this is a live-debugging
convenience, not a persistent log. Resetting the container clears it.

Registered as a LiteLLM callback from app startup so it catches every path
in the codebase that goes through `litellm.acompletion` / `router.acompletion`,
without every call site having to opt in.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# Keeping only the last N is enough for live debugging; the frontend renders
# newest-first and users normally look at the last call after clicking Tailor.
# Bump this if a workflow chains > 50 calls in a row.
_MAX_ENTRIES = 50

_lock = threading.Lock()
_entries: deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)


def _summarize_messages(messages: Any) -> list[dict[str, Any]]:
    """LiteLLM passes messages as a list of {role, content}. We keep the shape
    the frontend expects (role + string content) and drop tool-call scaffolding
    that's noise for the panel. Non-string content (multipart) is stringified
    so the JSON stays serializable regardless of provider."""
    if not isinstance(messages, list):
        return []
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "unknown")
        content = msg.get("content")
        if content is None:
            content = ""
        elif not isinstance(content, str):
            # Multipart content (vision, tool calls) — flatten to text for now.
            content = str(content)
        out.append({"role": role, "content": content})
    return out


def _extract_response_text(response_obj: Any) -> str:
    """LiteLLM response objects follow OpenAI's ChatCompletion shape; the
    text lives at `.choices[0].message.content` (or as a dict at the same path
    when the object is already serialized). Falls back to `str(response)` when
    the shape is unexpected so we still record something rather than dropping
    the call from the log."""
    try:
        choices = getattr(response_obj, "choices", None)
        if choices is None and isinstance(response_obj, dict):
            choices = response_obj.get("choices")
        if not choices:
            return str(response_obj) if response_obj else ""
        first = choices[0]
        message = getattr(first, "message", None) or (
            first.get("message") if isinstance(first, dict) else None
        )
        if message is None:
            return str(first)
        content = getattr(message, "content", None) or (
            message.get("content") if isinstance(message, dict) else None
        )
        return content or ""
    except Exception:
        return str(response_obj) if response_obj else ""


def _extract_usage(response_obj: Any) -> dict[str, int] | None:
    """Pull the usage block if the provider returned one (most do; Ollama
    reports prompt_eval_count / eval_count that LiteLLM normalizes into
    prompt_tokens / completion_tokens). Missing usage isn't an error."""
    usage = getattr(response_obj, "usage", None)
    if usage is None and isinstance(response_obj, dict):
        usage = response_obj.get("usage")
    if usage is None:
        return None
    try:
        # Cover both pydantic BaseModel and dict shapes.
        pt = getattr(usage, "prompt_tokens", None)
        ct = getattr(usage, "completion_tokens", None)
        tt = getattr(usage, "total_tokens", None)
        if pt is None and isinstance(usage, dict):
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            tt = usage.get("total_tokens")
        return {
            "prompt_tokens": int(pt) if pt is not None else 0,
            "completion_tokens": int(ct) if ct is not None else 0,
            "total_tokens": int(tt) if tt is not None else 0,
        }
    except Exception:
        return None


def record_call(
    *,
    kwargs: dict[str, Any] | None,
    response_obj: Any = None,
    start_time: float | None = None,
    end_time: float | None = None,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Append one LiteLLM call to the ring. Never raises — a broken audit
    entry must never break the real LLM call it was observing."""
    try:
        kwargs = kwargs or {}
        messages = _summarize_messages(kwargs.get("messages"))
        response_text = _extract_response_text(response_obj) if response_obj is not None else ""
        latency_ms: int | None = None
        if start_time is not None and end_time is not None:
            latency_ms = int((end_time - start_time) * 1000)
        entry = {
            "id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "model": kwargs.get("model"),
            "api_base": kwargs.get("api_base"),
            "status": status,
            "error": error,
            "latency_ms": latency_ms,
            "usage": _extract_usage(response_obj),
            "messages": messages,
            "response": response_text,
            # Keep a few generation params so the UI can show what was requested.
            "params": {
                k: kwargs.get(k)
                for k in ("temperature", "max_tokens", "response_format", "reasoning_effort")
                if k in kwargs
            },
        }
        with _lock:
            _entries.append(entry)
    except Exception:
        logger.exception("llm_audit: failed to record call")


def get_entries(limit: int | None = None) -> list[dict[str, Any]]:
    """Return a snapshot of the buffer, newest-first."""
    with _lock:
        items = list(_entries)
    items.reverse()
    if limit is not None:
        items = items[:limit]
    return items


def clear_entries() -> int:
    """Wipe the buffer; returns how many entries were dropped."""
    with _lock:
        n = len(_entries)
        _entries.clear()
    return n


# Base class comes from LiteLLM. Duck-typing an object with these methods is
# NOT enough — LiteLLM does an isinstance(cb, CustomLogger) gate before it
# calls any handler, silently skipping anything that doesn't pass. Inheriting
# ties us to LiteLLM's import graph, but that's already a hard runtime dep of
# this app, so no new coupling.
try:
    from litellm.integrations.custom_logger import CustomLogger as _CustomLoggerBase
except Exception:  # pragma: no cover — import guard for tests that stub litellm
    class _CustomLoggerBase:  # type: ignore[no-redef]
        pass


class _LiteLLMAuditCallback(_CustomLoggerBase):
    """Concrete LiteLLM CustomLogger that records every LLM call into the
    audit ring. Overriding the sync AND async success/failure hooks means we
    catch both `litellm.acompletion()` (async) and `litellm.completion()`
    (sync) paths without depending on which one this app uses today."""

    def log_pre_api_call(self, model, messages, kwargs):
        # No-op: we record on completion so latency and usage are known.
        return None

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        record_call(
            kwargs=kwargs,
            response_obj=response_obj,
            start_time=_ts_to_float(start_time),
            end_time=_ts_to_float(end_time),
            status="success",
        )

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # LiteLLM invokes async_* on async completion paths.
        self.log_success_event(kwargs, response_obj, start_time, end_time)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        record_call(
            kwargs=kwargs,
            response_obj=response_obj,
            start_time=_ts_to_float(start_time),
            end_time=_ts_to_float(end_time),
            status="failure",
            error=str(kwargs.get("exception") or response_obj or "unknown"),
        )

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self.log_failure_event(kwargs, response_obj, start_time, end_time)


def _ts_to_float(ts: Any) -> float | None:
    """LiteLLM passes timestamps as datetime, float, or None depending on
    version and provider. Normalize to POSIX seconds so latency math is boring."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        # datetime.datetime
        return ts.timestamp()  # type: ignore[no-any-return, attr-defined]
    except Exception:
        return None


_audit_callback: _LiteLLMAuditCallback | None = None


def install() -> None:
    """Register the audit callback on the LiteLLM global. Safe to call
    multiple times — subsequent calls are no-ops.

    Registers on THREE lists: `callbacks`, `success_callback`, and
    `failure_callback`. LiteLLM's Router (which this app uses) historically
    read from `success_callback` while direct `litellm.acompletion()` calls
    also consult `callbacks`; different versions have shifted which one
    fires. Registering on all three costs nothing (we only append the same
    instance once per list) and guarantees the audit fires regardless of
    which path the LLM call goes through.
    """
    global _audit_callback
    if _audit_callback is not None:
        return
    try:
        import litellm  # local import so tests can stub the module

        cb = _LiteLLMAuditCallback()
        for attr in ("callbacks", "success_callback", "failure_callback"):
            existing = list(getattr(litellm, attr, []) or [])
            if not any(isinstance(x, _LiteLLMAuditCallback) for x in existing):
                existing.append(cb)
                setattr(litellm, attr, existing)
        _audit_callback = cb
        # WARNING (not INFO) so the confirmation is visible under uvicorn's
        # default log level — INFO from app.* is filtered in production.
        logger.warning("llm_audit: registered LiteLLM callback on callbacks/success_callback/failure_callback")
    except Exception:
        logger.exception("llm_audit: failed to register LiteLLM callback")


def state_snapshot() -> dict[str, Any]:
    """Diagnostic view of the audit's own state — for the /debug/state
    endpoint. Never touches request data; only self-describes."""
    installed = _audit_callback is not None
    litellm_state: dict[str, Any] = {}
    try:
        import litellm

        for attr in ("callbacks", "success_callback", "failure_callback"):
            values = getattr(litellm, attr, None) or []
            litellm_state[attr] = [type(v).__name__ for v in values]
    except Exception as e:
        litellm_state["_error"] = str(e)
    with _lock:
        entry_count = len(_entries)
    return {
        "installed": installed,
        "callback_class": type(_audit_callback).__name__ if _audit_callback else None,
        "entry_count": entry_count,
        "litellm": litellm_state,
    }
