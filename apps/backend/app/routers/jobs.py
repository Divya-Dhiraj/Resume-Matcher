"""Job description management endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import db
from app.schemas import JobUploadRequest, JobUploadResponse
from app.services.improver import extract_job_keywords

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/upload", response_model=JobUploadResponse)
async def upload_job_descriptions(request: JobUploadRequest) -> JobUploadResponse:
    """Upload one or more job descriptions.

    Stores the raw text for later use in resume tailoring.
    Returns an array of job_ids corresponding to the input array.
    """
    if not request.job_descriptions:
        raise HTTPException(status_code=400, detail="No job descriptions provided")

    job_ids = []
    for jd in request.job_descriptions:
        if not jd.strip():
            raise HTTPException(status_code=400, detail="Empty job description")

        job = await db.create_job(
            content=jd.strip(),
            resume_id=request.resume_id,
        )
        job_ids.append(job["job_id"])

    return JobUploadResponse(
        message="data successfully processed",
        job_id=job_ids,
        request={
            "job_descriptions": request.job_descriptions,
            "resume_id": request.resume_id,
        },
    )


class JobUpdateRequest(BaseModel):
    content: str = Field(min_length=1)


@router.patch("/{job_id}")
async def update_job(job_id: str, request: JobUpdateRequest) -> dict:
    """Update a job description's content."""
    job = await db.update_job(job_id, {"content": request.content.strip()})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    """Get job description by ID."""
    job = await db.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


def _hash_job_content(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode()).hexdigest()[:16]


@router.post("/{job_id}/extract-keywords")
async def extract_keywords_for_job(job_id: str) -> dict[str, Any]:
    """Extract keywords from a job description (cheap ~500-token call).

    Returns cached keywords if the content hash matches, otherwise
    runs LLM extraction and caches the result on the job record.
    """
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    content_hash = _hash_job_content(job["content"])
    existing_hash = job.get("job_keywords_hash")
    existing_keywords = job.get("job_keywords")

    if existing_keywords and existing_hash == content_hash:
        return {
            "job_id": job_id,
            "keywords": existing_keywords,
            "cached": True,
        }

    try:
        keywords = await extract_job_keywords(job["content"])
    except Exception as e:
        logger.error("Keyword extraction failed for job %s: %s", job_id, e)
        raise HTTPException(
            status_code=500,
            detail="Keyword extraction failed. Please try again.",
        )

    cache_updates: dict[str, Any] = {
        "job_keywords": keywords,
        "job_keywords_hash": content_hash,
    }
    raw_company = keywords.get("company")
    raw_role = keywords.get("role")
    company = raw_company.strip() if isinstance(raw_company, str) else ""
    role = raw_role.strip() if isinstance(raw_role, str) else ""
    if company:
        cache_updates["company"] = company
    if role:
        cache_updates["role"] = role

    try:
        await db.update_job(job_id, cache_updates)
    except Exception as e:
        logger.warning("Failed to cache keywords for job %s: %s", job_id, e)

    return {
        "job_id": job_id,
        "keywords": keywords,
        "cached": False,
        "company": company,
        "role": role,
    }
