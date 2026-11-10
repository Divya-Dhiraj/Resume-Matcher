"""Integration tests for the preview pipeline: tailor + cover letter + review."""

import json
from unittest.mock import patch, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def mock_resume_record(sample_resume):
    return {
        "resume_id": "res-pipe",
        "content": "# Jane Doe\nSenior Backend Engineer",
        "content_type": "md",
        "filename": "resume.pdf",
        "is_master": True,
        "parent_id": None,
        "processed_data": sample_resume,
        "processing_status": "ready",
        "cover_letter": None,
        "outreach_message": None,
        "interview_prep": None,
        "title": None,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }


@pytest.fixture
def mock_job():
    return {
        "job_id": "job-pipe",
        "content": "Looking for a Python backend developer with FastAPI experience.",
        "job_keywords": {
            "hard_skills": ["Python", "FastAPI"],
            "soft_skills": ["Communication"],
            "tools": [],
            "certifications": [],
            "company": "Acme",
            "role": "Backend Dev",
        },
        "job_keywords_hash": None,
        "preview_hash": None,
        "preview_hashes": {},
    }


MOCK_DIFF_RESULT_OBJ = type("DiffResult", (), {
    "changes": [],
    "summary": "No changes",
    "model_used": "test-model",
})()

MOCK_REVIEW_RESULT = {
    "match_score": 82,
    "verdict": "INTERVIEW",
    "missing_keywords": ["Docker"],
    "weak_bullets": [],
    "top_3_fixes": ["Add Docker experience"],
    "pass": True,
    "panel_scores": {"ats": 80, "hiring_manager": 85},
}


class TestPreviewPipelineOutputLanguage:
    """output_language in the request overrides the system content language."""

    @pytest.mark.asyncio
    async def test_output_language_passed_to_preview(
        self, client, mock_resume_record, mock_job, sample_resume
    ):
        with (
            patch("app.routers.resumes.db") as mock_db,
            patch("app.routers.resumes.extract_job_keywords", new_callable=AsyncMock) as mock_extract,
            patch("app.routers.resumes.generate_skill_target_plan", new_callable=AsyncMock) as mock_plan,
            patch("app.routers.resumes.verify_skill_target_plan") as mock_verify,
            patch("app.routers.resumes.generate_resume_diffs", new_callable=AsyncMock) as mock_diffs,
            patch("app.routers.resumes.apply_diffs") as mock_apply,
            patch("app.routers.resumes.verify_diff_result") as mock_verify_diff,
            patch("app.routers.resumes.refine_resume", new_callable=AsyncMock) as mock_refine,
            patch("app.routers.resumes.get_content_language") as mock_lang,
        ):
            mock_db.get_resume = AsyncMock(return_value=mock_resume_record)
            mock_db.get_job = AsyncMock(return_value=mock_job)
            mock_db.update_job = AsyncMock(return_value=mock_job)
            mock_db.get_master_resume = AsyncMock(return_value=mock_resume_record)
            mock_extract.return_value = mock_job["job_keywords"]
            mock_plan.return_value = {"targets": []}
            mock_verify.return_value = {"accepted": [], "rejected": []}
            mock_diffs.return_value = MOCK_DIFF_RESULT_OBJ
            mock_apply.return_value = (sample_resume, [], [])
            mock_verify_diff.return_value = []
            mock_refine.side_effect = Exception("skip refine")
            mock_lang.return_value = "en"

            resp = await client.post(
                "/api/v1/resumes/improve/preview",
                json={
                    "resume_id": "res-pipe",
                    "job_id": "job-pipe",
                    "output_language": "de",
                },
            )

            assert resp.status_code == 200
            # The diffs function should have been called with language="de"
            call_kwargs = mock_diffs.call_args
            assert call_kwargs.kwargs.get("language") == "de" or call_kwargs[1].get("language") == "de"


class TestPreviewPipelineCoverLetterAndReview:
    """include_cover_letter and include_review produce inline results."""

    @pytest.mark.asyncio
    async def test_cover_letter_and_review_included(
        self, client, mock_resume_record, mock_job, sample_resume
    ):
        with (
            patch("app.routers.resumes.db") as mock_db,
            patch("app.routers.resumes.extract_job_keywords", new_callable=AsyncMock) as mock_extract,
            patch("app.routers.resumes.generate_skill_target_plan", new_callable=AsyncMock) as mock_plan,
            patch("app.routers.resumes.verify_skill_target_plan") as mock_verify,
            patch("app.routers.resumes.generate_resume_diffs", new_callable=AsyncMock) as mock_diffs,
            patch("app.routers.resumes.apply_diffs") as mock_apply,
            patch("app.routers.resumes.verify_diff_result") as mock_verify_diff,
            patch("app.routers.resumes.refine_resume", new_callable=AsyncMock) as mock_refine,
            patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock) as mock_cl,
            patch("app.routers.resumes._inline_review", new_callable=AsyncMock) as mock_review,
            patch("app.routers.resumes.get_content_language") as mock_lang,
        ):
            mock_db.get_resume = AsyncMock(return_value=mock_resume_record)
            mock_db.get_job = AsyncMock(return_value=mock_job)
            mock_db.update_job = AsyncMock(return_value=mock_job)
            mock_db.get_master_resume = AsyncMock(return_value=mock_resume_record)
            mock_extract.return_value = mock_job["job_keywords"]
            mock_plan.return_value = {"targets": []}
            mock_verify.return_value = {"accepted": [], "rejected": []}
            mock_diffs.return_value = MOCK_DIFF_RESULT_OBJ
            mock_apply.return_value = (sample_resume, [], [])
            mock_verify_diff.return_value = []
            mock_refine.side_effect = Exception("skip refine")
            mock_cl.return_value = "Dear Hiring Manager, ..."
            mock_review.return_value = MOCK_REVIEW_RESULT
            mock_lang.return_value = "en"

            resp = await client.post(
                "/api/v1/resumes/improve/preview",
                json={
                    "resume_id": "res-pipe",
                    "job_id": "job-pipe",
                    "include_cover_letter": True,
                    "include_review": True,
                },
            )

            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["cover_letter"] == "Dear Hiring Manager, ..."
            assert data["review"]["match_score"] == 82
            assert data["review"]["missing_keywords"] == ["Docker"]

    @pytest.mark.asyncio
    async def test_cover_letter_not_included_by_default(
        self, client, mock_resume_record, mock_job, sample_resume
    ):
        with (
            patch("app.routers.resumes.db") as mock_db,
            patch("app.routers.resumes.extract_job_keywords", new_callable=AsyncMock) as mock_extract,
            patch("app.routers.resumes.generate_skill_target_plan", new_callable=AsyncMock) as mock_plan,
            patch("app.routers.resumes.verify_skill_target_plan") as mock_verify,
            patch("app.routers.resumes.generate_resume_diffs", new_callable=AsyncMock) as mock_diffs,
            patch("app.routers.resumes.apply_diffs") as mock_apply,
            patch("app.routers.resumes.verify_diff_result") as mock_verify_diff,
            patch("app.routers.resumes.refine_resume", new_callable=AsyncMock) as mock_refine,
            patch("app.routers.resumes.get_content_language") as mock_lang,
        ):
            mock_db.get_resume = AsyncMock(return_value=mock_resume_record)
            mock_db.get_job = AsyncMock(return_value=mock_job)
            mock_db.update_job = AsyncMock(return_value=mock_job)
            mock_db.get_master_resume = AsyncMock(return_value=mock_resume_record)
            mock_extract.return_value = mock_job["job_keywords"]
            mock_plan.return_value = {"targets": []}
            mock_verify.return_value = {"accepted": [], "rejected": []}
            mock_diffs.return_value = MOCK_DIFF_RESULT_OBJ
            mock_apply.return_value = (sample_resume, [], [])
            mock_verify_diff.return_value = []
            mock_refine.side_effect = Exception("skip refine")
            mock_lang.return_value = "en"

            resp = await client.post(
                "/api/v1/resumes/improve/preview",
                json={
                    "resume_id": "res-pipe",
                    "job_id": "job-pipe",
                },
            )

            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["cover_letter"] is None
            assert data["review"] is None
