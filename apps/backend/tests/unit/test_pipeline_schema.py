"""Unit tests for the pipeline request/response schema fields."""

from app.schemas.models import ImproveResumeRequest, ImproveResumeData


class TestImproveResumeRequestPipelineFields:
    def test_output_language_defaults_none(self):
        req = ImproveResumeRequest(resume_id="r1", job_id="j1")
        assert req.output_language is None

    def test_output_language_accepts_de(self):
        req = ImproveResumeRequest(resume_id="r1", job_id="j1", output_language="de")
        assert req.output_language == "de"

    def test_include_cover_letter_defaults_false(self):
        req = ImproveResumeRequest(resume_id="r1", job_id="j1")
        assert req.include_cover_letter is False

    def test_include_review_defaults_false(self):
        req = ImproveResumeRequest(resume_id="r1", job_id="j1")
        assert req.include_review is False

    def test_include_flags_set_true(self):
        req = ImproveResumeRequest(
            resume_id="r1",
            job_id="j1",
            include_cover_letter=True,
            include_review=True,
        )
        assert req.include_cover_letter is True
        assert req.include_review is True


class TestImproveResumeDataReviewField:
    def test_review_defaults_none(self):
        data = ImproveResumeData(
            request_id="req1",
            job_id="j1",
            resume_preview={"personalInfo": {"name": "Test"}},
            improvements=[],
        )
        assert data.review is None

    def test_review_accepts_dict(self):
        review = {
            "match_score": 85,
            "verdict": "INTERVIEW",
            "missing_keywords": [],
            "pass": True,
        }
        data = ImproveResumeData(
            request_id="req1",
            job_id="j1",
            resume_preview={"personalInfo": {"name": "Test"}},
            improvements=[],
            review=review,
        )
        assert data.review["match_score"] == 85
