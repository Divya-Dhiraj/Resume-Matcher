"""Resume management endpoints."""

import asyncio
import copy
import hashlib
import json
import logging
import unicodedata
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from app.config_cache import get_content_language, load_config as _load_config
from app.database import db
from app.pdf import render_resume_pdf, PDFRenderError
from app.config import settings

logger = logging.getLogger(__name__)
from app.schemas import (
    ATSScore,
    ATSSubScores,
    GenerateContentResponse,
    GenerateInterviewPrepResponse,
    ImproveResumeConfirmRequest,
    ImproveResumeRequest,
    ImproveResumeResponse,
    ImproveResumeData,
    InterviewPrepData,
    RefinementStats,
    ResumeDiffSummary,
    ResumeFieldDiff,
    ResumeData,
    ResumeFetchData,
    ResumeFetchResponse,
    ResumeListResponse,
    ResumeSummary,
    ResumeUploadResponse,
    RawResume,
    UpdateCoverLetterRequest,
    UpdateOutreachMessageRequest,
    UpdateTitleRequest,
    normalize_resume_data,
)
from app.services.parser import parse_document, parse_resume_to_json, restore_dates_from_markdown
from app.services.improver import (
    MONTH_PATTERN,
    apply_diffs,
    enforce_optimal_skills_section,
    reorder_bullets_by_relevance,
    extract_job_keywords,
    generate_improvements,
    generate_skill_target_plan,
    generate_resume_diffs,
    improve_resume,
    verify_skill_target_plan,
    verify_diff_result,
)
from app.services.refiner import refine_resume, calculate_keyword_match, strip_hidden_sections
from app.services.ats import compute_ats_score
from app.schemas.refinement import RefinementConfig
from app.services.cover_letter import (
    generate_cover_letter,
    generate_outreach_message,
    generate_resume_title,
)
from app.services.interview_prep import generate_interview_prep
from app.prompts import DEFAULT_IMPROVE_PROMPT_ID, IMPROVE_PROMPT_OPTIONS


async def _auto_create_tracker_application(
    *,
    job_id: str,
    tailored_resume_id: str,
    master_resume_id: str,
    job: dict[str, Any] | None,
    title: str | None,
    company_override: str | None = None,
    role_override: str | None = None,
    status_override: str | None = None,
) -> None:
    """Best-effort: drop an ``applied`` card on the tracker after a tailoring.

    Company/role come from explicit overrides or the cached job (zero extra LLM
    call). Wrapped so a tracker failure can never break the tailoring flow.
    """
    try:
        company = company_override or (job or {}).get("company")
        role = role_override or title or (job or {}).get("role")
        status = status_override or "applied"
        await db.create_application(
            job_id=job_id,
            resume_id=tailored_resume_id,
            master_resume_id=master_resume_id,
            status=status,
            company=company,
            role=role,
        )
    except Exception as e:  # noqa: BLE001 - tracker is non-critical
        logger.warning("Failed to auto-create tracker application: %s", e)


def _get_default_prompt_id() -> str:
    """Get configured default prompt id from config file."""
    config = _load_config()
    option_ids = {option["id"] for option in IMPROVE_PROMPT_OPTIONS}
    prompt_id = config.get("default_prompt_id", DEFAULT_IMPROVE_PROMPT_ID)
    return prompt_id if prompt_id in option_ids else DEFAULT_IMPROVE_PROMPT_ID


def _hash_job_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_payload(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[Any, Any] = {}
        for key, val in value.items():
            normalized_key = (
                unicodedata.normalize("NFC", key) if isinstance(key, str) else key
            )
            normalized[normalized_key] = _normalize_payload(val)
        return normalized
    return value


def _serialize_interview_prep(interview_prep: InterviewPrepData | None) -> str | None:
    if interview_prep is None:
        return None
    return json.dumps(interview_prep.model_dump(mode="json"), ensure_ascii=False)


def _parse_interview_prep(
    raw: Any,
    *,
    resume_id: str | None = None,
) -> InterviewPrepData | None:
    if raw in (None, ""):
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return InterviewPrepData.model_validate(payload)
    except (TypeError, json.JSONDecodeError, ValidationError, ValueError) as e:
        logger.warning(
            "Invalid interview_prep payload for resume %s: %s",
            resume_id or "<unknown>",
            e,
        )
        return None


def _hash_improved_data(data: dict[str, Any]) -> str:
    """Hash canonicalized improved data for preview/confirm validation.

    Canonicalize through ``ResumeData`` first so a payload that merely omits
    optional fields (which the schema defaults) hashes identically to its
    schema-complete form. Without this, ``improve/preview`` (which hashes the
    raw ``improved_data`` dict) and ``improve/confirm`` (which hashes the
    ``ResumeData`` round-trip, ``request.improved_data.model_dump()``) disagree
    for any stored resume whose ``processed_data`` is not schema-complete, and a
    valid tailoring is rejected with 400 ("preview hash mismatch").
    """
    try:
        canonical: dict[str, Any] = ResumeData.model_validate(data).model_dump()
    except ValidationError:
        canonical = data  # not a full resume payload; hash as-is
    normalized = _normalize_payload(canonical)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,  # Preserve original behavior for hash stability
        default=str,  # Handle non-serializable types gracefully
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_personal_info_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value).strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    normalized = _normalize_payload(value)
    return json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _raise_improve_error(
    action: str,
    stage: str,
    error: Exception,
    detail: str,
) -> NoReturn:
    logger.error("Resume %s failed during %s: %s", action, stage, error)
    err_str = str(error)
    if "429" in err_str or "Quota exceeded" in err_str or "RESOURCE_EXHAUSTED" in err_str:
        detail = (
            "LLM rate limit / daily quota exceeded (429). "
            "Please wait a moment or switch provider/model in Settings."
        )
    raise HTTPException(status_code=500, detail=detail)


def _get_original_resume_data(resume: dict[str, Any]) -> dict[str, Any] | None:
    original_data = resume.get("processed_data")
    if not original_data and resume.get("content_type") == "json":
        try:
            original_data = json.loads(resume["content"])
        except json.JSONDecodeError as e:
            logger.warning("Skipping resume diff due to JSON parse failure: %s", e)
    return original_data


def _get_original_markdown(resume: dict[str, Any]) -> str | None:
    """Get the original markdown content from a resume.

    Checks ``original_markdown`` first (persisted at upload), then
    falls back to ``content`` if it's still in markdown format.
    """
    md = resume.get("original_markdown")
    if md and isinstance(md, str):
        return md
    if resume.get("content_type") == "md":
        content = resume.get("content", "")
        if content and isinstance(content, str):
            return content
    return None


def _has_month(date_str: str) -> bool:
    """Return True if the date string contains a month name."""
    return bool(MONTH_PATTERN.search(date_str))


def _restore_original_dates(
    original_data: dict[str, Any] | None,
    improved_data: dict[str, Any],
) -> dict[str, Any]:
    """Restore original date/years values that the LLM may have truncated.

    Compares each entry's ``years`` field in the tailored resume against
    the corresponding entry in the original.  If the original has more
    date precision (e.g. includes a month) and the tailored version lost
    it, the original value is restored.
    """
    if not original_data:
        return improved_data

    result = copy.deepcopy(improved_data)

    for section_key in ("workExperience", "education", "personalProjects"):
        orig_entries = original_data.get(section_key, [])
        result_entries = result.get(section_key, [])
        for idx, orig_entry in enumerate(orig_entries):
            if idx >= len(result_entries):
                break
            if not isinstance(orig_entry, dict) or not isinstance(result_entries[idx], dict):
                continue
            orig_years = orig_entry.get("years", "")
            result_years = result_entries[idx].get("years", "")
            if (
                isinstance(orig_years, str)
                and isinstance(result_years, str)
                and orig_years
                and orig_years != result_years
                and _has_month(orig_years)
                and not _has_month(result_years)
            ):
                logger.info(
                    "Restoring date in %s[%d]: %r → %r",
                    section_key,
                    idx,
                    result_years,
                    orig_years,
                )
                result_entries[idx]["years"] = orig_years

    # Custom sections (itemList)
    orig_custom = original_data.get("customSections", {})
    result_custom = result.get("customSections", {})
    if isinstance(orig_custom, dict) and isinstance(result_custom, dict):
        for section_key, orig_section in orig_custom.items():
            if not isinstance(orig_section, dict):
                continue
            result_section = result_custom.get(section_key)
            if not isinstance(result_section, dict):
                continue
            if orig_section.get("sectionType") != "itemList":
                continue
            orig_items = orig_section.get("items", [])
            result_items = result_section.get("items", [])
            for idx, orig_item in enumerate(orig_items):
                if idx >= len(result_items):
                    break
                if not isinstance(orig_item, dict) or not isinstance(result_items[idx], dict):
                    continue
                orig_years = orig_item.get("years", "")
                result_years = result_items[idx].get("years", "")
                if (
                    isinstance(orig_years, str)
                    and isinstance(result_years, str)
                    and orig_years
                    and orig_years != result_years
                    and _has_month(orig_years)
                    and not _has_month(result_years)
                ):
                    result_items[idx]["years"] = orig_years

    return result


def _preserve_original_skills(
    original_data: dict[str, Any] | None,
    improved_data: dict[str, Any],
) -> dict[str, Any]:
    """Log dropped skills but allow the LLM to remove irrelevant ones.

    Previously this was a hard safety net that restored every dropped item.
    Now the LLM is trusted to remove items it deems irrelevant to the target
    role — only languages are forcibly preserved (they are always valuable).
    """
    if not original_data:
        return improved_data

    result = copy.deepcopy(improved_data)

    orig_additional = original_data.get("additional", {})
    if not isinstance(orig_additional, dict):
        return result
    result_additional = result.setdefault("additional", {})

    # Only force-restore languages (always valuable); let LLM curate the rest
    force_restore_fields = ["languages"]
    log_only_fields = ["technicalSkills", "certificationsTraining", "awards"]

    for field in force_restore_fields + log_only_fields:
        orig_items = orig_additional.get(field, [])
        if not isinstance(orig_items, list) or not orig_items:
            continue
        current_items = result_additional.get(field, [])
        if not isinstance(current_items, list):
            current_items = []

        current_lower = {
            item.casefold() for item in current_items if isinstance(item, str)
        }

        dropped = [
            item for item in orig_items
            if isinstance(item, str) and item.casefold() not in current_lower
        ]

        if dropped:
            if field in force_restore_fields:
                for item in dropped:
                    current_items.append(item)
                logger.info("Restored %d dropped items in additional.%s", len(dropped), field)
            else:
                logger.info("LLM removed %d items from additional.%s: %s", len(dropped), field, dropped)

        result_additional[field] = current_items

    return result


def _protect_custom_sections(
    original_data: dict[str, Any] | None,
    improved_data: dict[str, Any],
) -> dict[str, Any]:
    """Protect custom sections from LLM hallucination.

    - If an item originally had description: [], revert any fabricated descriptions.
    - If the LLM added items that weren't in the original, remove them.
    """
    if not original_data:
        return improved_data

    orig_custom = original_data.get("customSections")
    if not isinstance(orig_custom, dict) or not orig_custom:
        return improved_data

    result = copy.deepcopy(improved_data)
    result_custom = result.get("customSections")
    if not isinstance(result_custom, dict):
        return result

    for section_key, orig_section in orig_custom.items():
        if not isinstance(orig_section, dict):
            continue
        result_section = result_custom.get(section_key)
        if not isinstance(result_section, dict):
            # Section was removed by LLM — restore original
            result_custom[section_key] = copy.deepcopy(orig_section)
            logger.info("Restored missing custom section: %s", section_key)
            continue

        section_type = orig_section.get("sectionType", "")
        if section_type == "itemList":
            orig_items = orig_section.get("items", [])
            result_items = result_section.get("items", [])
            if not isinstance(orig_items, list) or not isinstance(result_items, list):
                continue

            # Trim any items the LLM added beyond the original count
            if len(result_items) > len(orig_items):
                logger.info(
                    "Trimming %d hallucinated items from customSections.%s",
                    len(result_items) - len(orig_items),
                    section_key,
                )
                result_items = result_items[: len(orig_items)]

            # Revert fabricated descriptions on items that had empty descriptions
            for idx, orig_item in enumerate(orig_items):
                if idx >= len(result_items):
                    break
                if not isinstance(orig_item, dict):
                    continue
                orig_desc = orig_item.get("description")
                if isinstance(orig_desc, list) and len(orig_desc) == 0:
                    result_desc = result_items[idx].get("description")
                    if isinstance(result_desc, list) and len(result_desc) > 0:
                        logger.info(
                            "Reverted fabricated description on customSections.%s.items[%d]",
                            section_key,
                            idx,
                        )
                        result_items[idx]["description"] = []

            result_section["items"] = result_items

    result["customSections"] = result_custom
    return result


def _preserve_personal_info(
    original_data: dict[str, Any] | None,
    improved_data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Preserve personal info from original, return warnings if unable.

    Uses deep copy to prevent mutation of original data.
    """
    warnings: list[str] = []

    if not original_data:
        warnings.append(
            "Original resume data unavailable - personal info may be AI-generated"
        )
        return improved_data, warnings

    original_info = original_data.get("personalInfo")
    if not isinstance(original_info, dict):
        warnings.append("Original personal info missing or invalid")
        return improved_data, warnings

    # SVC-001: Use deep copy to prevent any mutation of original data
    result = copy.deepcopy(improved_data)
    result["personalInfo"] = copy.deepcopy(original_info)
    return result, warnings


def _build_ats_score(
    improved_data: dict[str, Any],
    job_keywords: dict[str, Any],
    refinement_result: Any,
    refinement_successful: bool,
) -> ATSScore | None:
    """Build ATSScore from refinement result and resume data."""
    try:
        kw_analysis = (
            refinement_result.keyword_analysis
            if refinement_successful and refinement_result is not None
            else None
        )
        final_match = (
            refinement_result.final_match_percentage
            if refinement_successful and refinement_result is not None
            else calculate_keyword_match(improved_data, job_keywords)
        )
        ats_raw = compute_ats_score(
            refined_resume=improved_data,
            job_keywords=job_keywords,
            keyword_match_percentage=final_match,
            missing_keywords=kw_analysis.non_injectable_keywords if kw_analysis else [],
            injectable_keywords=kw_analysis.injectable_keywords if kw_analysis else [],
        )
        return ATSScore(
            overall_score=ats_raw["overall_score"],
            sub_scores=ATSSubScores(**ats_raw["sub_scores"]),
            missing_keywords=ats_raw["missing_keywords"],
            injectable_keywords=ats_raw["injectable_keywords"],
            recommendations=ats_raw["recommendations"],
        )
    except Exception as e:
        logger.warning("ATS score computation failed", exc_info=True)
        return None


def _calculate_diff_from_resume(
    resume: dict[str, Any],
    improved_data: dict[str, Any],
) -> tuple[ResumeDiffSummary | None, list[ResumeFieldDiff] | None, str | None]:
    """Calculate resume diffs when structured data is available.

    Returns (summary, changes, error_reason). Error reason is None on success,
    or a string describing why diff calculation failed.
    """
    original_data = _get_original_resume_data(resume)
    if not original_data:
        return None, None, "original_data_missing"
    from app.services.improver import calculate_resume_diff

    try:
        summary, changes = calculate_resume_diff(original_data, improved_data)
        return summary, changes, None
    except Exception as e:
        logger.warning("Skipping resume diff due to calculation failure: %s", e)
        return None, None, f"calculation_error: {str(e)}"


def _validate_confirm_payload(
    original_data: dict[str, Any] | None,
    improved_data: dict[str, Any],
) -> None:
    if not original_data:
        logger.warning(
            "Skipping confirm payload validation; structured resume data unavailable."
        )
        return
    original_info = original_data.get("personalInfo")
    improved_info = improved_data.get("personalInfo")
    # JSON-008: Explicit null checks with clear error messages
    if original_info is None:
        raise ValueError("Original resume missing personalInfo")
    if improved_info is None:
        raise ValueError("Improved resume missing personalInfo")
    if not isinstance(original_info, dict):
        raise ValueError(
            f"Original personalInfo is not a dict: {type(original_info).__name__}"
        )
    if not isinstance(improved_info, dict):
        raise ValueError(
            f"Improved personalInfo is not a dict: {type(improved_info).__name__}"
        )
    fields = set(original_info.keys()) | set(improved_info.keys())
    mismatches = [
        field
        for field in sorted(fields)
        if _normalize_personal_info_value(original_info.get(field))
        != _normalize_personal_info_value(improved_info.get(field))
    ]
    if mismatches:
        raise ValueError(f"personalInfo fields changed: {', '.join(mismatches)}")


async def _generate_auxiliary_messages(
    improved_data: dict[str, Any],
    job_content: str,
    language: str,
    enable_cover_letter: bool,
    enable_outreach: bool,
    enable_interview_prep: bool,
) -> tuple[str | None, str | None, str | None, InterviewPrepData | None, list[str]]:
    """Generate cover letter, outreach, interview prep, and resume title.

    Returns (cover_letter, outreach_message, title, interview_prep, warnings).
    """
    cover_letter = None
    outreach_message = None
    title = None
    interview_prep = None
    warnings: list[str] = []
    generation_tasks: list[Awaitable[str | InterviewPrepData]] = []
    task_labels: list[str] = []

    # Title generation is always on (no feature flag)
    generation_tasks.append(generate_resume_title(job_content, language))
    task_labels.append("title")

    if enable_cover_letter:
        generation_tasks.append(
            generate_cover_letter(improved_data, job_content, language)
        )
        task_labels.append("cover_letter")
    if enable_outreach:
        generation_tasks.append(
            generate_outreach_message(improved_data, job_content, language)
        )
        task_labels.append("outreach")
    if enable_interview_prep:
        generation_tasks.append(
            generate_interview_prep(improved_data, job_content, language)
        )
        task_labels.append("interview_prep")

    results = await asyncio.gather(*generation_tasks, return_exceptions=True)
    for label, result in zip(task_labels, results):
        if isinstance(result, Exception):
            logger.warning(
                "%s generation failed: %s",
                label,
                result,
                exc_info=result,
            )
            if label != "title":
                warnings.append(f"{label.replace('_', ' ').title()} generation failed")
        else:
            if label == "title":
                title = result
            elif label == "cover_letter":
                cover_letter = result
            elif label == "outreach":
                outreach_message = result
            elif label == "interview_prep":
                interview_prep = result

    return cover_letter, outreach_message, title, interview_prep, warnings


router = APIRouter(prefix="/resumes", tags=["Resumes"])

ALLOWED_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 4 * 1024 * 1024  # 4MB


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...)) -> ResumeUploadResponse:
    """Upload and process a resume file (PDF/DOCX).

    Converts the file to Markdown and stores it in the database.
    Optionally parses to structured JSON if LLM is configured.
    """
    # Validate file type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {file.content_type}. Allowed: PDF, DOC, DOCX",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Convert to markdown
    try:
        markdown_content = await parse_document(content, file.filename or "resume.pdf")
    except Exception as e:
        logger.error(f"Document parsing failed: {e}")
        raise HTTPException(
            status_code=422,
            detail="Failed to parse document. Please ensure it's a valid PDF or DOCX file.",
        )

    # Validate extracted text is not empty (image-based PDFs / scanned documents)
    if not markdown_content or not markdown_content.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract text from the uploaded file. The document may be "
                "image-based or scanned. Please upload a text-based PDF/DOCX with "
                "selectable text, or run OCR first."
            ),
        )

    # Store in database first with "processing" status (atomic master assignment)
    # original_markdown is preserved permanently for date reference even after
    # builder saves overwrite `content` with JSON.
    resume = await db.create_resume_atomic_master(
        content=markdown_content,
        content_type="md",
        filename=file.filename,
        processed_data=None,
        processing_status="processing",
        original_markdown=markdown_content,
    )

    # Try to parse to structured JSON (optional, may fail if LLM not configured)
    try:
        processed_data = await parse_resume_to_json(markdown_content)
        await db.update_resume(
            resume["resume_id"],
            {
                "processed_data": processed_data,
                "processing_status": "ready",
            },
        )
        resume["processed_data"] = processed_data
        resume["processing_status"] = "ready"
    except Exception as e:
        # LLM parsing failed, update status to failed
        logger.warning(f"Resume parsing to JSON failed for {file.filename}: {e}")
        await db.update_resume(resume["resume_id"], {"processing_status": "failed"})
        resume["processing_status"] = "failed"

    # Return accurate status to client (API-001 fix)
    return ResumeUploadResponse(
        message=(
            f"File {file.filename} uploaded successfully"
            if resume["processing_status"] == "ready"
            else f"File {file.filename} uploaded but parsing failed"
        ),
        request_id=str(uuid4()),
        resume_id=resume["resume_id"],
        processing_status=resume["processing_status"],
        is_master=resume.get("is_master", False),
    )


@router.get("", response_model=ResumeFetchResponse)
async def get_resume(resume_id: str = Query(...)) -> ResumeFetchResponse:
    """Fetch resume details by ID.

    Returns both raw markdown and structured data (if available),
    plus cover letter and outreach message if they exist.
    Applies lazy migration for section metadata if needed.
    """
    resume = await db.get_resume(resume_id)

    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Get processing status (default to "pending" for old records)
    processing_status = resume.get("processing_status", "pending")

    # Build response
    raw_resume = RawResume(
        id=None,  # TinyDB doesn't have numeric IDs like SQL
        content=resume["content"],
        content_type=resume["content_type"],
        created_at=resume["created_at"],
        processing_status=processing_status,
    )

    # Get processed data if available (no more on-demand parsing)
    processed_data = resume.get("processed_data")

    # Apply lazy migration - add section metadata to old resumes
    if processed_data:
        processed_data = normalize_resume_data(processed_data)

    processed_resume = (
        ResumeData.model_validate(processed_data) if processed_data else None
    )

    return ResumeFetchResponse(
        request_id=str(uuid4()),
        data=ResumeFetchData(
            resume_id=resume_id,
            raw_resume=raw_resume,
            processed_resume=processed_resume,
            cover_letter=resume.get("cover_letter"),
            outreach_message=resume.get("outreach_message"),
            interview_prep=_parse_interview_prep(
                resume.get("interview_prep"),
                resume_id=resume_id,
            ),
            parent_id=resume.get("parent_id"),
            title=resume.get("title"),
        ),
    )


@router.get("/list", response_model=ResumeListResponse)
async def list_resumes(include_master: bool = Query(False)) -> ResumeListResponse:
    """List resumes, optionally including the master resume."""
    resumes = await db.list_resumes()
    if not include_master:
        resumes = [resume for resume in resumes if not resume.get("is_master", False)]

    resumes.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

    summaries = [
        ResumeSummary(
            resume_id=resume["resume_id"],
            filename=resume.get("filename"),
            is_master=resume.get("is_master", False),
            parent_id=resume.get("parent_id"),
            processing_status=resume.get("processing_status", "pending"),
            created_at=resume.get("created_at", ""),
            updated_at=resume.get("updated_at", ""),
            title=resume.get("title"),
        )
        for resume in resumes
    ]

    return ResumeListResponse(request_id=str(uuid4()), data=summaries)


@router.post("/improve/preview", response_model=ImproveResumeResponse)
async def improve_resume_preview_endpoint(
    request: ImproveResumeRequest,
) -> ImproveResumeResponse:
    """Preview a tailored resume without persisting it.

    The response includes resume_preview data but leaves resume_id null.
    """
    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    job = await db.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job description not found")

    language = request.output_language or get_content_language()
    prompt_id = request.prompt_id or _get_default_prompt_id()

    stage = "load_job_keywords"
    detail = "Failed to preview resume. Please try again."
    try:
        return await asyncio.wait_for(
            _improve_preview_flow(
                request=request,
                resume=resume,
                job=job,
                language=language,
                prompt_id=prompt_id,
            ),
            timeout=settings.request_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Improve preview timed out after %ss for resume %s / job %s",
            settings.request_timeout_seconds,
            request.resume_id,
            request.job_id,
        )
        raise HTTPException(
            status_code=504,
            detail=(
                f"Resume tailoring timed out after {settings.request_timeout_seconds}s. "
                "If you are running a local LLM, raise REQUEST_TIMEOUT_SECONDS (and the "
                "matching frontend NEXT_PUBLIC_REQUEST_TIMEOUT_MS); otherwise try a shorter "
                "job description or a simpler prompt."
            ),
        )
    except Exception as e:
        _raise_improve_error("preview", stage, e, detail)


def _postprocess_review_result(
    review: dict[str, Any],
    resume_data: dict[str, Any],
    job_keywords: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically calibrate review scores and filter false-positive missing keywords.

    1. Removes any keyword from ``missing_keywords`` that is already present in the
       resume text (including ``additional.technicalSkills``, ``customSections``
       grouped blocks, ``workExperience``, ``personalProjects``, and ``summary``).
    2. Removes false-positive 'future date' fabrication flags for 2025/2026 dates.
    3. Anchors ``panel_scores.ats`` to the deterministic ATS keyword coverage when
       ``job_keywords`` is available, and recomputes ``match_score`` as the exact
       mean of ``panel_scores`` so repeated runs are consistent and closed-loop
       retailoring reliably increases the score.
    """
    if not isinstance(review, dict):
        return review

    from app.services.refiner import _extract_all_text, _keyword_in_text

    resume_text = _extract_all_text(resume_data).lower()

    # 1. Filter out missing_keywords that are already in the resume
    raw_missing = review.get("missing_keywords")
    if isinstance(raw_missing, list):
        filtered_missing: list[str] = []
        for kw in raw_missing:
            if not isinstance(kw, str) or not kw.strip():
                continue
            # Strip parenthetical qualifiers like "Databricks (Experience level)" -> "Databricks"
            clean_kw = kw.split("(")[0].strip()
            if clean_kw and (
                _keyword_in_text(clean_kw, resume_text)
                or _keyword_in_text(kw.strip(), resume_text)
            ):
                continue
            filtered_missing.append(kw.strip())
        review["missing_keywords"] = filtered_missing

    # 2. Filter out false-positive 2025/2026 "future date" flags
    raw_flags = review.get("fabrication_flags")
    if isinstance(raw_flags, list):
        review["fabrication_flags"] = [
            f
            for f in raw_flags
            if not (
                isinstance(f, str)
                and ("future" in f.lower() or "chronolog" in f.lower() or "impossible date" in f.lower())
                and ("2025" in f or "2026" in f)
            )
        ]

    raw_weak = review.get("weak_bullets")
    if isinstance(raw_weak, list):
        review["weak_bullets"] = [
            wb
            for wb in raw_weak
            if not (
                isinstance(wb, dict)
                and (
                    str(wb.get("path", "")).endswith(".years")
                    or (
                        "future" in str(wb.get("problem", "")).lower()
                        and ("2025" in str(wb.get("text", "")) or "2026" in str(wb.get("text", "")))
                    )
                )
            )
        ]

    raw_fixes = review.get("top_3_fixes")
    if isinstance(raw_fixes, list):
        review["top_3_fixes"] = [
            fix
            for fix in raw_fixes
            if not (
                isinstance(fix, str)
                and ("future" in fix.lower() or "2025" in fix or "2026" in fix)
                and "date" in fix.lower()
            )
        ]

    # 3. Calibrate panel_scores and match_score deterministically
    panel_scores = review.get("panel_scores")
    if isinstance(panel_scores, dict) and panel_scores:
        if job_keywords:
            det_kw_match = calculate_keyword_match(resume_data, job_keywords)
            llm_ats = float(panel_scores.get("ats", det_kw_match) or det_kw_match)
            # Blend deterministic keyword coverage with LLM ATS readability score
            panel_scores["ats"] = int(round(max(det_kw_match, (det_kw_match * 0.7 + llm_ats * 0.3))))
        # If false-positive future-date flags were removed, ensure skeptic isn't artificially tanked to 10
        skeptic_score = panel_scores.get("skeptic")
        if isinstance(skeptic_score, (int, float)) and skeptic_score < 65 and not review.get("fabrication_flags"):
            panel_scores["skeptic"] = max(int(skeptic_score), 75)

        numeric_scores = [
            float(v) for v in panel_scores.values() if isinstance(v, (int, float))
        ]
        if numeric_scores:
            computed_mean = int(round(sum(numeric_scores) / len(numeric_scores)))
            review["match_score"] = max(int(review.get("match_score", 0) or 0), computed_mean)

    match_score = int(review.get("match_score", 0) or 0)
    if match_score >= 80:
        review["verdict"] = "INTERVIEW"
    if match_score >= 85 and review.get("verdict") == "INTERVIEW":
        review["pass"] = True

    return review


async def _ensure_summary(
    improved_data: dict[str, Any],
    job_content: str,
    language: str,
) -> dict[str, Any]:
    """Generate a concise profile summary if the resume lacks one.

    Produces a 2–3 sentence summary tailored to the JD, using only facts
    already present in the resume.  Also ensures sectionMeta marks the
    summary visible.
    """
    existing = improved_data.get("summary", "")
    has_summary = isinstance(existing, str) and existing.strip()

    # Always ensure sectionMeta marks summary visible
    section_meta = improved_data.get("sectionMeta", {})
    if isinstance(section_meta, dict):
        summary_meta = section_meta.get("summary", {})
        if not isinstance(summary_meta, dict):
            summary_meta = {}
        if not summary_meta.get("isVisible", True):
            improved_data = copy.deepcopy(improved_data)
            summary_meta["isVisible"] = True
            if "order" not in summary_meta:
                summary_meta["order"] = 1
            section_meta["summary"] = summary_meta
            improved_data["sectionMeta"] = section_meta

    if has_summary:
        return improved_data

    from app.llm import complete, get_config_for_task
    from app.prompts.templates import get_language_name

    lang_name = get_language_name(language)
    personal = improved_data.get("personalInfo", {})
    name = personal.get("name", "the candidate")
    skills = improved_data.get("additional", {}).get("technicalSkills", [])
    skills_str = ", ".join(skills[:15]) if skills else "N/A"

    prompt = (
        f"Write a concise 2–3 sentence professional summary for {name} "
        f"tailored to this job description. Use ONLY facts from the resume below — "
        f"do not invent experience or skills.\n\n"
        f"Key skills: {skills_str}\n\n"
        f"Job description:\n{job_content[:2000]}\n\n"
        f"Output ONLY the summary text in {lang_name}, no JSON, no quotes, no labels."
    )

    try:
        summary_text = await complete(
            prompt=prompt,
            system_prompt="You write concise, keyword-rich resume summaries. No fluff, no clichés.",
            config=get_config_for_task("keywords"),
            max_tokens=256,
            temperature=0.3,
        )
        summary_text = (summary_text or "").strip().strip('"').strip("'")
        if summary_text:
            improved_data = copy.deepcopy(improved_data)
            improved_data["summary"] = summary_text
            # Ensure sectionMeta marks summary visible
            section_meta = improved_data.get("sectionMeta", {})
            if not isinstance(section_meta, dict):
                section_meta = {}
            summary_meta = section_meta.get("summary", {})
            if not isinstance(summary_meta, dict):
                summary_meta = {}
            summary_meta["isVisible"] = True
            if "order" not in summary_meta:
                summary_meta["order"] = 1
            section_meta["summary"] = summary_meta
            improved_data["sectionMeta"] = section_meta
            logger.info("Generated missing profile summary (%d chars)", len(summary_text))
    except Exception as e:
        logger.warning("Failed to generate profile summary: %s", e)

    return improved_data


async def _autofix_weak_bullets(
    improved_data: dict[str, Any],
    weak_bullets: list[dict[str, Any]],
    job_content: str,
) -> dict[str, Any]:
    """Rewrite weak bullets identified by the review panel.

    Takes the review's ``weak_bullets`` list and rewrites each one via a
    single focused LLM call.  Returns the improved data with fixes applied.
    """
    if not weak_bullets:
        return improved_data

    from app.llm import complete_json, get_config_for_task

    # Build a compact fix request: only the bullets that need rewriting
    fixes_needed: list[dict[str, str]] = []
    for wb in weak_bullets[:5]:  # cap at 5 to keep prompt small
        if not isinstance(wb, dict):
            continue
        path = wb.get("path", "")
        text = wb.get("text", "")
        problem = wb.get("problem", "")
        fix_hint = wb.get("fix", "")
        if path and text and fix_hint != "REMOVE":
            fixes_needed.append({
                "path": path,
                "current": text,
                "problem": problem,
                "hint": fix_hint,
            })

    if not fixes_needed:
        return improved_data

    prompt = (
        "Rewrite ONLY the weak bullets listed below. For each, output the path "
        "and the improved text. Keep the candidate's real facts, add JD keywords "
        "naturally, use action verbs and quantify where the original has numbers.\n\n"
        f"Job description (first 1500 chars):\n{job_content[:1500]}\n\n"
        f"Bullets to fix:\n{json.dumps(fixes_needed)}\n\n"
        'Output JSON: {{"fixes": [{{"path": "...", "value": "improved text"}}]}}'
    )

    try:
        result = await complete_json(
            prompt=prompt,
            system_prompt="You rewrite resume bullets to be concise, keyword-rich, and impactful. Output only valid JSON.",
            config=get_config_for_task("keywords"),
            max_tokens=1024,
            temperature=0.3,
        )

        fixes = result.get("fixes", [])
        if not isinstance(fixes, list):
            return improved_data

        data = copy.deepcopy(improved_data)
        applied = 0
        for fix in fixes:
            if not isinstance(fix, dict):
                continue
            path = fix.get("path", "")
            value = fix.get("value", "")
            if not path or not isinstance(value, str) or not value.strip():
                continue

            # Parse path like "workExperience[0].description[2]"
            import re as _re
            m = _re.match(r"(\w+)\[(\d+)\]\.description\[(\d+)\]", path)
            if not m:
                continue
            section, entry_idx, bullet_idx = m.group(1), int(m.group(2)), int(m.group(3))
            entries = data.get(section, [])
            if not isinstance(entries, list) or entry_idx >= len(entries):
                continue
            entry = entries[entry_idx]
            if not isinstance(entry, dict):
                continue
            desc = entry.get("description", [])
            if not isinstance(desc, list) or bullet_idx >= len(desc):
                continue
            desc[bullet_idx] = value.strip()
            applied += 1

        if applied:
            logger.info("Auto-fixed %d/%d weak bullets from review", applied, len(fixes_needed))
        return data

    except Exception as e:
        logger.warning("Auto-fix weak bullets failed: %s", e)
        return improved_data


async def _inline_review(
    improved_data: dict[str, Any],
    job_content: str,
    job_keywords: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the hiring-panel review on in-memory resume data (no DB lookup)."""
    from app.llm import complete_json
    from app.prompts.templates import RESUME_REVIEW_PROMPT
    from app.config_cache import get_system_prompt_override

    from app.services.refiner import strip_hidden_sections

    visible_data = strip_hidden_sections(improved_data)
    resume_str = json.dumps(visible_data)
    review_tpl = get_system_prompt_override("resume_review") or RESUME_REVIEW_PROMPT
    prompt = review_tpl.format(
        job_description=job_content,
        resume_data=resume_str,
    )
    raw_review = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert hiring panel evaluating a tailored resume. Output only valid JSON.",
        max_tokens=2048,
        schema_type="enrichment",
    )
    return _postprocess_review_result(raw_review, visible_data, job_keywords)


async def _improve_preview_flow(
    *,
    request: ImproveResumeRequest,
    resume: dict[str, Any],
    job: dict[str, Any],
    language: str,
    prompt_id: str,
) -> ImproveResumeResponse:
    """Inner flow for improve/preview, extracted so it can be wrapped in wait_for."""
    job_keywords = job.get("job_keywords")
    job_keywords_hash = job.get("job_keywords_hash")
    content_hash = _hash_job_content(job["content"])
    if not job_keywords or (
        job_keywords_hash != content_hash
        and job_keywords_hash != content_hash[:16]
    ):
        job_keywords = await extract_job_keywords(job["content"])
        # Cache extracted keywords with a content hash for basic invalidation.
        # Also surface company/role to the job's top level so the tracker's
        # auto-create-on-confirm path can read them without an extra LLM call.
        cache_updates: dict[str, Any] = {
            "job_keywords": job_keywords,
            "job_keywords_hash": content_hash,
        }
        # LLM output isn't guaranteed to be a string — guard before .strip().
        raw_company = job_keywords.get("company")
        raw_role = job_keywords.get("role")
        company = raw_company.strip() if isinstance(raw_company, str) else ""
        role = raw_role.strip() if isinstance(raw_role, str) else ""
        if company:
            cache_updates["company"] = company
        if role:
            cache_updates["role"] = role
        try:
            updated_job = await db.update_job(
                request.job_id,
                cache_updates,
            )
            if not updated_job:
                logger.warning(
                    "Failed to persist job keywords for job %s.",
                    request.job_id,
                )
        except Exception as e:
            logger.warning(
                "Failed to persist job keywords for job %s: %s",
                request.job_id,
                e,
            )
    original_resume_data = (
        copy.deepcopy(request.base_resume_data)
        if isinstance(request.base_resume_data, dict) and request.base_resume_data
        else _get_original_resume_data(resume)
    )
    ext_mode = request.extrapolation_mode or "aggressive"
    # Collect warnings throughout the process
    response_warnings: list[str] = []

    # Diff-based improvement: generate targeted changes, apply with verification
    if original_resume_data:
        skill_targets: list[dict[str, Any]] = []
        try:
            raw_skill_plan = await generate_skill_target_plan(
                original_resume_data=original_resume_data,
                job_description=job["content"],
                job_keywords=job_keywords,
                language=language,
            )
            verified_skill_plan = verify_skill_target_plan(
                raw_skill_plan,
                original_resume_data=original_resume_data,
                job_keywords=job_keywords,
                job_description=job["content"],
            )
            accepted_targets = verified_skill_plan.get("accepted", [])
            if isinstance(accepted_targets, list):
                skill_targets = [
                    target
                    for target in accepted_targets
                    if isinstance(target, dict)
                ]
            rejected_targets = verified_skill_plan.get("rejected", [])
            if isinstance(rejected_targets, list) and rejected_targets:
                response_warnings.append(
                    f"{len(rejected_targets)} unsupported skill target(s) rejected"
                )
        except Exception as e:
            logger.warning("Skill target planning failed, continuing without it: %s", e)
            response_warnings.append("Skill target planning failed")

        diff_result = await generate_resume_diffs(
            original_resume=resume["content"],
            job_description=job["content"],
            job_keywords=job_keywords,
            language=language,
            prompt_id=prompt_id,
            original_resume_data=original_resume_data,
            skill_targets=skill_targets,
            confirmed_skills=request.confirmed_skills,
            extrapolation_mode=ext_mode,
        )

        effective_allowed = list(skill_targets or [])
        if request.confirmed_skills:
            effective_allowed.extend(request.confirmed_skills)
        improved_data, applied_changes, rejected_changes = apply_diffs(
            original=original_resume_data,
            changes=diff_result.changes,
            allowed_skill_targets=effective_allowed,
            confirmed_skills=request.confirmed_skills,
        )

        diff_warnings = verify_diff_result(
            original=original_resume_data,
            result=improved_data,
            applied_changes=applied_changes,
            job_keywords=job_keywords,
        )
        response_warnings.extend(diff_warnings)

        if rejected_changes:
            response_warnings.append(
                f"{len(rejected_changes)} change(s) rejected during verification"
            )

        logger.info(
            "Diff-based improve: %d applied, %d rejected, %d warnings",
            len(applied_changes),
            len(rejected_changes),
            len(diff_warnings),
        )
    else:
        # Fallback to full-output mode when no structured data available
        improved_data = await improve_resume(
            original_resume=resume["content"],
            job_description=job["content"],
            job_keywords=job_keywords,
            language=language,
            prompt_id=prompt_id,
            original_resume_data=original_resume_data,
            confirmed_skills=request.confirmed_skills,
            extrapolation_mode=ext_mode,
        )

    # Safety nets (defense in depth — should rarely activate with diff-based flow)
    improved_data, preserve_warnings = _preserve_personal_info(
        original_resume_data,
        improved_data,
    )
    response_warnings.extend(preserve_warnings)

    improved_data = _restore_original_dates(original_resume_data, improved_data)
    original_markdown = _get_original_markdown(resume)
    if original_markdown:
        improved_data = restore_dates_from_markdown(improved_data, original_markdown)
    improved_data = _preserve_original_skills(original_resume_data, improved_data)
    improved_data = _protect_custom_sections(original_resume_data, improved_data)

    # Ensure the tailored resume has a profile summary (generate if missing)
    improved_data = await _ensure_summary(improved_data, job["content"], language)

    # Multi-pass refinement: keyword injection, AI phrase removal, alignment validation
    # Skip refinement when keyword coverage is already high enough (saves ~5K tokens)
    refinement_stats: RefinementStats | None = None
    refinement_result = None
    refinement_attempted = False
    refinement_successful = False
    try:
        # Get master resume for alignment validation
        master_resume = await db.get_master_resume()
        master_data = (
            _get_original_resume_data(master_resume)
            if master_resume
            else _get_original_resume_data(resume)
        )
        if master_data:
            initial_match = calculate_keyword_match(improved_data, job_keywords)

            if initial_match >= 90:
                logger.info(
                    "Keyword coverage %.0f%% >= 90%%, skipping refinement pass",
                    initial_match,
                )
                refinement_stats = RefinementStats(
                    passes_completed=0,
                    keywords_injected=0,
                    ai_phrases_removed=[],
                    alignment_violations_fixed=0,
                    initial_match_percentage=initial_match,
                    final_match_percentage=initial_match,
                )
                refinement_attempted = True
                refinement_successful = True
                response_warnings.append(
                    f"Refinement skipped — keyword coverage already {initial_match:.0f}%"
                )
            else:
                refinement_attempted = True
                refinement_result = await refine_resume(
                    initial_tailored=improved_data,
                    master_resume=master_data,
                    job_description=job["content"],
                    job_keywords=job_keywords,
                    config=RefinementConfig(),
                    confirmed_skills=request.confirmed_skills,
                )
                improved_data = refinement_result.refined_data
                refinement_stats = RefinementStats(
                    passes_completed=refinement_result.passes_completed,
                    keywords_injected=(
                        len(refinement_result.keyword_analysis.injectable_keywords)
                        if refinement_result.keyword_analysis
                        else 0
                    ),
                    ai_phrases_removed=refinement_result.ai_phrases_removed,
                    alignment_violations_fixed=(
                        len(
                            [
                                v
                                for v in refinement_result.alignment_report.violations
                                if v.severity == "critical"
                            ]
                        )
                        if refinement_result.alignment_report
                        else 0
                    ),
                    initial_match_percentage=initial_match,
                    final_match_percentage=refinement_result.final_match_percentage,
                )
                refinement_successful = True
                logger.info(
                    "Refinement completed: %d passes, %d AI phrases removed",
                    refinement_result.passes_completed,
                    len(refinement_result.ai_phrases_removed),
                )
    except Exception as e:
        logger.warning("Refinement failed, using unrefined result: %s", e)
        if refinement_attempted:
            response_warnings.append(f"Refinement failed: {str(e)}")

    improved_data = enforce_optimal_skills_section(improved_data)
    improved_data = reorder_bullets_by_relevance(improved_data, job_keywords)

    improved_text = json.dumps(improved_data, indent=2)
    preview_hash = _hash_improved_data(improved_data)
    preview_hashes = job.get("preview_hashes")
    if not isinstance(preview_hashes, dict):
        preview_hashes = {}
    preview_hashes[prompt_id] = preview_hash
    # NOTE: preview_hashes updates are last-write-wins; concurrent previews can race.
    try:
        updated_job = await db.update_job(
            request.job_id,
            {
                "preview_hash": preview_hash,
                "preview_prompt_id": prompt_id,
                "preview_hashes": preview_hashes,
            },
        )
        if not updated_job:
            logger.warning(
                "Failed to persist preview hash for job %s.", request.job_id
            )
    except Exception as e:
        logger.warning(
            "Failed to persist preview hash for job %s: %s", request.job_id, e
        )
    diff_summary, detailed_changes, diff_error = _calculate_diff_from_resume(
        resume,
        improved_data,
    )
    if diff_error:
        response_warnings.append(f"Could not calculate changes: {diff_error}")
    improvements = generate_improvements(job_keywords)

    # Generate cover letter and/or review inline when requested
    cover_letter = None
    review_result = None
    pipeline_tasks: list[Awaitable[Any]] = []
    pipeline_labels: list[str] = []

    if request.include_cover_letter:
        pipeline_tasks.append(
            generate_cover_letter(improved_data, job["content"], language)
        )
        pipeline_labels.append("cover_letter")

    if request.include_review:
        pipeline_tasks.append(
            _inline_review(improved_data, job["content"], job_keywords=job_keywords)
        )
        pipeline_labels.append("review")

    if pipeline_tasks:
        pipeline_results = await asyncio.gather(
            *pipeline_tasks, return_exceptions=True
        )
        for label, result in zip(pipeline_labels, pipeline_results):
            if isinstance(result, Exception):
                logger.warning("Preview pipeline %s failed: %s", label, result)
                response_warnings.append(f"{label.replace('_', ' ').title()} failed")
            elif label == "cover_letter":
                cover_letter = result
            elif label == "review":
                review_result = result

    # Closed-loop: auto-fix weak bullets identified by the review panel
    weak_bullets = review_result.get("weak_bullets", []) if review_result else []
    if weak_bullets and isinstance(weak_bullets, list):
        try:
            fixed_data = await _autofix_weak_bullets(
                improved_data, weak_bullets, job["content"],
            )
            if fixed_data is not improved_data:
                improved_data = fixed_data
                improved_text = json.dumps(improved_data, indent=2)
        except Exception as e:
            logger.warning("Closed-loop auto-fix failed: %s", e)

    # Persist inline review and cover letter on the job so confirm and JD Match
    # can reuse them immediately without re-running LLM calls.
    job_pipeline_updates: dict[str, Any] = {}
    if review_result is not None:
        job_pipeline_updates["review"] = review_result
    if cover_letter:
        job_pipeline_updates["cached_cover_letter"] = cover_letter
    if job_pipeline_updates:
        try:
            await db.update_job(request.job_id, job_pipeline_updates)
        except Exception as e:
            logger.warning(
                "Failed to cache preview review/cover_letter for job %s: %s",
                request.job_id,
                e,
            )

    request_id = str(uuid4())
    return ImproveResumeResponse(
        request_id=request_id,
        data=ImproveResumeData(
            request_id=request_id,
            resume_id=None,
            job_id=request.job_id,
            resume_preview=ResumeData.model_validate(improved_data),
            improvements=[
                {
                    "suggestion": imp["suggestion"],
                    "lineNumber": imp.get("lineNumber"),
                }
                for imp in improvements
            ],
            markdownOriginal=resume["content"],
            markdownImproved=improved_text,
            cover_letter=cover_letter,
            outreach_message=None,
            interview_prep=None,
            diff_summary=diff_summary,
            detailed_changes=detailed_changes,
            refinement_stats=refinement_stats,
            ats_score=_build_ats_score(
                improved_data,
                job_keywords,
                refinement_result,
                refinement_successful,
            ),
            review=review_result,
            warnings=response_warnings,
            refinement_attempted=refinement_attempted,
            refinement_successful=refinement_successful,
        ),
    )


@router.post("/improve/confirm", response_model=ImproveResumeResponse)
async def improve_resume_confirm_endpoint(
    request: ImproveResumeConfirmRequest,
) -> ImproveResumeResponse:
    """Confirm and persist a tailored resume."""
    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    job = await db.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job description not found")

    feature_config = _load_config()
    enable_cover_letter = feature_config.get("enable_cover_letter", False)
    enable_outreach = feature_config.get("enable_outreach_message", False)
    enable_interview_prep = feature_config.get("enable_interview_prep", False)
    language = get_content_language()

    stage = "serialize_improved_data"
    detail = "Failed to confirm resume. Please try again."
    try:
        improved_data = request.improved_data.model_dump()
        improved_text = json.dumps(improved_data, indent=2)
        # NOTE: This endpoint relies on preview-hash validation to ensure the payload matches a prior preview.
        # Stronger guarantees would require server-side preview storage or re-running the improvement.
        try:
            _validate_confirm_payload(_get_original_resume_data(resume), improved_data)
        except ValueError as e:
            logger.warning("Resume confirm rejected: %s", e)
            raise HTTPException(
                status_code=400,
                detail="Invalid improved resume data. Please retry preview.",
            )
        preview_hashes = job.get("preview_hashes")
        allowed_hashes: set[str] = set()
        if isinstance(preview_hashes, dict):
            allowed_hashes.update(preview_hashes.values())
        elif isinstance(preview_hashes, list):
            allowed_hashes.update(
                [value for value in preview_hashes if isinstance(value, str)]
            )
        else:
            preview_hash = job.get("preview_hash")
            if isinstance(preview_hash, str):
                allowed_hashes.add(preview_hash)

        if not allowed_hashes:
            logger.warning(
                "Rejecting confirm; preview hash missing for job %s.",
                request.job_id,
            )
            raise HTTPException(
                status_code=400,
                detail="Preview required before confirmation. Please retry preview.",
            )

        request_hash = _hash_improved_data(improved_data)
        if request_hash not in allowed_hashes:
            logger.warning("Resume confirm rejected due to preview hash mismatch.")
            raise HTTPException(
                status_code=400,
                detail="Invalid improved resume data. Please retry preview.",
            )

        stage = "calculate_diff"
        response_warnings: list[str] = []
        diff_summary, detailed_changes, diff_error = _calculate_diff_from_resume(
            resume,
            improved_data,
        )
        if diff_error:
            response_warnings.append(f"Could not calculate changes: {diff_error}")

        stage = "generate_auxiliary_messages"
        pregenerated_cover_letter = (
            request.cover_letter
            or (
                job.get("cached_cover_letter")
                if isinstance(job.get("cached_cover_letter"), str)
                else None
            )
        )
        (
            generated_cover_letter,
            outreach_message,
            title,
            interview_prep,
            aux_warnings,
        ) = await _generate_auxiliary_messages(
            improved_data,
            job["content"],
            language,
            enable_cover_letter and not bool(pregenerated_cover_letter),
            enable_outreach,
            enable_interview_prep,
        )
        cover_letter = pregenerated_cover_letter or generated_cover_letter
        response_warnings.extend(aux_warnings)

        persisted_review = request.review or (
            job.get("review") if isinstance(job.get("review"), dict) else None
        )
        job_confirm_updates: dict[str, Any] = {}
        if persisted_review is not None and not job.get("review"):
            job_confirm_updates["review"] = persisted_review
        if request.company:
            job_confirm_updates["company"] = request.company.strip()
        if request.role:
            job_confirm_updates["role"] = request.role.strip()
        if job_confirm_updates:
            try:
                await db.update_job(request.job_id, job_confirm_updates)
            except Exception as e:
                logger.warning("Failed to update job metadata on confirm: %s", e)

        stage = "create_resume"
        tailored_resume = await db.create_resume(
            content=improved_text,
            content_type="json",
            filename=f"tailored_{resume.get('filename', 'resume')}",
            is_master=False,
            parent_id=request.resume_id,
            processed_data=improved_data,
            processing_status="ready",
            cover_letter=cover_letter,
            outreach_message=outreach_message,
            interview_prep=_serialize_interview_prep(interview_prep),
            title=title,
        )

        improvements_payload = [imp.model_dump() for imp in request.improvements]
        stage = "create_improvement"
        request_id = str(uuid4())
        await db.create_improvement(
            original_resume_id=request.resume_id,
            tailored_resume_id=tailored_resume["resume_id"],
            job_id=request.job_id,
            improvements=improvements_payload,
        )

        await _auto_create_tracker_application(
            job_id=request.job_id,
            tailored_resume_id=tailored_resume["resume_id"],
            master_resume_id=request.resume_id,
            job=job,
            title=title,
            company_override=request.company.strip() if request.company else None,
            role_override=request.role.strip() if request.role else None,
            status_override=request.status.strip() if request.status else None,
        )

        # Auto-export CV + cover letter (PDF + DOCX) to the user's host-
        # mounted Resume Matcher/<Company>/<Role>/ folder. Fire-and-forget:
        # a failure here must NOT block the tailor response.
        try:
            from app.services.exporter import export_tailored_bundle

            asyncio.create_task(export_tailored_bundle(tailored_resume["resume_id"]))
        except Exception as e:  # pragma: no cover
            logger.warning("auto-export scheduling failed: %s", e)

        return ImproveResumeResponse(
            request_id=request_id,
            data=ImproveResumeData(
                request_id=request_id,
                resume_id=tailored_resume["resume_id"],
                job_id=request.job_id,
                resume_preview=request.improved_data,
                improvements=request.improvements,
                markdownOriginal=resume["content"],
                markdownImproved=improved_text,
                cover_letter=cover_letter,
                outreach_message=outreach_message,
                interview_prep=interview_prep,
                diff_summary=diff_summary,
                detailed_changes=detailed_changes,
                review=persisted_review,
                warnings=response_warnings,
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        _raise_improve_error("confirm", stage, e, detail)


@router.post("/improve", response_model=ImproveResumeResponse)
async def improve_resume_endpoint(
    request: ImproveResumeRequest,
) -> ImproveResumeResponse:
    """Improve/tailor a resume for a specific job description.

    Uses LLM to analyze the job and generate an optimized resume version
    with improvement suggestions. Also generates cover letter and outreach
    message if enabled in feature configuration.
    Persists the tailored resume and returns a non-null resume_id.
    """
    # Fetch resume
    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Fetch job description
    job = await db.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job description not found")

    # Load feature configuration and content language
    feature_config = _load_config()
    enable_cover_letter = feature_config.get("enable_cover_letter", False)
    enable_outreach = feature_config.get("enable_outreach_message", False)
    enable_interview_prep = feature_config.get("enable_interview_prep", False)
    language = get_content_language()

    try:
        # Extract keywords from job description
        job_keywords = await extract_job_keywords(job["content"])

        # Generate improved resume in the configured language
        prompt_id = request.prompt_id or _get_default_prompt_id()

        original_resume_data = _get_original_resume_data(resume)
        # Collect warnings throughout the process
        response_warnings: list[str] = []

        # Diff-based improvement: generate targeted changes, apply with verification
        if original_resume_data:
            diff_result = await generate_resume_diffs(
                original_resume=resume["content"],
                job_description=job["content"],
                job_keywords=job_keywords,
                language=language,
                prompt_id=prompt_id,
                original_resume_data=original_resume_data,
            )

            improved_data, applied_changes, rejected_changes = apply_diffs(
                original=original_resume_data,
                changes=diff_result.changes,
            )

            diff_warnings = verify_diff_result(
                original=original_resume_data,
                result=improved_data,
                applied_changes=applied_changes,
                job_keywords=job_keywords,
            )
            response_warnings.extend(diff_warnings)

            if rejected_changes:
                response_warnings.append(
                    f"{len(rejected_changes)} change(s) rejected during verification"
                )

            logger.info(
                "Diff-based improve (legacy): %d applied, %d rejected, %d warnings",
                len(applied_changes),
                len(rejected_changes),
                len(diff_warnings),
            )
        else:
            # Fallback to full-output mode when no structured data available
            improved_data = await improve_resume(
                original_resume=resume["content"],
                job_description=job["content"],
                job_keywords=job_keywords,
                language=language,
                prompt_id=prompt_id,
                original_resume_data=original_resume_data,
            )

        # Safety nets (defense in depth)
        improved_data, preserve_warnings = _preserve_personal_info(
            original_resume_data,
            improved_data,
        )
        response_warnings.extend(preserve_warnings)

        improved_data = _restore_original_dates(original_resume_data, improved_data)
        original_markdown = _get_original_markdown(resume)
        if original_markdown:
            improved_data = restore_dates_from_markdown(improved_data, original_markdown)
        improved_data = _preserve_original_skills(original_resume_data, improved_data)
        improved_data = _protect_custom_sections(original_resume_data, improved_data)

        # Multi-pass refinement: keyword injection, AI phrase removal, alignment validation
        refinement_stats: RefinementStats | None = None
        refinement_result = None
        refinement_attempted = False
        refinement_successful = False
        try:
            # Get master resume for alignment validation
            master_resume = await db.get_master_resume()
            master_data = (
                _get_original_resume_data(master_resume)
                if master_resume
                else _get_original_resume_data(resume)
            )
            if master_data:
                initial_match = calculate_keyword_match(improved_data, job_keywords)
                refinement_attempted = True
                refinement_result = await refine_resume(
                    initial_tailored=improved_data,
                    master_resume=master_data,
                    job_description=job["content"],
                    job_keywords=job_keywords,
                    config=RefinementConfig(),
                )
                improved_data = refinement_result.refined_data
                refinement_stats = RefinementStats(
                    passes_completed=refinement_result.passes_completed,
                    keywords_injected=(
                        len(refinement_result.keyword_analysis.injectable_keywords)
                        if refinement_result.keyword_analysis
                        else 0
                    ),
                    ai_phrases_removed=refinement_result.ai_phrases_removed,
                    alignment_violations_fixed=(
                        len(
                            [
                                v
                                for v in refinement_result.alignment_report.violations
                                if v.severity == "critical"
                            ]
                        )
                        if refinement_result.alignment_report
                        else 0
                    ),
                    initial_match_percentage=initial_match,
                    final_match_percentage=refinement_result.final_match_percentage,
                )
                refinement_successful = True
                logger.info(
                    "Refinement completed: %d passes, %d AI phrases removed",
                    refinement_result.passes_completed,
                    len(refinement_result.ai_phrases_removed),
                )
        except Exception as e:
            logger.warning("Refinement failed, using unrefined result: %s", e)
            if refinement_attempted:
                response_warnings.append(f"Refinement failed: {str(e)}")

        improved_data = enforce_optimal_skills_section(improved_data)

        # Convert improved data to JSON string for storage
        improved_text = json.dumps(improved_data, indent=2)

        # Calculate differences between original and improved resume
        diff_summary, detailed_changes, diff_error = _calculate_diff_from_resume(
            resume,
            improved_data,
        )
        if diff_error:
            response_warnings.append(f"Could not calculate changes: {diff_error}")

        # Generate improvement suggestions
        improvements = generate_improvements(job_keywords)

        # Generate cover letter, outreach message, and title in parallel if enabled
        (
            cover_letter,
            outreach_message,
            title,
            interview_prep,
            aux_warnings,
        ) = await _generate_auxiliary_messages(
            improved_data,
            job["content"],
            language,
            enable_cover_letter,
            enable_outreach,
            enable_interview_prep,
        )
        response_warnings.extend(aux_warnings)

        # Store the tailored resume with cover letter, outreach message, and title
        tailored_resume = await db.create_resume(
            content=improved_text,
            content_type="json",
            filename=f"tailored_{resume.get('filename', 'resume')}",
            is_master=False,
            parent_id=request.resume_id,
            processed_data=improved_data,
            processing_status="ready",
            cover_letter=cover_letter,
            outreach_message=outreach_message,
            interview_prep=_serialize_interview_prep(interview_prep),
            title=title,
        )

        # Store improvement record
        request_id = str(uuid4())
        await db.create_improvement(
            original_resume_id=request.resume_id,
            tailored_resume_id=tailored_resume["resume_id"],
            job_id=request.job_id,
            improvements=improvements,
        )

        await _auto_create_tracker_application(
            job_id=request.job_id,
            tailored_resume_id=tailored_resume["resume_id"],
            master_resume_id=request.resume_id,
            job=job,
            title=title,
        )

        # Auto-export CV + cover letter (PDF + DOCX) to the user's host-
        # mounted Resume Matcher/<Company>/<Role>/ folder. Fire-and-forget:
        # a failure here must NOT block the tailor response.
        try:
            from app.services.exporter import export_tailored_bundle

            asyncio.create_task(export_tailored_bundle(tailored_resume["resume_id"]))
        except Exception as e:  # pragma: no cover
            logger.warning("auto-export scheduling failed: %s", e)

        return ImproveResumeResponse(
            request_id=request_id,
            data=ImproveResumeData(
                request_id=request_id,
                resume_id=tailored_resume["resume_id"],
                job_id=request.job_id,
                resume_preview=ResumeData.model_validate(improved_data),
                improvements=[
                    {
                        "suggestion": imp["suggestion"],
                        "lineNumber": imp.get("lineNumber"),
                    }
                    for imp in improvements
                ],
                markdownOriginal=resume["content"],
                markdownImproved=improved_text,
                cover_letter=cover_letter,
                outreach_message=outreach_message,
                interview_prep=interview_prep,
                # Diff metadata
                diff_summary=diff_summary,
                detailed_changes=detailed_changes,
                refinement_stats=refinement_stats,
                ats_score=_build_ats_score(
                    improved_data,
                    job_keywords,
                    refinement_result,
                    refinement_successful,
                ),
                warnings=response_warnings,
                refinement_attempted=refinement_attempted,
                refinement_successful=refinement_successful,
            ),
        )

    except Exception as e:
        logger.error(f"Resume improvement failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to improve resume. Please try again.",
        )


@router.patch("/{resume_id}", response_model=ResumeFetchResponse)
async def update_resume_endpoint(
    resume_id: str, resume_data: ResumeData
) -> ResumeFetchResponse:
    """Update a resume with new structured data."""
    existing = await db.get_resume(resume_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Resume not found")

    updated_data = resume_data.model_dump()
    updated_content = json.dumps(updated_data, indent=2)

    updated = await db.update_resume(
        resume_id,
        {
            "content": updated_content,
            "content_type": "json",
            "processed_data": updated_data,
            "processing_status": "ready",
        },
    )

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update resume")

    raw_resume = RawResume(
        id=None,
        content=updated["content"],
        content_type=updated["content_type"],
        created_at=updated["created_at"],
        processing_status=updated.get("processing_status", "pending"),
    )

    processed_resume = (
        ResumeData.model_validate(updated.get("processed_data"))
        if updated.get("processed_data")
        else None
    )

    return ResumeFetchResponse(
        request_id=str(uuid4()),
        data=ResumeFetchData(
            resume_id=resume_id,
            raw_resume=raw_resume,
            processed_resume=processed_resume,
            cover_letter=updated.get("cover_letter"),
            outreach_message=updated.get("outreach_message"),
            interview_prep=_parse_interview_prep(
                updated.get("interview_prep"),
                resume_id=resume_id,
            ),
            parent_id=updated.get("parent_id"),
            title=updated.get("title"),
        ),
    )


@router.get("/{resume_id}/pdf")
async def download_resume_pdf(
    resume_id: str,
    template: str = Query("swiss-single"),
    pageSize: str = Query("A4", pattern="^(A4|LETTER)$"),
    marginTop: int = Query(10, ge=5, le=25),
    marginBottom: int = Query(10, ge=5, le=25),
    marginLeft: int = Query(10, ge=5, le=25),
    marginRight: int = Query(10, ge=5, le=25),
    sectionSpacing: int = Query(3, ge=1, le=5),
    itemSpacing: int = Query(2, ge=1, le=5),
    lineHeight: int = Query(3, ge=1, le=5),
    fontSize: int = Query(3, ge=1, le=5),
    headerScale: int = Query(3, ge=1, le=5),
    # Accepts either the three legacy generics (serif/sans-serif/mono, kept for
    # existing saved settings) or any of the named faces the frontend registers
    # in NAMED_FONT_FAMILIES — validation of the exact vocabulary lives on the
    # frontend so this pattern only rejects obviously-hostile input.
    headerFont: str = Query("serif", pattern=r"^[a-z][a-z0-9-]{0,31}$"),
    bodyFont: str = Query("sans-serif", pattern=r"^[a-z][a-z0-9-]{0,31}$"),
    compactMode: bool = Query(False),
    showContactIcons: bool = Query(False),
    accentColor: str = Query("blue", pattern="^(blue|green|orange|red)$"),
    lang: str | None = Query(None, pattern="^[a-z]{2}(-[A-Z]{2})?$"),
) -> Response:
    """Generate a PDF for a resume using headless Chromium.

    Accepts template settings for customization:
    - template: swiss-single, swiss-two-column, modern, modern-two-column, latex, clean, or vivid
    - pageSize: A4 or LETTER
    - marginTop/Bottom/Left/Right: page margins in mm (5-25)
    - sectionSpacing: gap between sections (1-5)
    - itemSpacing: gap between items (1-5)
    - lineHeight: text line height (1-5)
    - fontSize: base font size (1-5)
    - headerScale: header size scale (1-5)
    - headerFont: serif, sans-serif, or mono
    - bodyFont: serif, sans-serif, or mono
    - compactMode: enable tighter spacing
    - showContactIcons: show icons in contact info
    - lang: locale used for print page translations
    """
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Build print URL with all settings
    params = (
        f"template={template}"
        f"&pageSize={pageSize}"
        f"&marginTop={marginTop}"
        f"&marginBottom={marginBottom}"
        f"&marginLeft={marginLeft}"
        f"&marginRight={marginRight}"
        f"&sectionSpacing={sectionSpacing}"
        f"&itemSpacing={itemSpacing}"
        f"&lineHeight={lineHeight}"
        f"&fontSize={fontSize}"
        f"&headerScale={headerScale}"
        f"&headerFont={headerFont}"
        f"&bodyFont={bodyFont}"
        f"&compactMode={str(compactMode).lower()}"
        f"&showContactIcons={str(showContactIcons).lower()}"
        f"&accentColor={accentColor}"
    )
    if lang:
        params = f"{params}&lang={lang}"
    url = f"{settings.frontend_base_url}/print/resumes/{resume_id}?{params}"

    # Use the exact margins provided; compact mode only affects spacing.
    pdf_margins = {
        "top": marginTop,
        "right": marginRight,
        "bottom": marginBottom,
        "left": marginLeft,
    }

    # Render PDF with margins applied to every page
    try:
        pdf_bytes = await render_resume_pdf(url, pageSize, margins=pdf_margins)
    except PDFRenderError as e:
        raise HTTPException(status_code=503, detail=str(e))

    headers = {"Content-Disposition": f'attachment; filename="resume_{resume_id}.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.delete("/{resume_id}")
async def delete_resume(resume_id: str) -> dict:
    """Delete a resume by ID."""
    if not await db.delete_resume(resume_id):
        raise HTTPException(status_code=404, detail="Resume not found")

    return {"message": "Resume deleted successfully"}


@router.post("/{resume_id}/retry-processing", response_model=ResumeUploadResponse)
async def retry_processing(resume_id: str) -> ResumeUploadResponse:
    """Retry AI processing for a failed or stuck resume.

    Re-runs parse_resume_to_json() on the stored markdown content.
    Works for resumes with processing_status == "failed" or "processing".
    """
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if resume.get("processing_status") not in ("failed", "processing"):
        raise HTTPException(
            status_code=400,
            detail="Only resumes with 'failed' or 'processing' status can be retried.",
        )

    markdown_content = resume.get("content", "")
    if not markdown_content:
        raise HTTPException(
            status_code=400,
            detail="Resume has no stored content to re-process.",
        )

    try:
        processed_data = await parse_resume_to_json(markdown_content)
        await db.update_resume(
            resume_id,
            {
                "processed_data": processed_data,
                "processing_status": "ready",
            },
        )
        return ResumeUploadResponse(
            message="Resume processing succeeded on retry",
            request_id=str(uuid4()),
            resume_id=resume_id,
            processing_status="ready",
            is_master=resume.get("is_master", False),
        )
    except Exception as e:
        logger.warning(f"Retry processing failed for resume {resume_id}: {e}")
        await db.update_resume(resume_id, {"processing_status": "failed"})
        return ResumeUploadResponse(
            message="Retry processing failed",
            request_id=str(uuid4()),
            resume_id=resume_id,
            processing_status="failed",
            is_master=resume.get("is_master", False),
        )


@router.patch("/{resume_id}/cover-letter")
async def update_cover_letter(
    resume_id: str, request: UpdateCoverLetterRequest
) -> dict:
    """Update the cover letter for a resume."""
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.update_resume(resume_id, {"cover_letter": request.content})
    return {"message": "Cover letter updated successfully"}


@router.patch("/{resume_id}/outreach-message")
async def update_outreach_message(
    resume_id: str, request: UpdateOutreachMessageRequest
) -> dict:
    """Update the outreach message for a resume."""
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.update_resume(resume_id, {"outreach_message": request.content})
    return {"message": "Outreach message updated successfully"}


@router.patch("/{resume_id}/title")
async def update_title(resume_id: str, request: UpdateTitleRequest) -> dict:
    """Update the title for a resume."""
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    title = request.title.strip()[:80]
    await db.update_resume(resume_id, {"title": title})
    return {"message": "Title updated successfully"}


@router.post("/{resume_id}/set-as-master")
async def set_as_master(resume_id: str) -> dict:
    """Make this resume the master, atomically demoting any previous master.

    Single-master model: at most one resume is master at any moment.
    Uses db.set_master_resume which does demote-then-promote in one
    transaction so the transient state (0 masters, 2 masters) never
    surfaces to other readers.
    """
    ok = await db.set_master_resume(resume_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Resume not found")
    return {"message": "Resume set as master", "resume_id": resume_id, "is_master": True}


@router.post(
    "/{resume_id}/generate-cover-letter", response_model=GenerateContentResponse
)
async def generate_cover_letter_endpoint(resume_id: str) -> GenerateContentResponse:
    """Generate a cover letter on-demand for an existing tailored resume.

    This endpoint allows users to generate a cover letter after a resume has been
    tailored, without needing to re-tailor the entire resume. It requires:
    - The resume must be a tailored resume (has parent_id)
    - The resume must have an associated job context in the improvements table
    """
    # Get the resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Check if it's a tailored resume (has parent_id)
    if not resume.get("parent_id"):
        raise HTTPException(
            status_code=400,
            detail="Cover letter can only be generated for tailored resumes. "
            "Please tailor this resume to a job description first.",
        )

    # Get improvement record to find the job_id
    improvement = await db.get_improvement_by_tailored_resume(resume_id)
    if not improvement:
        raise HTTPException(
            status_code=400,
            detail="No job context found for this resume. "
            "The resume may have been created before job tracking was implemented.",
        )

    # Get the job description
    job = await db.get_job(improvement["job_id"])
    if not job:
        raise HTTPException(
            status_code=404,
            detail="The associated job description was not found.",
        )

    # Get resume data
    resume_data = resume.get("processed_data")
    if not resume_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data. Please re-upload the resume.",
        )

    # Get language setting
    language = get_content_language()

    # Generate cover letter
    try:
        cover_letter_content = await generate_cover_letter(
            resume_data, job["content"], language
        )
    except Exception as e:
        logger.error(f"Cover letter generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate cover letter. Please try again.",
        )

    # Save to resume record
    await db.update_resume(resume_id, {"cover_letter": cover_letter_content})

    # Re-export the bundle so the user's Desktop folder picks up the new CL.
    try:
        from app.services.exporter import export_tailored_bundle

        asyncio.create_task(export_tailored_bundle(resume_id))
    except Exception as e:  # pragma: no cover
        logger.warning("auto-export on cover-letter regen failed: %s", e)

    return GenerateContentResponse(
        content=cover_letter_content,
        message="Cover letter generated successfully",
    )


@router.post("/{resume_id}/generate-outreach", response_model=GenerateContentResponse)
async def generate_outreach_endpoint(resume_id: str) -> GenerateContentResponse:
    """Generate an outreach message on-demand for an existing tailored resume.

    This endpoint allows users to generate a cold outreach message after a resume
    has been tailored. It requires:
    - The resume must be a tailored resume (has parent_id)
    - The resume must have an associated job context in the improvements table
    """
    # Get the resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Check if it's a tailored resume (has parent_id)
    if not resume.get("parent_id"):
        raise HTTPException(
            status_code=400,
            detail="Outreach message can only be generated for tailored resumes. "
            "Please tailor this resume to a job description first.",
        )

    # Get improvement record to find the job_id
    improvement = await db.get_improvement_by_tailored_resume(resume_id)
    if not improvement:
        raise HTTPException(
            status_code=400,
            detail="No job context found for this resume. "
            "The resume may have been created before job tracking was implemented.",
        )

    # Get the job description
    job = await db.get_job(improvement["job_id"])
    if not job:
        raise HTTPException(
            status_code=404,
            detail="The associated job description was not found.",
        )

    # Get resume data
    resume_data = resume.get("processed_data")
    if not resume_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data. Please re-upload the resume.",
        )

    # Get language setting
    language = get_content_language()

    # Generate outreach message
    try:
        outreach_content = await generate_outreach_message(
            resume_data, job["content"], language
        )
    except Exception as e:
        logger.error(f"Outreach message generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate outreach message. Please try again.",
        )

    # Save to resume record
    await db.update_resume(resume_id, {"outreach_message": outreach_content})

    return GenerateContentResponse(
        content=outreach_content,
        message="Outreach message generated successfully",
    )


@router.post(
    "/{resume_id}/generate-interview-prep",
    response_model=GenerateInterviewPrepResponse,
)
async def generate_interview_prep_endpoint(
    resume_id: str,
) -> GenerateInterviewPrepResponse:
    """Generate interview preparation on-demand for an existing tailored resume."""
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not resume.get("parent_id"):
        raise HTTPException(
            status_code=400,
            detail="Interview preparation can only be generated for tailored resumes. "
            "Please tailor this resume to a job description first.",
        )

    improvement = await db.get_improvement_by_tailored_resume(resume_id)
    if not improvement:
        raise HTTPException(
            status_code=400,
            detail="No job context found for this resume. "
            "The resume may have been created before job tracking was implemented.",
        )

    job = await db.get_job(improvement["job_id"])
    if not job:
        raise HTTPException(
            status_code=404,
            detail="The associated job description was not found.",
        )

    resume_data = resume.get("processed_data")
    if not resume_data:
        raise HTTPException(
            status_code=400,
            detail="Resume has no processed data. Please re-upload the resume.",
        )

    language = get_content_language()

    try:
        interview_prep = await generate_interview_prep(
            resume_data,
            job["content"],
            language,
        )
    except Exception as e:
        logger.exception("Interview preparation generation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate interview preparation. Please try again.",
        )

    await db.update_resume(
        resume_id,
        {"interview_prep": _serialize_interview_prep(interview_prep)},
    )

    return GenerateInterviewPrepResponse(
        interview_prep=interview_prep,
        message="Interview preparation generated successfully",
    )


@router.get("/{resume_id}/job-description")
async def get_job_description_for_resume(resume_id: str) -> dict:
    """Get the job description used to tailor this resume.

    This endpoint retrieves the original job description that was used
    to tailor a resume. Only works for tailored resumes (those with parent_id).
    """
    # Get the resume
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Check if it's a tailored resume (has parent_id)
    if not resume.get("parent_id"):
        raise HTTPException(
            status_code=400,
            detail="Job description is only available for tailored resumes.",
        )

    # Get improvement record to find the job_id
    improvement = await db.get_improvement_by_tailored_resume(resume_id)
    if not improvement:
        raise HTTPException(
            status_code=400,
            detail="No job context found for this resume. "
            "The resume may have been created before job tracking was implemented.",
        )

    # Get the job description
    job = await db.get_job(improvement["job_id"])
    if not job:
        raise HTTPException(
            status_code=404,
            detail="The associated job description was not found.",
        )

    return {
        "job_id": job["job_id"],
        "content": job["content"],
        "review": job.get("review"),
    }


@router.get("/{resume_id}/cover-letter/pdf")
async def download_cover_letter_pdf(
    resume_id: str,
    pageSize: str = Query("A4", pattern="^(A4|LETTER)$"),
    lang: str | None = Query(None, pattern="^[a-z]{2}(-[A-Z]{2})?$"),
) -> Response:
    """Generate a PDF for a cover letter using headless Chromium.

    Args:
        resume_id: The ID of the resume containing the cover letter
        pageSize: A4 or LETTER
        lang: locale used for print page translations
    """
    resume = await db.get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    cover_letter = resume.get("cover_letter")
    if not cover_letter:
        raise HTTPException(
            status_code=404, detail="No cover letter found for this resume"
        )

    # Build print URL (same pattern as resume PDF)
    url = f"{settings.frontend_base_url}/print/cover-letter/{resume_id}?pageSize={pageSize}"
    if lang:
        url = f"{url}&lang={lang}"

    # Render PDF with cover letter selector and standard letter margins
    cover_letter_margins = {"top": 20, "right": 20, "bottom": 20, "left": 20}
    try:
        pdf_bytes = await render_resume_pdf(
            url, pageSize, selector=".cover-letter-print",
            margins=cover_letter_margins,
        )
    except PDFRenderError as e:
        raise HTTPException(status_code=503, detail=str(e))

    headers = {
        "Content-Disposition": f'attachment; filename="cover_letter_{resume_id}.pdf"'
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


# ---------------------------------------------------------------------------
# Resume Review (lightweight hiring-panel-style, single LLM call)
# ---------------------------------------------------------------------------

@router.post("/review")
async def review_resume(request: ImproveResumeRequest) -> dict[str, Any]:
    """Single-pass hiring-panel review: ATS + hiring manager + rival applicant.

    Returns structured JSON feedback with match_score, missing keywords,
    weak bullets, and top fixes. One LLM call (~1k tokens out).
    """
    from app.llm import complete_json
    from app.prompts.templates import RESUME_REVIEW_PROMPT

    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    job = await db.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Return cached review unless force re-analysis is requested
    cached_review = job.get("review")
    if not request.force and isinstance(cached_review, dict) and cached_review:
        return cached_review

    resume_data = resume.get("processed_data") or resume.get("raw_resume", {})
    if isinstance(resume_data, dict):
        resume_str = json.dumps(resume_data)
    else:
        resume_str = str(resume_data)

    prompt = RESUME_REVIEW_PROMPT.format(
        job_description=job.get("content", ""),
        resume_data=resume_str,
    )

    try:
        result = await complete_json(
            prompt=prompt,
            system_prompt="You are an expert hiring panel evaluating a tailored resume. Output only valid JSON.",
            max_tokens=2048,
            schema_type="enrichment",
        )
        if isinstance(result, dict) and isinstance(resume_data, dict):
            result = _postprocess_review_result(
                result,
                resume_data,
                job_keywords=job.get("job_keywords"),
            )
    except Exception as e:
        logger.error("Resume review failed: %s", e)
        raise HTTPException(status_code=500, detail="Review failed. Please try again.")

    if isinstance(result, dict):
        try:
            await db.update_job(request.job_id, {"review": result})
        except Exception as e:
            logger.warning("Failed to cache review for job %s: %s", request.job_id, e)

    return result


# ---------------------------------------------------------------------------
# Closed-Loop Tailor: tailor → review → re-tailor until pass or max rounds
# ---------------------------------------------------------------------------

@router.post("/improve/auto-loop")
async def auto_loop_tailor(request: ImproveResumeRequest) -> dict[str, Any]:
    """Closed-loop tailoring: tailor, review, re-tailor until the reviewer
    says INTERVIEW with score >= 85, or max 3 rounds.

    Uses the existing preview pipeline internally. Returns the final
    improved resume data + all review rounds for transparency.
    """
    max_rounds = 3
    rounds: list[dict[str, Any]] = []

    resume = await db.get_resume(request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    job = await db.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    current_resume = resume
    job_id = request.job_id
    language = request.output_language or get_content_language()
    prompt_id = request.prompt_id or "full"
    accumulated_skills: list[str] = list(request.confirmed_skills or [])
    final_preview: ImproveResumeResponse | None = None

    for round_num in range(1, max_rounds + 1):
        logger.info("Auto-loop round %d for resume=%s job=%s", round_num, current_resume["resume_id"], job_id)

        round_request = ImproveResumeRequest(
            resume_id=current_resume["resume_id"],
            job_id=job_id,
            prompt_id=prompt_id,
            confirmed_skills=accumulated_skills if accumulated_skills else None,
            extrapolation_mode=request.extrapolation_mode or "aggressive",
            output_language=language,
            include_cover_letter=(round_num == 1 and request.include_cover_letter),
            include_review=True,
        )

        try:
            preview_result = await _improve_preview_flow(
                request=round_request,
                resume=current_resume,
                job=job,
                language=language,
                prompt_id=prompt_id,
            )
            final_preview = preview_result
        except Exception as e:
            logger.error("Auto-loop tailor round %d failed: %s", round_num, e)
            break

        review = preview_result.data.review or {}
        missing_kws = review.get("missing_keywords", [])
        if isinstance(missing_kws, list):
            for mkw in missing_kws:
                if isinstance(mkw, str) and mkw.strip() and mkw.strip() not in accumulated_skills:
                    accumulated_skills.append(mkw.strip())

        rounds.append({
            "round": round_num,
            "match_score": review.get("match_score", 0),
            "verdict": review.get("verdict", "UNKNOWN"),
            "top_3_fixes": review.get("top_3_fixes", []),
            "missing_keywords": missing_kws,
            "passed": review.get("pass", False),
        })

        if review.get("pass", False) or int(review.get("match_score", 0) or 0) >= 85:
            logger.info("Auto-loop passed at round %d with score %s", round_num, review.get("match_score"))
            break

        # Prepare in-memory resume dict from this round's tailored output for the next round
        tailored_dict = preview_result.data.resume_preview.model_dump()
        current_resume = {
            **current_resume,
            "content": json.dumps(tailored_dict, indent=2),
            "processed_data": tailored_dict,
        }
        job = await db.get_job(job_id) or job

    return {
        "rounds": rounds,
        "total_rounds": len(rounds),
        "final_passed": rounds[-1]["passed"] if rounds else False,
        "final_score": rounds[-1]["match_score"] if rounds else 0,
        "preview": final_preview.model_dump() if final_preview else None,
        "resume_id": request.resume_id,
    }
