"""Cover letter, outreach message, and resume title generation service."""

import json
import logging
import re
from typing import Any

from app.config import load_config_file
from app.llm import complete
from app.services.panel import complete_with_panel
from app.prompts.templates import (
    COVER_LETTER_CRITIQUE_REFINE_PROMPT,
    COVER_LETTER_PROMPT,
    GENERATE_TITLE_PROMPT,
    OUTREACH_MESSAGE_PROMPT,
)
from app.prompts import get_language_name

_BAD_OPENING_RE = re.compile(
    r"^\s*(?:as\s+the\s+global\s+market\s+leader|as\s+a\s+global\s+leader|in\s+today['’]?s\s+fast|in\s+an\s+era\s+where|with\s+the\s+rapid\s+evolution)",
    re.IGNORECASE,
)


def _needs_storyline_refinement(draft: str) -> bool:
    """Check whether a cover letter draft needs a second storyline refinement pass."""
    if not draft or not draft.strip():
        return False
    lower = draft.lower()
    # 1. Check if header has outdated 2024/2025 year
    if ".2024" in draft or " 2024" in draft[:250]:
        return True
    # 2. Check if first body paragraph starts with a robotic corporate summary
    lines = [line.strip() for line in draft.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line.lower().startswith(("dear ", "sehr geehrte")):
            if idx + 1 < len(lines) and _BAD_OPENING_RE.search(lines[idx + 1]):
                return True
            break
    # 3. Check if closing invites an initial discussion / conversation
    has_discussion_cta = any(
        phrase in lower
        for phrase in (
            "initial discussion",
            "initial conversation",
            "opportunity to discuss",
            "welcome the opportunity",
            "love the opportunity",
            "persönlichen gespräch",
            "kennenlerngespräch",
            "ersten austausch",
        )
    )
    if not has_discussion_cta:
        return True
    # 4. Check for em-dashes
    if "—" in draft:
        return True
    return False


def _resolve_feature_prompt(
    custom_key: str,
    default_template: str,
) -> tuple[str, bool]:
    """Resolve a feature-prompt template at runtime.

    Returns ``(template, is_custom)``. If the stored custom prompt is
    empty or absent, returns the default template. The ``is_custom`` flag
    lets callers decide whether to fall back to the default on a format
    failure (defensive — save-time validation should have caught a
    malformed custom prompt).
    """
    stored = load_config_file()
    custom = (stored.get(custom_key) or "").strip()
    if not custom:
        return default_template, False
    return custom, True


async def generate_cover_letter(
    resume_data: dict[str, Any],
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a cover letter based on resume and job description.

    Args:
        resume_data: Structured resume data (ResumeData format)
        job_description: Target job description text
        language: Output language code (en, es, zh, ja)

    Returns:
        Generated cover letter as plain text
    """
    output_language = get_language_name(language)

    template, is_custom = _resolve_feature_prompt(
        "cover_letter_prompt", COVER_LETTER_PROMPT
    )
    try:
        prompt = template.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )
    except (KeyError, IndexError, ValueError) as e:
        # str.format() raises KeyError for unknown placeholders, IndexError for
        # positional out-of-range, and ValueError for unmatched/invalid braces
        # (e.g., ``{foo``). If the failing template is the built-in default,
        # something is broken upstream and the caller should see it — re-raise.
        # If it's a user-supplied custom prompt, fall back to the default with a
        # warning so generation doesn't crash on out-of-band disk edits.
        if not is_custom:
            raise
        logging.warning(
            "Custom cover letter prompt failed to format (%s); falling back to default",
            e,
        )
        prompt = COVER_LETTER_PROMPT.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )

    result = await complete_with_panel(
        prompt=prompt,
        system_prompt="You are a professional career coach and resume writer. Write compelling, personalized cover letters.",
        max_tokens=2048,
        merge_instruction=(
            "Merge the cover-letter drafts below into ONE final letter that keeps the "
            "most specific, verifiable claims and drops generic filler. Match the voice "
            "of the resume. Output the final letter only — no preamble, no commentary."
        ),
    )

    draft = result.strip()

    # Closed-loop storyline refinement: if the draft uses a bad corporate-lecture
    # opening, an outdated 2024 date, em-dashes, or misses the initial-discussion
    # call to action, run a targeted editorial refinement pass.
    if not is_custom and _needs_storyline_refinement(draft):
        try:
            refine_prompt = COVER_LETTER_CRITIQUE_REFINE_PROMPT.format(
                job_description=job_description,
                resume_data=json.dumps(resume_data),
                draft_cover_letter=draft,
                output_language=output_language,
            )
            refined = await complete(
                prompt=refine_prompt,
                system_prompt="You are an executive hiring manager and editorial coach refining a cover letter for storyline, tone, and standard professional structure.",
                max_tokens=2048,
                temperature=0.3,
            )
            if refined and len(refined.strip()) > 150:
                draft = refined.strip()
        except Exception as e:
            logging.warning("Cover letter storyline refinement pass skipped: %s", e)

    # Final deterministic cleanup: strip any stray em-dashes
    draft = draft.replace(" — ", ", ").replace("—", ", ")
    return draft


async def generate_outreach_message(
    resume_data: dict[str, Any],
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a cold outreach message for networking.

    Args:
        resume_data: Structured resume data (ResumeData format)
        job_description: Target job description text
        language: Output language code (en, es, zh, ja)

    Returns:
        Generated outreach message as plain text
    """
    output_language = get_language_name(language)

    template, is_custom = _resolve_feature_prompt(
        "outreach_message_prompt", OUTREACH_MESSAGE_PROMPT
    )
    try:
        prompt = template.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )
    except (KeyError, IndexError, ValueError) as e:
        # See generate_cover_letter for rationale on the exception set.
        if not is_custom:
            raise
        logging.warning(
            "Custom outreach message prompt failed to format (%s); falling back to default",
            e,
        )
        prompt = OUTREACH_MESSAGE_PROMPT.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )

    result = await complete_with_panel(
        prompt=prompt,
        system_prompt="You are a professional networking coach. Write genuine, engaging cold outreach messages.",
        max_tokens=1024,
        merge_instruction=(
            "Merge the outreach drafts below into ONE final message. Keep the most "
            "specific hooks and the clearest ask; drop clichés. Output the final "
            "message only — no commentary."
        ),
    )

    return result.strip()


async def generate_resume_title(
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a short descriptive title from a job description.

    Args:
        job_description: Target job description text
        language: Output language code (en, es, zh, ja)

    Returns:
        Generated title like "Senior Frontend Engineer @ Stripe"
    """
    output_language = get_language_name(language)

    prompt = GENERATE_TITLE_PROMPT.format(
        job_description=job_description,
        output_language=output_language,
    )

    result = await complete(
        prompt=prompt,
        system_prompt="You extract job titles and company names from job descriptions.",
        max_tokens=60,
        temperature=0.3,
    )

    # Strip quotes and whitespace, truncate to 80 chars
    title = result.strip().strip("\"'")
    return title[:80]
