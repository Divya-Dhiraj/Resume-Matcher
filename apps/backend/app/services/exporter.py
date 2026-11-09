"""Auto-exporter: writes finished CV + cover letter (PDF + DOCX) to the
host-mounted /app/exports directory the moment a tailor or cover-letter
generation finishes.

Folder layout on the host (via docker-compose volume mount to
~/Desktop/Resume Matcher/):

    Resume Matcher/
        <Company>/
            <Role>/
                CV.pdf
                CV.docx
                Cover Letter.pdf
                Cover Letter.docx
                job-description.txt      (plain text, for reference)

Design notes:
    * Fire-and-forget: callers await export_tailored_bundle() as a
      background task; export failures must not break the user-facing
      generate / tailor response.
    * Idempotent: writing to the same (company, role) folder overwrites —
      a user re-tailoring the same role replaces the files.
    * Safe filenames: sanitize company / role so a slash in "L'Oréal /
      Paris" doesn't escape the export root.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import db
from app.pdf import PDFRenderError, render_resume_pdf
from app.services.docx_renderer import render_cover_letter_docx, render_cv_docx

logger = logging.getLogger(__name__)


EXPORT_ROOT = Path(os.environ.get("EXPORT_ROOT", "/app/exports"))


def _safe_component(s: str | None, fallback: str = "Untitled") -> str:
    """Reduce a company/role string to a safe filesystem path component.

    Allows letters, digits, space, hyphen, underscore, dot, ampersand, and
    a handful of common accented characters. Everything else becomes a
    space. Collapses runs of whitespace and trims.
    """
    if not s:
        return fallback
    cleaned = re.sub(r"[^\w .\-&()']", " ", s, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def _resume_title_fallback(resume: dict) -> tuple[str, str]:
    """When a resume has no explicit company/role, split its title.

    Resume titles from the backend look like "Senior BI Engineer @ Hügli"
    — split on " @ " to recover both pieces.
    """
    title = (resume.get("title") or "").strip()
    if " @ " in title:
        role, company = title.split(" @ ", 1)
        return company.strip(), role.strip()
    return "Untitled Company", title or (resume.get("filename") or "Untitled Role")


async def _resolve_company_role(resume_id: str) -> tuple[str, str]:
    """Pull company/role from the job this resume was tailored for, with
    a fallback to the resume's own title when there's no job link."""
    resume = await db.get_resume(resume_id)
    if not resume:
        return "Unknown Company", resume_id[:8]

    job_id = resume.get("job_id")
    if job_id:
        job = await db.get_job(job_id)
        if job:
            company = (job.get("company") or "").strip()
            role = (job.get("role") or "").strip()
            if company or role:
                return (company or "Untitled Company", role or "Untitled Role")

    return _resume_title_fallback(resume)


async def _render_cv_pdf(resume_id: str) -> bytes:
    """Render the CV PDF using the default template settings."""
    url = f"{settings.frontend_base_url}/print/resumes/{resume_id}?template=swiss-single&pageSize=A4"
    return await render_resume_pdf(url, "A4", selector=".resume-print")


async def _render_cover_letter_pdf(resume_id: str) -> bytes | None:
    """Render the cover-letter PDF if one exists; return None if there is
    no cover letter attached to this resume."""
    resume = await db.get_resume(resume_id)
    cl = (resume or {}).get("cover_letter")
    if not cl or not str(cl).strip():
        return None
    url = f"{settings.frontend_base_url}/print/cover-letter/{resume_id}?pageSize=A4"
    return await render_resume_pdf(url, "A4", selector=".cover-letter-print")


async def export_tailored_bundle(resume_id: str, *, write_jd: bool = True) -> dict[str, str]:
    """Export CV + cover letter (PDF + DOCX) to the mounted export dir.

    Returns {"dir": str, "files": {kind: path}} — primarily for tests and
    for the router to echo back to the UI. Logs warnings and keeps going
    if any single artifact fails so a late DOCX exception doesn't block
    the PDFs that already succeeded.
    """
    if not EXPORT_ROOT.exists():
        logger.warning(
            "export root %s does not exist — skipping export. Mount the "
            "host folder via docker-compose or create it inside the container.",
            EXPORT_ROOT,
        )
        return {"dir": "", "files": {}}

    resume = await db.get_resume(resume_id)
    if not resume:
        logger.warning("export: resume %s not found", resume_id)
        return {"dir": "", "files": {}}

    company, role = await _resolve_company_role(resume_id)
    folder = EXPORT_ROOT / _safe_component(company) / _safe_component(role)
    folder.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}

    # CV PDF
    try:
        cv_pdf = await _render_cv_pdf(resume_id)
        cv_pdf_path = folder / "CV.pdf"
        cv_pdf_path.write_bytes(cv_pdf)
        paths["cv_pdf"] = str(cv_pdf_path)
    except PDFRenderError as e:
        logger.warning("export CV pdf failed for %s: %s", resume_id, e)
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("export CV pdf unexpected failure: %s", e)

    # CV DOCX (always possible — pulls directly from processed_data)
    processed = resume.get("processed_data") or {}
    if processed:
        try:
            cv_docx_path = folder / "CV.docx"
            render_cv_docx(processed, cv_docx_path)
            paths["cv_docx"] = str(cv_docx_path)
        except Exception as e:  # pragma: no cover
            logger.exception("export CV docx failed: %s", e)

    # Cover letter — only if one exists.
    cl_text = (resume.get("cover_letter") or "").strip()
    if cl_text:
        try:
            cl_docx_path = folder / "Cover Letter.docx"
            render_cover_letter_docx(cl_text, cl_docx_path)
            paths["cover_letter_docx"] = str(cl_docx_path)
        except Exception as e:  # pragma: no cover
            logger.exception("export CL docx failed: %s", e)
        try:
            cl_pdf = await _render_cover_letter_pdf(resume_id)
            if cl_pdf:
                cl_pdf_path = folder / "Cover Letter.pdf"
                cl_pdf_path.write_bytes(cl_pdf)
                paths["cover_letter_pdf"] = str(cl_pdf_path)
        except PDFRenderError as e:
            logger.warning("export CL pdf failed for %s: %s", resume_id, e)
        except Exception as e:  # pragma: no cover
            logger.exception("export CL pdf unexpected failure: %s", e)

    # Job description plain-text copy (nice reference next to the outputs).
    if write_jd and resume.get("job_id"):
        job = await db.get_job(resume["job_id"])
        jd = (job or {}).get("content") or ""
        if jd.strip():
            try:
                jd_path = folder / "job-description.txt"
                jd_path.write_text(jd.strip(), encoding="utf-8")
                paths["jd"] = str(jd_path)
            except Exception as e:  # pragma: no cover
                logger.exception("export JD failed: %s", e)

    logger.info(
        "exported %d artifacts for resume=%s to %s", len(paths), resume_id, folder
    )
    return {"dir": str(folder), "files": paths}
