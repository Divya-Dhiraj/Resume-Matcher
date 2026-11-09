"""Tests for the host-mount auto-exporter.

Covers:
    - _safe_component sanitises company/role to safe path parts.
    - _resolve_company_role prefers the linked job's company/role, falls
      back to "<role> @ <company>" in the resume title, and handles neither.
    - render_cv_docx + render_cover_letter_docx produce opening-bytes-valid
      files for realistic ResumeData shapes (dict description AND list-of-
      bullets description — the real bug that crashed on live data).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.docx_renderer import render_cover_letter_docx, render_cv_docx
from app.services.exporter import _resolve_company_role, _safe_component


def test_safe_component_strips_slashes_and_collapses_whitespace():
    assert _safe_component("L'Oréal / Paris") == "L'Oréal Paris"
    assert _safe_component("  Senior   BI   Engineer ") == "Senior BI Engineer"
    assert _safe_component("") == "Untitled"
    assert _safe_component(None) == "Untitled"


def test_safe_component_blocks_path_traversal():
    # The sanitizer must reduce any ../ pattern to safe characters so the
    # export root can't be escaped by a hostile company/role string.
    out = _safe_component("../../../etc/passwd")
    assert ".." not in out or "/" not in out
    assert "/" not in out


class _StubDB:
    def __init__(self, resume: dict | None = None, job: dict | None = None) -> None:
        self._resume = resume
        self._job = job

    async def get_resume(self, rid: str):
        return self._resume

    async def get_job(self, jid: str):
        return self._job


@pytest.mark.asyncio
async def test_resolve_company_role_from_linked_job():
    stub = _StubDB(
        resume={"resume_id": "r", "job_id": "j", "title": "whatever"},
        job={"company": "Hügli", "role": "BI Specialist"},
    )
    with patch("app.services.exporter.db", stub):
        c, r = await _resolve_company_role("r")
    assert (c, r) == ("Hügli", "BI Specialist")


@pytest.mark.asyncio
async def test_resolve_company_role_falls_back_to_resume_title():
    stub = _StubDB(
        resume={"resume_id": "r", "title": "Senior BI Engineer @ Stripe"},
        job=None,
    )
    with patch("app.services.exporter.db", stub):
        c, r = await _resolve_company_role("r")
    assert (c, r) == ("Stripe", "Senior BI Engineer")


@pytest.mark.asyncio
async def test_resolve_company_role_handles_no_job_no_title():
    stub = _StubDB(resume={"resume_id": "r", "filename": "cv.pdf"}, job=None)
    with patch("app.services.exporter.db", stub):
        c, r = await _resolve_company_role("r")
    assert c == "Untitled Company"
    assert "cv" in r.lower() or r == "Untitled Role"


def test_render_cv_docx_writes_zip_file(tmp_path: Path):
    resume = {
        "personalInfo": {"name": "Jane Doe", "email": "j@example.com"},
        "summary": "Short summary.",
        "workExperience": [
            {
                "title": "Engineer",
                "company": "Acme",
                "dates": "2021–2024",
                "description": ["Built a thing", "Shipped another thing"],
            }
        ],
        "education": [{"degree": "BSc", "institution": "Uni"}],
        "additional": {"technicalSkills": ["Python", "SQL"], "languages": ["English"]},
    }
    out = tmp_path / "cv.docx"
    render_cv_docx(resume, out)
    assert out.exists() and out.stat().st_size > 0
    # DOCX is a zip — opening bytes start with the PK zip signature.
    assert out.read_bytes()[:2] == b"PK"


def test_render_cv_docx_handles_list_description_in_custom_section(tmp_path: Path):
    """Regression for the live-data bug: a custom-section item's `description`
    is sometimes a list of bullets, not a single string. Must not crash."""
    resume = {
        "personalInfo": {"name": "Jane Doe"},
        "customSections": {
            "publications": {
                "sectionType": "itemList",
                "items": [
                    {"title": "Paper A", "description": ["Finding 1", "Finding 2"]},
                    {"title": "Paper B", "description": "Short string form"},
                ],
            }
        },
        "sectionMeta": [
            {"key": "publications", "displayName": "Publications", "hidden": False}
        ],
    }
    out = tmp_path / "cv.docx"
    render_cv_docx(resume, out)
    assert out.read_bytes()[:2] == b"PK"


def test_render_cover_letter_docx_writes_blocks(tmp_path: Path):
    text = "Dear hiring team,\n\nI am interested.\n\nSincerely,\nJane"
    out = tmp_path / "cl.docx"
    render_cover_letter_docx(text, out)
    assert out.read_bytes()[:2] == b"PK"
