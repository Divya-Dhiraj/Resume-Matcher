"""Content guards on the tailoring prompts.

Two invariants this locks:
1. JD-keyword incorporation is the DEFAULT across sections (the maintainer goal).
2. The anti-fabrication clauses stay present. Per the truthfulness audit,
   invented bullet *narrative* (e.g. "led 12 engineers") is NOT caught by
   verify_diff_result (its metric regex misses bare counts) or verify_alignment
   (which only checks skills/certs/companies) — so these prompt clauses are the
   ONLY guard. If a future edit drops them, this test fails loudly.
"""

from app.prompts.templates import (
    COVER_LETTER_PROMPT,
    DIFF_IMPROVE_PROMPT,
    INTERVIEW_PREP_PROMPT,
)
from app.prompts.refinement import KEYWORD_INJECTION_PROMPT


class TestJdIncorporationIsDefault:
    def test_diff_prompt_reframes_by_default(self):
        assert "Scan every bullet" in DIFF_IMPROVE_PROMPT
        assert "translate" in DIFF_IMPROVE_PROMPT.lower()

    def test_keyword_injection_targets_every_section_by_default(self):
        assert "EVERY section" in KEYWORD_INJECTION_PROMPT
        assert "DEFAULT" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_reframes_in_jd_terminology(self):
        assert "terminology" in COVER_LETTER_PROMPT.lower()


class TestAdjacentExtrapolationClausesPresent:
    def test_diff_prompt_has_extrapolation_directive(self):
        assert "ADJACENT EXTRAPOLATION" in DIFF_IMPROVE_PROMPT
        assert "JD keyword" in DIFF_IMPROVE_PROMPT.lower() or "jd keywords" in DIFF_IMPROVE_PROMPT.lower()

    def test_keyword_injection_has_extrapolation_approach(self):
        assert "adjacent extrapolation" in KEYWORD_INJECTION_PROMPT.lower()
        assert "JD keywords" in KEYWORD_INJECTION_PROMPT or "keywords" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_uses_adjacent_extrapolation(self):
        assert "adjacent extrapolation" in COVER_LETTER_PROMPT.lower()
        assert "JD" in COVER_LETTER_PROMPT or "job description" in COVER_LETTER_PROMPT.lower()

    def test_interview_prep_keeps_no_fabrication_guardrails(self):
        assert "Do NOT invent experience" in INTERVIEW_PREP_PROMPT
        assert "tools, employers, metrics, certifications, skills" in INTERVIEW_PREP_PROMPT
        assert "Skill gaps are preparation targets only" in INTERVIEW_PREP_PROMPT
        assert "Do NOT translate JSON property names" in INTERVIEW_PREP_PROMPT
        assert "role_fit_analysis" in INTERVIEW_PREP_PROMPT
        assert "talking_points" in INTERVIEW_PREP_PROMPT
