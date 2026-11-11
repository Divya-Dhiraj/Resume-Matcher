"""Multi-pass resume refinement service.

This module provides functionality to refine an initially tailored resume through
multiple passes:
1. Keyword injection - add missing JD keywords where supported by master resume
2. AI phrase removal - replace AI-generated buzzwords with simpler alternatives
3. Master alignment validation - ensure no fabricated content was added
"""

import copy
import json
import logging
import re
from functools import lru_cache
from typing import Any

from app.llm import complete_json
from app.prompts.refinement import (
    AI_PHRASE_BLACKLIST,
    AI_PHRASE_REPLACEMENTS,
    KEYWORD_INJECTION_PROMPT,
)
from app.schemas.refinement import (
    AlignmentReport,
    AlignmentViolation,
    KeywordGapAnalysis,
    RefinementConfig,
    RefinementResult,
)

logger = logging.getLogger(__name__)

# LLM-012: Job description truncation limits
MAX_JD_LENGTH = 2000
MIN_TRUNCATION_WARNING_LENGTH = 1500


_SYNONYM_MAP: dict[str, list[str]] = {
    # --- Software / DevOps ---
    "javascript": ["js", "ecmascript"],
    "typescript": ["ts"],
    "python": ["py"],
    "postgresql": ["postgres", "psql"],
    "mongodb": ["mongo"],
    "kubernetes": ["k8s"],
    "ci/cd": ["cicd", "ci cd", "continuous integration", "continuous deployment"],
    "continuous integration": ["ci"],
    "continuous deployment": ["cd"],
    "amazon web services": ["aws"],
    "google cloud platform": ["gcp", "google cloud"],
    "microsoft azure": ["azure"],
    "react": ["reactjs", "react.js"],
    "node.js": ["nodejs", "node"],
    "vue.js": ["vuejs", "vue"],
    "next.js": ["nextjs", "next"],
    "docker": ["containerization", "containers"],
    "rest api": ["restful", "rest apis", "restful api"],
    "graphql": ["graph ql"],
    "sql": ["structured query language"],
    "nosql": ["no-sql"],
    "trpc": ["t-rpc"],
    "large language models": ["llms", "llm"],
    "software development life cycle": ["sdlc"],
    "object oriented programming": ["oop"],
    "application programming interface": ["api", "apis"],
    "user interface": ["ui"],
    "user experience": ["ux"],
    "ui/ux": ["ui ux", "ux/ui", "ux ui"],
    # --- Data & Analytics ---
    "machine learning": ["ml"],
    "artificial intelligence": ["ai"],
    "natural language processing": ["nlp"],
    "extract transform load": ["etl"],
    "data visualization": ["data viz"],
    "business intelligence": ["bi"],
    "power bi": ["powerbi"],
    "tableau": ["tableau desktop", "tableau server"],
    "key performance indicators": ["kpi", "kpis"],
    "return on investment": ["roi"],
    "data analysis": ["data analytics"],
    "statistical analysis": ["statistics", "statistical modeling"],
    # --- Project & Process ---
    "project management": ["pm", "project mgmt"],
    "program management": ["pgm", "program mgmt"],
    "agile": ["scrum", "kanban", "agile methodology"],
    "waterfall": ["waterfall methodology"],
    "project management professional": ["pmp"],
    "objectives and key results": ["okr", "okrs"],
    "service level agreement": ["sla", "slas"],
    # --- Finance & Business ---
    "profit and loss": ["p&l", "pnl"],
    "financial planning and analysis": ["fp&a", "fpa"],
    "generally accepted accounting principles": ["gaap"],
    "international financial reporting standards": ["ifrs"],
    "enterprise resource planning": ["erp"],
    "customer relationship management": ["crm"],
    "supply chain management": ["scm"],
    "mergers and acquisitions": ["m&a"],
    "due diligence": ["dd"],
    "year over year": ["yoy", "y/y"],
    "quarter over quarter": ["qoq", "q/q"],
    "compound annual growth rate": ["cagr"],
    # --- Marketing & Sales ---
    "search engine optimization": ["seo"],
    "search engine marketing": ["sem"],
    "pay per click": ["ppc"],
    "cost per acquisition": ["cpa"],
    "cost per click": ["cpc"],
    "click through rate": ["ctr"],
    "customer acquisition cost": ["cac"],
    "lifetime value": ["ltv", "clv"],
    "content management system": ["cms"],
    "social media marketing": ["smm"],
    # --- HR & Operations ---
    "human resources": ["hr"],
    "human resources information system": ["hris"],
    "applicant tracking system": ["ats"],
    "diversity equity and inclusion": ["dei", "de&i"],
    "employee resource group": ["erg", "ergs"],
    "full time equivalent": ["fte", "ftes"],
    "standard operating procedure": ["sop", "sops"],
    "quality assurance": ["qa"],
    "quality control": ["qc"],
    # --- Certifications & Frameworks ---
    "certified public accountant": ["cpa certified"],
    "chartered financial analyst": ["cfa"],
    "six sigma": ["6σ", "6 sigma"],
    "information technology infrastructure library": ["itil"],
}

_REVERSE_SYNONYM_MAP: dict[str, str] = {}
for _canonical, _aliases in _SYNONYM_MAP.items():
    for _alias in _aliases:
        _REVERSE_SYNONYM_MAP[_alias.lower()] = _canonical
    _REVERSE_SYNONYM_MAP[_canonical.lower()] = _canonical


def _keyword_in_text(keyword: str, text: str) -> bool:
    """Check if keyword or any of its synonyms exists as a whole term in text.

    SVC-010: Uses term boundaries instead of substring matching to avoid
    false positives like 'python' matching 'pythonic' or 'go' matching 'going'.
    Also checks synonym variants so 'PostgreSQL' matches 'Postgres' etc.
    """
    kw_lower = keyword.strip().lower()
    text_lower = text.lower()
    if not kw_lower:
        return False

    # Check exact match first
    escaped = re.escape(kw_lower)
    pattern = rf"(?<!\w){escaped}(?!\w)"
    if re.search(pattern, text_lower):
        return True

    # Check synonyms: gather all variant forms for this keyword
    variants: list[str] = []
    if kw_lower in _SYNONYM_MAP:
        variants.extend(_SYNONYM_MAP[kw_lower])
    if kw_lower in _REVERSE_SYNONYM_MAP:
        canonical = _REVERSE_SYNONYM_MAP[kw_lower]
        variants.append(canonical)
        variants.extend(a for a in _SYNONYM_MAP.get(canonical, []) if a != kw_lower)

    for variant in variants:
        escaped_v = re.escape(variant.lower())
        if re.search(rf"(?<!\w){escaped_v}(?!\w)", text_lower):
            return True

    return False


def _normalize_skill_key(skill: str) -> str:
    """Normalize a skill for case-insensitive comparisons."""
    return re.sub(r"\s+", " ", skill.strip()).casefold()


def _extract_jd_skill_keys(
    job_keywords: dict[str, Any],
    job_description: str,
    confirmed_skills: list[str] | None = None,
) -> set[str]:
    """Extract normalized required/preferred/confirmed skills."""
    keys: set[str] = set()
    for field in ("required_skills", "preferred_skills"):
        values = job_keywords.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value.strip():
                keys.add(_normalize_skill_key(value))
    for skill in confirmed_skills or []:
        if isinstance(skill, str) and skill.strip():
            keys.add(_normalize_skill_key(skill))
    return keys


async def refine_resume(
    initial_tailored: dict[str, Any],
    master_resume: dict[str, Any],
    job_description: str,
    job_keywords: dict[str, Any],
    config: RefinementConfig | None = None,
    confirmed_skills: list[str] | None = None,
) -> RefinementResult:
    """Multi-pass refinement of an initially tailored resume.

    Args:
        initial_tailored: Output from improve_resume() first pass
        master_resume: Original master resume data (source of truth)
        job_description: Raw job description text
        job_keywords: Extracted job keywords
        config: Refinement configuration

    Returns:
        RefinementResult with refined data and analysis
    """
    if config is None:
        config = RefinementConfig()

    current = _deep_copy(initial_tailored)
    passes = 0
    ai_phrases_found: list[str] = []
    keyword_analysis: KeywordGapAnalysis | None = None
    alignment: AlignmentReport | None = None

    # Pass 1: Keyword injection (single pass — multiple passes risk unnatural phrasing)
    if config.enable_keyword_injection:
        keyword_analysis = analyze_keyword_gaps(job_keywords, current, master_resume)
        if not keyword_analysis.injectable_keywords:
            logger.info("No injectable keywords found, skipping injection")
        else:
            logger.info(
                "Keyword injection: injecting %d keywords: %s",
                len(keyword_analysis.injectable_keywords),
                keyword_analysis.injectable_keywords,
            )
            try:
                current = await inject_keywords(
                    current,
                    keyword_analysis.injectable_keywords,
                    master_resume,
                    job_description,
                )
                passes += 1
            except Exception as e:
                logger.warning("Keyword injection failed: %s", e)

    # Pass 2: AI phrase removal and polish (local, no LLM call)
    if config.enable_ai_phrase_removal:
        current, removed = remove_ai_phrases(current, job_description)
        ai_phrases_found.extend(removed)
        if removed:
            logger.info("Removed %d AI phrases: %s", len(removed), removed)
            passes += 1

    # Pass 3: Master alignment validation
    # LLM-008: Alignment validation is MANDATORY - not optional fallback
    if config.enable_master_alignment_check:
        alignment = validate_master_alignment(
            current,
            master_resume,
            allowed_new_skills=_extract_jd_skill_keys(
                job_keywords,
                job_description,
                confirmed_skills=confirmed_skills,
            ),
        )
        if not alignment.is_aligned:
            # Count critical violations
            critical_violations = [
                v for v in alignment.violations if v.severity == "critical"
            ]
            logger.warning(
                "Alignment violations found: %d total, %d critical",
                len(alignment.violations),
                len(critical_violations),
            )

            if critical_violations:
                # LLM-008: Remove fabricated content before returning
                logger.error(
                    "Alignment violations found - removing fabricated content: %s",
                    [v.value for v in critical_violations],
                )
                # Fix violations before returning
                current = fix_alignment_violations(current, alignment.violations)
                passes += 1
            else:
                # Non-critical violations - fix and continue
                current = fix_alignment_violations(current, alignment.violations)
                passes += 1

    # Calculate final match percentage
    final_match = calculate_keyword_match(current, job_keywords)

    return RefinementResult(
        refined_data=current,
        passes_completed=passes,
        keyword_analysis=keyword_analysis,
        alignment_report=alignment,
        ai_phrases_removed=ai_phrases_found,
        final_match_percentage=final_match,
    )


def analyze_keyword_gaps(
    jd_keywords: dict[str, Any],
    tailored: dict[str, Any],
    master: dict[str, Any],
) -> KeywordGapAnalysis:
    """Analyze which JD keywords are missing from the tailored resume.

    Args:
        jd_keywords: Extracted job keywords with required_skills, preferred_skills, etc.
        tailored: Current tailored resume data
        master: Master resume data (source of truth)

    Returns:
        KeywordGapAnalysis with missing, injectable, and non-injectable keywords
    """
    # Extract text content from resumes
    tailored_text = _extract_all_text(tailored).lower()
    master_text = _extract_all_text(master).lower()

    # Get all keywords from JD
    all_jd_keywords: set[str] = set()
    all_jd_keywords.update(jd_keywords.get("required_skills", []))
    all_jd_keywords.update(jd_keywords.get("preferred_skills", []))
    all_jd_keywords.update(jd_keywords.get("keywords", []))

    # Find missing keywords
    missing: list[str] = []
    injectable: list[str] = []
    non_injectable: list[str] = []

    for keyword in all_jd_keywords:
        if not _keyword_in_text(keyword, tailored_text):
            missing.append(keyword)
            if _keyword_in_text(keyword, master_text):
                injectable.append(keyword)
            else:
                non_injectable.append(keyword)

    # Calculate percentages
    total = len(all_jd_keywords) if all_jd_keywords else 1
    current_match = (total - len(missing)) / total * 100
    potential_match = (total - len(non_injectable)) / total * 100

    return KeywordGapAnalysis(
        missing_keywords=missing,
        injectable_keywords=injectable,
        non_injectable_keywords=non_injectable,
        current_match_percentage=current_match,
        potential_match_percentage=potential_match,
    )


# Technical camelCase/mixedCase identifiers that legitimately start with a lowercase letter
_CAMEL_CASE_START_RE = re.compile(r"^[a-z]+[A-Z0-9]")
_LEADING_HTML_TAG_RE = re.compile(r"^(\s*(?:<[^>]+>\s*)*)")
_LEADING_JUNK_RE = re.compile(r"^[\s,;:\-–—•*]+")


def clean_and_capitalize_bullet(text: str) -> str:
    """Clean punctuation artifacts and ensure the first letter of a bullet is capitalized.

    Preserves leading HTML tags (e.g. ``<strong>``) and intentional camelCase
    technical identifiers (e.g. ``iOS``, ``eBay``, ``macOS``, ``k8s``, ``gRPC``).
    """
    if not text or not isinstance(text, str):
        return text

    # Collapse multiple spaces and clean spacing around punctuation
    cleaned = re.sub(r" {2,}", " ", text).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)

    # Separate any leading HTML tags so we clean and capitalize the actual text
    tag_match = _LEADING_HTML_TAG_RE.match(cleaned)
    leading_tags = tag_match.group(1) if tag_match else ""
    body = cleaned[len(leading_tags):]

    # Strip leftover leading punctuation/spaces (e.g. ", built..." after filler removal)
    body = _LEADING_JUNK_RE.sub("", body)
    if not body:
        return cleaned

    # Check if the first token is an intentional camelCase identifier (e.g., iOS, eBay, gRPC)
    first_word = body.split()[0] if body.split() else ""
    if _CAMEL_CASE_START_RE.match(first_word):
        return f"{leading_tags}{body}"

    # Capitalize the first alphabetical character if it is lowercase
    for idx, ch in enumerate(body):
        if ch.isalpha():
            if ch.islower():
                body = body[:idx] + ch.upper() + body[idx + 1 :]
            break

    return f"{leading_tags}{body}"


def remove_ai_phrases(
    data: dict[str, Any],
    job_description: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Remove AI-generated phrases from resume content.

    This is a local operation that doesn't require an LLM call.
    It performs case-insensitive replacement of blacklisted phrases,
    preserving capitalization at the start of sentences/bullets.
    Phrases that appear in the job description are protected from removal.

    Args:
        data: Resume data dictionary
        job_description: Job description text; phrases found here are skipped

    Returns:
        Tuple of (cleaned data, list of removed phrases)
    """
    # Build set of JD-protected phrases
    jd_lower = job_description.lower()
    jd_protected: set[str] = set()
    for phrase in AI_PHRASE_BLACKLIST:
        if phrase.lower() in jd_lower:
            jd_protected.add(phrase.lower())

    if jd_protected:
        logger.info("JD-protected phrases (skipping removal): %s", jd_protected)

    # Use a set to avoid duplicate tracking
    removed: set[str] = set()

    # Sort longest phrases first so e.g. "paradigm shift" and "proactively"
    # match before "paradigm" and "proactive".
    sorted_phrases = sorted(AI_PHRASE_BLACKLIST, key=len, reverse=True)

    def _build_phrase_pattern(phrase: str) -> re.Pattern[str]:
        escaped = re.escape(phrase)
        # Use word boundaries when the phrase starts/ends with word characters
        prefix = r"\b" if phrase[0].isalnum() else ""
        suffix = r"\b" if phrase[-1].isalnum() else ""
        return re.compile(f"{prefix}{escaped}{suffix}", re.IGNORECASE)

    phrase_patterns: list[tuple[str, re.Pattern[str], str]] = [
        (
            phrase,
            _build_phrase_pattern(phrase),
            AI_PHRASE_REPLACEMENTS.get(phrase.lower(), ""),
        )
        for phrase in sorted_phrases
        if phrase.lower() not in jd_protected
    ]

    def clean_text(text: str, *, is_sentence_field: bool = False) -> str:
        cleaned = text
        for phrase, pattern, replacement in phrase_patterns:
            if not pattern.search(cleaned):
                continue
            removed.add(phrase)

            def _replace_match(
                match: re.Match[str], repl: str = replacement
            ) -> str:
                matched_text = match.group(0)
                if not repl:
                    return ""
                # Preserve capitalization if the original word was capitalized
                if matched_text and matched_text[0].isupper() and repl[0].isalpha():
                    return repl[0].upper() + repl[1:]
                return repl

            cleaned = pattern.sub(_replace_match, cleaned)

        if is_sentence_field:
            cleaned = clean_and_capitalize_bullet(cleaned)
        else:
            cleaned = re.sub(r" {2,}", " ", cleaned).strip()
        return cleaned

    sentence_list_keys = {"description", "strings"}
    sentence_str_keys = {"summary", "text"}

    def clean_recursive(obj: Any, parent_key: str = "") -> Any:
        if isinstance(obj, str):
            is_sentence = parent_key in sentence_list_keys or parent_key in sentence_str_keys
            return clean_text(obj, is_sentence_field=is_sentence)
        elif isinstance(obj, list):
            return [clean_recursive(item, parent_key=parent_key) for item in obj]
        elif isinstance(obj, dict):
            return {k: clean_recursive(v, parent_key=k) for k, v in obj.items()}
        return obj

    cleaned_data = clean_recursive(data)
    return cleaned_data, list(removed)


def validate_master_alignment(
    tailored: dict[str, Any],
    master: dict[str, Any],
    allowed_new_skills: set[str] | None = None,
) -> AlignmentReport:
    """Verify tailored resume doesn't contain fabricated content.

    Checks that all skills, certifications, and work experience companies
    in the tailored resume exist in the master resume.

    Args:
        tailored: Tailored resume data
        master: Master resume data (source of truth)

    Returns:
        AlignmentReport with violations and confidence score
    """
    violations: list[AlignmentViolation] = []

    # Check skills - use full resume text for broader matching
    tailored_skills = set(
        s.lower()
        for s in tailored.get("additional", {}).get("technicalSkills", [])
        if isinstance(s, str)
    )
    master_skills = set(
        s.lower()
        for s in master.get("additional", {}).get("technicalSkills", [])
        if isinstance(s, str)
    )
    allowed_skills = {
        _normalize_skill_key(skill)
        for skill in (allowed_new_skills or set())
        if isinstance(skill, str) and skill.strip()
    }
    master_full_text = _extract_all_text(master).lower()

    for skill in tailored_skills - master_skills:
        if _normalize_skill_key(skill) in allowed_skills:
            continue
        # Check substring/containment: e.g. "Python" in "Python 3.x"
        has_substring_match = any(
            skill in ms or ms in skill for ms in master_skills if ms
        )
        # Check if skill appears anywhere in master resume text
        found_in_text = _keyword_in_text(skill, master_full_text)

        if has_substring_match or found_in_text:
            violations.append(
                AlignmentViolation(
                    field_path="additional.technicalSkills",
                    violation_type="skill_variant",
                    value=skill,
                    severity="info",
                )
            )
        else:
            violations.append(
                AlignmentViolation(
                    field_path="additional.technicalSkills",
                    violation_type="fabricated_skill",
                    value=skill,
                    severity="critical",
                )
            )

    # Check certifications
    tailored_certs = set(
        c.lower()
        for c in tailored.get("additional", {}).get("certificationsTraining", [])
        if isinstance(c, str)
    )
    master_certs = set(
        c.lower()
        for c in master.get("additional", {}).get("certificationsTraining", [])
        if isinstance(c, str)
    )

    for cert in tailored_certs - master_certs:
        violations.append(
            AlignmentViolation(
                field_path="additional.certificationsTraining",
                violation_type="fabricated_cert",
                value=cert,
                severity="critical",
            )
        )

    # Check work experience companies (should not add new companies)
    tailored_companies = set(
        exp.get("company", "").lower()
        for exp in tailored.get("workExperience", [])
        if isinstance(exp, dict)
    )
    master_companies = set(
        exp.get("company", "").lower()
        for exp in master.get("workExperience", [])
        if isinstance(exp, dict)
    )

    for company in tailored_companies - master_companies:
        if company:  # Skip empty strings
            violations.append(
                AlignmentViolation(
                    field_path="workExperience",
                    violation_type="fabricated_company",
                    value=company,
                    severity="critical",
                )
            )

    is_aligned = len([v for v in violations if v.severity == "critical"]) == 0
    confidence = 1.0 - (len(violations) * 0.1)  # Decrease confidence per violation

    return AlignmentReport(
        is_aligned=is_aligned,
        violations=violations,
        confidence_score=max(0.0, confidence),
    )


def _prepare_job_description(job_description: str) -> tuple[str, bool]:
    """LLM-012: Prepare job description for prompt, with truncation warning.

    Returns:
        Tuple of (truncated_text, was_truncated)
    """
    was_truncated = len(job_description) > MAX_JD_LENGTH

    if was_truncated:
        logger.warning(
            "Job description truncated from %d to %d characters",
            len(job_description),
            MAX_JD_LENGTH,
        )

    return job_description[:MAX_JD_LENGTH], was_truncated


def _validate_resume_structure(data: dict[str, Any]) -> bool:
    """LLM-014: Validate resume maintains required structure after keyword injection.

    Returns:
        True if structure is valid, False otherwise.
    """
    # Check for required top-level keys
    required_keys = ["personalInfo"]
    for key in required_keys:
        if key not in data:
            logger.warning("Resume structure invalid: missing '%s'", key)
            return False

    # Check that arrays are still arrays
    array_fields = ["workExperience", "education", "personalProjects"]
    for field in array_fields:
        if field in data and not isinstance(data[field], list):
            logger.warning("Resume structure invalid: '%s' is not a list", field)
            return False

    return True


def _preserve_description_styles(
    original: dict[str, Any], improved: dict[str, Any]
) -> dict[str, Any]:
    """Restore descriptionStyles the LLM dropped or truncated (H-04).

    ``descriptionStyles`` is positional metadata parallel to ``description``.
    An LLM cannot be relied on to carry it through a rewrite, and when it is
    absent ``ResumeData`` silently backfills every row to ``"bullet"`` — so a
    user's "plain" rows are erased with no warning and no log.

    Rows are matched by index, which is the same contract the frontend and the
    Pydantic validators use. Where the improved list is longer than the
    original, the extra rows keep whatever the model returned (defaulting to
    bullet downstream).

    Args:
        original: The resume before refinement.
        improved: The resume returned by the LLM.

    Returns:
        ``improved``, mutated in place, with descriptionStyles restored.
    """
    item_fields = ("workExperience", "personalProjects")

    def _restore(orig_items: Any, new_items: Any) -> None:
        if not isinstance(orig_items, list) or not isinstance(new_items, list):
            return
        for index, new_item in enumerate(new_items):
            if index >= len(orig_items):
                continue
            orig_item = orig_items[index]
            if not isinstance(orig_item, dict) or not isinstance(new_item, dict):
                continue
            orig_styles = orig_item.get("descriptionStyles")
            if not isinstance(orig_styles, list) or not orig_styles:
                continue
            new_styles = new_item.get("descriptionStyles")
            if isinstance(new_styles, list) and len(new_styles) == len(
                new_item.get("description") or []
            ):
                # The model returned a correctly-aligned list; trust it.
                continue
            description = new_item.get("description")
            if not isinstance(description, list):
                continue
            new_item["descriptionStyles"] = [
                orig_styles[i] if i < len(orig_styles) else "bullet"
                for i in range(len(description))
            ]
            logger.debug(
                "Restored descriptionStyles dropped by the LLM (index %d)", index
            )

    for field in item_fields:
        _restore(original.get(field), improved.get(field))

    # customSections is `dict[str, CustomSection]` keyed by section id (see
    # ResumeData in app/schemas/models.py) -- NOT a list. Matching by position
    # would be wrong even if the shape allowed it, since dict ordering is not
    # part of the contract; match by key.
    orig_sections = original.get("customSections")
    new_sections = improved.get("customSections")
    if isinstance(orig_sections, dict) and isinstance(new_sections, dict):
        for key, new_section in new_sections.items():
            orig_section = orig_sections.get(key)
            if not isinstance(orig_section, dict) or not isinstance(new_section, dict):
                continue
            _restore(orig_section.get("items"), new_section.get("items"))

    return improved


async def inject_keywords(
    tailored: dict[str, Any],
    keywords_to_inject: list[str],
    master: dict[str, Any],
    job_description: str,
) -> dict[str, Any]:
    """Use LLM to inject missing keywords into appropriate sections.

    Args:
        tailored: Current tailored resume
        keywords_to_inject: Keywords that are in master but missing from tailored
        master: Master resume (source of truth)
        job_description: Job description for context

    Returns:
        Updated resume data with keywords injected

    LLM-012: Truncates job description with warning.
    LLM-014: Validates result structure before returning.
    """
    # LLM-012: Prepare job description with truncation handling
    truncated_jd, was_truncated = _prepare_job_description(job_description)
    if was_truncated:
        logger.info(
            "Job description was truncated for keyword injection (original: %d chars)",
            len(job_description),
        )

    from app.config_cache import get_system_prompt_override

    ki_prompt = get_system_prompt_override("keyword_injection") or KEYWORD_INJECTION_PROMPT
    prompt = ki_prompt.format(
        keywords_to_inject=json.dumps(keywords_to_inject),
        current_resume=json.dumps(tailored),
        master_resume=json.dumps(master),
        job_description=truncated_jd,
    )

    try:
        result = await complete_json(
            prompt=prompt,
            system_prompt=(
                "You are a resume editor. Inject keywords naturally without adding "
                "fabricated content. Return only valid JSON matching the input schema."
            ),
            max_tokens=8192,
        )

        # LLM-014: Validate the result maintains required structure
        if not isinstance(result, dict):
            logger.warning("Keyword injection returned non-dict: %s", type(result))
            return tailored

        if not _validate_resume_structure(result):
            logger.warning(
                "Keyword injection corrupted resume structure, using original"
            )
            return tailored

        # H-04: the prompt asks the model to preserve descriptionStyles, but a
        # prompt is not a guarantee for positional metadata. Restore it locally,
        # matching the defence-in-depth pattern the improve pipeline already
        # uses for dates, skills, personalInfo and custom sections.
        return _preserve_description_styles(tailored, result)

    except Exception as e:
        logger.warning("Keyword injection failed: %s", e)
        return tailored


def fix_alignment_violations(
    tailored: dict[str, Any],
    violations: list[AlignmentViolation],
) -> dict[str, Any]:
    """Remove or correct alignment violations.

    This is a local operation that removes fabricated content.

    Args:
        tailored: Tailored resume data
        violations: List of alignment violations to fix

    Returns:
        Fixed resume data
    """
    fixed = _deep_copy(tailored)

    for violation in violations:
        if violation.severity != "critical":
            continue

        if violation.violation_type == "fabricated_skill":
            skills = fixed.get("additional", {}).get("technicalSkills", [])
            fixed.setdefault("additional", {})["technicalSkills"] = [
                s for s in skills if s.lower() != violation.value.lower()
            ]

        elif violation.violation_type == "fabricated_cert":
            certs = fixed.get("additional", {}).get("certificationsTraining", [])
            fixed.setdefault("additional", {})["certificationsTraining"] = [
                c for c in certs if c.lower() != violation.value.lower()
            ]

        elif violation.violation_type == "fabricated_company":
            # SVC-002: Remove the fabricated work experience entry
            logger.error("Critical: Fabricated company detected: %s", violation.value)
            if "workExperience" in fixed:
                fixed["workExperience"] = [
                    exp
                    for exp in fixed["workExperience"]
                    if exp.get("company", "").lower() != violation.value.lower()
                ]
                logger.info(
                    "Removed fabricated company '%s' from resume",
                    violation.value,
                )

    return fixed


def strip_hidden_sections(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of resume data with hidden sections' content cleared.

    Reads ``sectionMeta`` to decide visibility. Sections whose
    ``isVisible`` is ``False`` have their content emptied so that
    scoring functions (review LLM, keyword match) only evaluate what
    the user actually sees in the rendered resume.
    """
    section_meta = data.get("sectionMeta", {})
    if not isinstance(section_meta, dict) or not section_meta:
        return data

    filtered = copy.deepcopy(data)

    section_to_field: dict[str, str | list[str]] = {
        "summary": "summary",
        "workExperience": "workExperience",
        "education": "education",
        "personalProjects": "personalProjects",
        "additional": "additional",
    }

    for section_key, field in section_to_field.items():
        meta = section_meta.get(section_key, {})
        if isinstance(meta, dict) and meta.get("isVisible") is False:
            if isinstance(field, str):
                if isinstance(filtered.get(field), str):
                    filtered[field] = ""
                elif isinstance(filtered.get(field), list):
                    filtered[field] = []
                elif isinstance(filtered.get(field), dict):
                    filtered[field] = {}

    # Also handle customSections
    custom_sections = filtered.get("customSections", {})
    if isinstance(custom_sections, dict):
        for cs_key in list(custom_sections.keys()):
            meta = section_meta.get(cs_key, {})
            if isinstance(meta, dict) and meta.get("isVisible") is False:
                custom_sections[cs_key] = {}

    return filtered


def calculate_keyword_match(
    resume: dict[str, Any],
    jd_keywords: dict[str, Any],
) -> float:
    """Calculate keyword match percentage.

    Args:
        resume: Resume data dictionary
        jd_keywords: Extracted job keywords

    Returns:
        Match percentage (0.0 to 100.0)
    """
    resume_text = _extract_all_text(strip_hidden_sections(resume)).lower()

    # Weighted scoring: required skills matter most, then preferred, then general
    _WEIGHT_REQUIRED = 3.0
    _WEIGHT_PREFERRED = 2.0
    _WEIGHT_GENERAL = 1.0

    required = jd_keywords.get("required_skills", [])
    preferred = jd_keywords.get("preferred_skills", [])
    general = jd_keywords.get("keywords", [])

    weighted_items: list[tuple[str, float]] = []
    seen: set[str] = set()
    for kw in required:
        k = kw.strip().lower() if isinstance(kw, str) else ""
        if k and k not in seen:
            seen.add(k)
            weighted_items.append((kw, _WEIGHT_REQUIRED))
    for kw in preferred:
        k = kw.strip().lower() if isinstance(kw, str) else ""
        if k and k not in seen:
            seen.add(k)
            weighted_items.append((kw, _WEIGHT_PREFERRED))
    for kw in general:
        k = kw.strip().lower() if isinstance(kw, str) else ""
        if k and k not in seen:
            seen.add(k)
            weighted_items.append((kw, _WEIGHT_GENERAL))

    # SVC-009: Return 0% if no keywords (not 100% - that's misleading)
    if not weighted_items:
        logger.warning("No keywords found in job description")
        return 0.0

    total_weight = sum(w for _, w in weighted_items)
    matched_weight = sum(w for kw, w in weighted_items if _keyword_in_text(kw, resume_text))
    return (matched_weight / total_weight) * 100


def _extract_all_text(data: dict[str, Any]) -> str:
    """Extract all text content from resume data for keyword matching.

    SVC-011: Uses caching to avoid repeated extraction on same resume data.

    Args:
        data: Resume data dictionary

    Returns:
        Concatenated text from all resume sections
    """
    # Create a cache key from the data
    data_json = json.dumps(data, sort_keys=True, default=str)
    return _extract_all_text_cached(data_json)


@lru_cache(maxsize=100)
def _extract_all_text_cached(data_json: str) -> str:
    """Cached implementation of text extraction.

    SVC-011: LRU cache avoids re-extracting text from the same resume
    multiple times during a single refinement pass.
    """
    data = json.loads(data_json)
    parts: list[str] = []

    # Summary
    if data.get("summary"):
        parts.append(str(data["summary"]))

    # Work experience
    for exp in data.get("workExperience", []):
        if isinstance(exp, dict):
            parts.append(str(exp.get("title", "")))
            parts.append(str(exp.get("company", "")))
            desc = exp.get("description", [])
            if isinstance(desc, list):
                parts.extend(str(d) for d in desc)

    # Education
    for edu in data.get("education", []):
        if isinstance(edu, dict):
            parts.append(str(edu.get("degree", "")))
            parts.append(str(edu.get("institution", "")))
            if edu.get("description"):
                parts.append(str(edu["description"]))

    # Projects
    for proj in data.get("personalProjects", []):
        if isinstance(proj, dict):
            parts.append(str(proj.get("name", "")))
            parts.append(str(proj.get("role", "")))
            desc = proj.get("description", [])
            if isinstance(desc, list):
                parts.extend(str(d) for d in desc)

    # Additional
    additional = data.get("additional", {})
    if isinstance(additional, dict):
        skills = additional.get("technicalSkills", [])
        if isinstance(skills, list):
            parts.extend(str(s) for s in skills)
        certs = additional.get("certificationsTraining", [])
        if isinstance(certs, list):
            parts.extend(str(c) for c in certs)
        languages = additional.get("languages", [])
        if isinstance(languages, list):
            parts.extend(str(lang) for lang in languages)
        awards = additional.get("awards", [])
        if isinstance(awards, list):
            parts.extend(str(a) for a in awards)

    # Custom sections
    custom_sections = data.get("customSections", {})
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            if not isinstance(section, dict):
                continue
            section_type = section.get("sectionType", "")
            if section_type == "itemList":
                for item in section.get("items", []):
                    if isinstance(item, dict):
                        parts.append(str(item.get("title", "")))
                        parts.append(str(item.get("subtitle", "")))
                        desc = item.get("description", [])
                        if isinstance(desc, list):
                            parts.extend(str(d) for d in desc)
                        elif isinstance(desc, str):
                            parts.append(desc)
            elif section_type == "text":
                text = section.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
            elif section_type == "stringList":
                items = section.get("strings", [])
                if isinstance(items, list):
                    parts.extend(str(i) for i in items)
            elif section_type == "groupedList":
                for block in section.get("blocks", []) or []:
                    if isinstance(block, dict):
                        if block.get("label"):
                            parts.append(str(block["label"]))
                        b_items = block.get("items", [])
                        if isinstance(b_items, list):
                            parts.extend(str(i) for i in b_items)

    return " ".join(p for p in parts if p)


def _deep_copy(data: dict[str, Any]) -> dict[str, Any]:
    """Create a deep copy of a dictionary.

    Uses copy.deepcopy for reliability. JSON serialization is avoided
    because it can't handle all Python types and loses type information.
    """
    return copy.deepcopy(data)
