"""Multi-pass resume parser.

Splits the resume markdown into section blocks (regex, no LLM), then extracts
each block with a small, focused prompt (parallel LLM calls). This avoids
the single-shot failure mode where a 14B local model, asked to emit the
whole ResumeData schema, drops fields whose entries appear after a long
workExperience array and closes the JSON early.

Concretely, on a dense master CV that previously produced 0 skills and
0 custom sections, the multi-pass parser produces the full skills grouping
and every custom section by construction — each is its own tiny call.

Latency trade-off: ~5-8 LLM calls instead of 1, but they run in parallel
via asyncio.gather. On qwen2.5:14b the wall-clock cost is roughly 1.5-2×
a single-shot call (bounded by the slowest section, usually workExperience).

Fallback: if a section extractor errors, that section is left empty in the
returned dict. The single-shot parser stays available as an outer fallback
(see parser.parse_resume_to_json).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.llm import complete_json, get_llm_config, get_model_name, get_safe_max_tokens
from app.prompts.multi_pass import (
    CUSTOM_SECTION_PROMPT,
    EDUCATION_PROMPT,
    EXPERIENCE_PROMPT,
    FLAT_LIST_PROMPT,
    PERSONAL_INFO_PROMPT,
    SKILLS_PROMPT,
    SUMMARY_PROMPT,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Section detection (regex, no LLM)
# --------------------------------------------------------------------------- #

# Canonical section kinds. Anything not in this map lands in "other" and is
# treated as a custom itemList section keyed by its heading slug.
_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "profile", "professional summary", "profile summary", "about", "objective"),
    "experience": (
        "professional experience",
        "work experience",
        "experience",
        "employment",
        "employment history",
        "career",
    ),
    "education": ("education", "academic background", "qualifications", "studies"),
    "projects": ("projects", "personal projects", "side projects", "portfolio"),
    "research": ("research", "research experience", "research projects"),
    "skills": (
        "skills",
        "technical skills",
        "core skills",
        "core competencies",
        "competencies",
        "skills & awards",
        "skills and awards",
    ),
    "languages": ("languages", "language", "spoken languages"),
    "certifications": (
        "certifications",
        "certifications & training",
        "certifications and training",
        "certificates",
        "training",
        "trainings",
        "courses",
    ),
    "awards": ("awards", "honors", "honours", "achievements", "recognitions"),
    "publications": ("publications", "papers", "articles"),
    "volunteer": ("volunteer", "volunteering", "volunteer work", "community"),
    "interests": ("interests", "hobbies"),
}

# Reverse index: heading text (lowercased) → canonical kind.
_HEADING_TO_KIND: dict[str, str] = {
    heading: kind for kind, aliases in _SECTION_ALIASES.items() for heading in aliases
}

# Match a heading line. Common resume heading shapes:
#   ALL CAPS ("PROFESSIONAL EXPERIENCE")
#   Title case ("Professional Experience")
#   Markdown-style ("## Professional Experience", "**Professional Experience**")
# Rejects lines with a colon (skill category), a comma (list), or trailing
# punctuation that suggests body text. The line must be short and mostly
# uppercase or title case.
_HEADING_RE = re.compile(
    r"^\s*(?:#+\s*)?\*{0,2}([A-Z][A-Z0-9 &/,\-']{2,40}?|[A-Z][a-zA-Z &/'-]{2,40}?)\*{0,2}\s*:?\s*$"
)


def _is_heading(line: str, next_lines: list[str]) -> str | None:
    """Return the canonical section kind for a heading line, or None if the
    line doesn't look like one. `next_lines` lets us reject "headings" that
    actually have body text on the same conceptual line (skill category, etc.)."""
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return None
    if ":" in stripped and not stripped.rstrip(":").isupper():
        # "Programming: Python, SQL" is a skill category, not a section head.
        return None
    if "," in stripped or "." in stripped.rstrip("."):
        return None
    m = _HEADING_RE.match(stripped)
    if not m:
        return None
    text = m.group(1).strip().rstrip(":").lower()
    # Direct exact alias hit
    if text in _HEADING_TO_KIND:
        return _HEADING_TO_KIND[text]
    # Fuzzy: "PROFESSIONAL EXPERIENCE " with trailing whitespace, etc.
    text_condensed = re.sub(r"\s+", " ", text)
    if text_condensed in _HEADING_TO_KIND:
        return _HEADING_TO_KIND[text_condensed]
    # Not a canonical section — but still return "other" if it looks like a
    # heading (uppercase or well-formed title case), so we can promote it to
    # a custom section. The `next_lines` heuristic filters out isolated
    # single-line noise.
    if stripped.isupper() and next_lines and any(nl.strip() for nl in next_lines[:3]):
        return f"other:{text}"
    return None


def split_into_sections(markdown: str) -> dict[str, str]:
    """Slice the resume markdown into named section blocks.

    Returns a dict where keys are canonical section kinds (`"summary"`,
    `"experience"`, `"education"`, …) or `"other:<heading slug>"` for
    unrecognized headings. The special key `"header"` holds everything
    before the first recognized heading — that's where personal info lives.

    We ignore any "heading" candidates found in the header block itself so
    that the person's name (usually the first ALL-CAPS line) doesn't get
    misread as an "other:" custom section — the header only ends when a
    CANONICAL section heading appears (Experience, Education, Skills, …).
    """
    lines = markdown.splitlines()
    blocks: dict[str, list[str]] = {"header": []}
    current_kind = "header"
    seen_canonical = False

    i = 0
    while i < len(lines):
        line = lines[i]
        kind = _is_heading(line, lines[i + 1 : i + 4])
        # Suppress "other:" headings until we've seen at least one canonical
        # section — that keeps the person's name (an ALL-CAPS line that
        # happens to look heading-shaped) inside the header block instead
        # of spawning a bogus custom section.
        if kind and kind.startswith("other:") and not seen_canonical:
            kind = None
        if kind:
            current_kind = kind
            if not kind.startswith("other:"):
                seen_canonical = True
            # Don't include the heading line itself in the block body —
            # the per-section prompts don't need it and it can confuse the
            # LLM into treating the heading as content.
            blocks.setdefault(current_kind, [])
        else:
            blocks.setdefault(current_kind, []).append(line)
        i += 1

    return {kind: "\n".join(body).strip() for kind, body in blocks.items() if body}


# --------------------------------------------------------------------------- #
# Focused LLM extractors
# --------------------------------------------------------------------------- #


async def _extract(prompt: str, section_name: str, max_tokens: int) -> dict[str, Any]:
    """Wrap complete_json with a section-tagged log line so the LLM Inspector
    entries are easy to associate with a specific pass. Any exception is
    caught and turned into an empty dict — the merge step then keeps that
    field as its schema default rather than aborting the whole parse."""
    try:
        return await complete_json(
            prompt=prompt,
            system_prompt="You are a JSON extraction engine. Output only valid JSON, no explanations.",
            max_tokens=max_tokens,
            retries=2,
        )
    except Exception:
        logger.exception("multi_pass: %s extraction failed", section_name)
        return {}


async def _extract_personal_info(header_block: str, max_tokens: int) -> dict[str, Any]:
    if not header_block.strip():
        return {}
    prompt = PERSONAL_INFO_PROMPT.format(block=header_block)
    result = await _extract(prompt, "personalInfo", max_tokens)
    # `result` should BE the personal-info dict; if the LLM wrapped it,
    # unwrap common shapes.
    if "personalInfo" in result and isinstance(result["personalInfo"], dict):
        return result["personalInfo"]
    return result


async def _extract_summary(block: str, max_tokens: int) -> str:
    if not block.strip():
        return ""
    prompt = SUMMARY_PROMPT.format(block=block)
    result = await _extract(prompt, "summary", max_tokens)
    val = result.get("summary", "")
    return val if isinstance(val, str) else ""


async def _extract_experience(block: str, max_tokens: int) -> list[dict[str, Any]]:
    if not block.strip():
        return []
    prompt = EXPERIENCE_PROMPT.format(block=block)
    result = await _extract(prompt, "workExperience", max_tokens)
    val = result.get("workExperience", [])
    return val if isinstance(val, list) else []


async def _extract_education(block: str, max_tokens: int) -> list[dict[str, Any]]:
    if not block.strip():
        return []
    prompt = EDUCATION_PROMPT.format(block=block)
    result = await _extract(prompt, "education", max_tokens)
    val = result.get("education", [])
    return val if isinstance(val, list) else []


async def _extract_projects(block: str, max_tokens: int) -> list[dict[str, Any]]:
    """Projects share the same shape as workExperience for our purposes."""
    if not block.strip():
        return []
    # Reuse the experience prompt with a swap so the LLM understands it's
    # projects — the shape is identical.
    prompt = EXPERIENCE_PROMPT.replace("workExperience", "personalProjects").format(block=block)
    result = await _extract(prompt, "personalProjects", max_tokens)
    val = result.get("personalProjects", result.get("workExperience", []))
    return val if isinstance(val, list) else []


async def _extract_skills(block: str, max_tokens: int) -> list[str]:
    if not block.strip():
        return []
    prompt = SKILLS_PROMPT.format(block=block)
    result = await _extract(prompt, "technicalSkills", max_tokens)
    val = result.get("technicalSkills", [])
    if not isinstance(val, list):
        return []
    return [s for s in val if isinstance(s, str) and s.strip()]


async def _extract_flat_list(
    block: str, field: str, label: str, max_tokens: int
) -> list[str]:
    if not block.strip():
        return []
    prompt = FLAT_LIST_PROMPT.format(field=field, label=label, block=block)
    result = await _extract(prompt, field, max_tokens)
    val = result.get(field, [])
    if not isinstance(val, list):
        return []
    return [s for s in val if isinstance(s, str) and s.strip()]


async def _extract_custom_section(
    block: str, heading: str, max_tokens: int
) -> dict[str, Any] | None:
    if not block.strip():
        return None
    prompt = CUSTOM_SECTION_PROMPT.format(block=block, heading=heading)
    result = await _extract(prompt, f"custom:{heading}", max_tokens)
    if not isinstance(result, dict) or "sectionType" not in result:
        return None
    return result


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


def _slugify_heading(heading: str) -> str:
    """Turn "Volunteer Work" into "volunteer_work" for use as a customSections
    key."""
    slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    return slug or "section"


async def parse_multi_pass(markdown_text: str) -> dict[str, Any]:
    """Parse a resume in multiple focused passes.

    Returns a dict shaped like ResumeData. Missing sections are filled with
    schema defaults (empty strings / lists / dicts) so the outer validator
    stays happy.
    """
    if not markdown_text or not markdown_text.strip():
        raise ValueError("Resume content is empty after text extraction.")

    sections = split_into_sections(markdown_text)
    logger.info(
        "multi_pass: detected sections: %s", list(sections.keys())
    )

    config = get_llm_config()
    model_name = get_model_name(config)
    # Each focused pass is much smaller than a full-doc parse, so a modest
    # per-call budget is plenty. Keeping this small also helps the model stay
    # focused on its one job.
    per_call_tokens = min(2048, get_safe_max_tokens(model_name))

    # Kick off every focused pass in parallel. asyncio.gather waits for the
    # slowest — usually workExperience — while everything else finishes early.
    coros = {
        "personalInfo": _extract_personal_info(
            sections.get("header", ""), per_call_tokens
        ),
        "summary": _extract_summary(sections.get("summary", ""), per_call_tokens),
        "workExperience": _extract_experience(
            sections.get("experience", ""), per_call_tokens
        ),
        "education": _extract_education(
            sections.get("education", ""), per_call_tokens
        ),
        "personalProjects": _extract_projects(
            sections.get("projects", ""), per_call_tokens
        ),
        "technicalSkills": _extract_skills(
            sections.get("skills", ""), per_call_tokens
        ),
        "languages": _extract_flat_list(
            sections.get("languages", ""), "languages", "Languages", per_call_tokens
        ),
        "certificationsTraining": _extract_flat_list(
            sections.get("certifications", ""),
            "certificationsTraining",
            "Certifications",
            per_call_tokens,
        ),
        "awards": _extract_flat_list(
            sections.get("awards", ""), "awards", "Awards", per_call_tokens
        ),
    }

    # Custom sections — one call per unrecognized heading, plus canonical
    # publications / research / volunteer that we DO want kept as custom
    # sections (they render as itemList in the templates and have their own
    # structure).
    custom_coros: dict[str, Any] = {}
    for kind, block in sections.items():
        if kind == "research" and block.strip():
            custom_coros["research_experience"] = _extract_custom_section(
                block, "Research Experience", per_call_tokens
            )
        if kind == "publications" and block.strip():
            custom_coros["publications"] = _extract_custom_section(
                block, "Publications", per_call_tokens
            )
        if kind == "volunteer" and block.strip():
            custom_coros["volunteer_work"] = _extract_custom_section(
                block, "Volunteer Work", per_call_tokens
            )
        if kind == "interests" and block.strip():
            custom_coros["interests"] = _extract_custom_section(
                block, "Interests", per_call_tokens
            )
        if kind.startswith("other:"):
            heading = kind.split(":", 1)[1].title()
            custom_coros[_slugify_heading(heading)] = _extract_custom_section(
                block, heading, per_call_tokens
            )

    # await all — main sections and customs in the same batch to keep
    # wall-clock latency dominated by the slowest single call.
    results = await asyncio.gather(*coros.values(), *custom_coros.values())
    main_results = dict(zip(coros.keys(), results[: len(coros)]))
    custom_results = dict(zip(custom_coros.keys(), results[len(coros) :]))

    parsed: dict[str, Any] = {
        "personalInfo": main_results.get("personalInfo") or {},
        "summary": main_results.get("summary") or "",
        "workExperience": main_results.get("workExperience") or [],
        "education": main_results.get("education") or [],
        "personalProjects": main_results.get("personalProjects") or [],
        "additional": {
            "technicalSkills": main_results.get("technicalSkills") or [],
            "languages": main_results.get("languages") or [],
            "certificationsTraining": main_results.get("certificationsTraining") or [],
            "awards": main_results.get("awards") or [],
        },
        "customSections": {
            key: val for key, val in custom_results.items() if val is not None
        },
    }

    logger.info(
        "multi_pass: extracted "
        "%d work / %d edu / %d proj / %d skill groups / %d langs / %d certs / "
        "%d awards / %d custom",
        len(parsed["workExperience"]),
        len(parsed["education"]),
        len(parsed["personalProjects"]),
        len(parsed["additional"]["technicalSkills"]),
        len(parsed["additional"]["languages"]),
        len(parsed["additional"]["certificationsTraining"]),
        len(parsed["additional"]["awards"]),
        len(parsed["customSections"]),
    )

    return parsed
