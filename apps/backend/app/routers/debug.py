"""Debug endpoints — currently just an LLM inspector.

Intentionally scoped tightly: these expose in-memory diagnostic data and are
not gated behind auth (the app has none), so anything that could leak secrets
should NOT be added here without a real auth model. Prompt/response text can
still contain the user's resume content and pasted JD text, which is exactly
what makes the panel useful — that's not a leak given the app runs locally.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import llm_audit

router = APIRouter(prefix="/api/v1/debug", tags=["Debug"])


@router.get("/llm-calls")
async def list_llm_calls(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Return the recent LLM calls newest-first. Limit exists so an aggressive
    poll can't churn on a huge payload; the ring itself is capped separately."""
    return {"calls": llm_audit.get_entries(limit=limit)}


@router.delete("/llm-calls")
async def clear_llm_calls() -> dict:
    """Wipe the in-memory audit buffer. Returns the count of dropped entries
    so the UI can show a confirmation ("cleared 12 calls")."""
    dropped = llm_audit.clear_entries()
    return {"dropped": dropped}


@router.get("/state")
async def audit_state() -> dict:
    """Diagnostic view of the audit itself — whether the callback is
    registered, how many entries are buffered, which LiteLLM callback lists
    reference it. Useful when the inspector shows 0 calls to distinguish
    'nothing happened yet' from 'callback wiring is broken'."""
    return llm_audit.state_snapshot()
