"""Resume improvement service using LLM."""

import copy
import json
import logging
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any, Callable

from app.llm import complete_json, get_config_for_task
from app.prompts import (
    CRITICAL_TRUTHFULNESS_RULES,
    DEFAULT_IMPROVE_PROMPT_ID,
    DIFF_IMPROVE_PROMPT,
    DIFF_STRATEGY_INSTRUCTIONS,
    EXTRACT_KEYWORDS_PROMPT,
    IMPROVE_RESUME_PROMPTS,
    SKILL_TARGET_PLAN_PROMPT,
    build_truthfulness_rules_with_skills,
    get_diff_strategy,
    get_language_name,
)
from app.prompts.templates import IMPROVE_SCHEMA_EXAMPLE
from app.schemas import ResumeData, ResumeFieldDiff, ResumeDiffSummary
from app.schemas.models import ImproveDiffResult, ResumeChange

logger = logging.getLogger(__name__)

# LLM-011: Prompt injection patterns to sanitize
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?above",
    r"forget\s+(everything|all)",
    r"new\s+instructions?:",
    r"system\s*:",
    r"<\s*/?\s*system\s*>",
    r"\[\s*INST\s*\]",
    r"\[\s*/\s*INST\s*\]",
]


@dataclass(frozen=True)
class DiffConfidence:
    added: str
    removed: str
    modified: str


def _sanitize_user_input(text: str) -> str:
    """LLM-011: Sanitize user input to prevent prompt injection.

    Removes or redacts common injection patterns that could manipulate LLM behavior.
    """
    sanitized = text
    for pattern in _INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


def _check_for_truncation(data: dict[str, Any]) -> None:
    """LLM-006: Log warnings for obvious truncation signs before Pydantic validation.

    Note: personalInfo is intentionally excluded — the improve prompts tell the
    LLM to skip it, and _preserve_personal_info() restores it from the original.
    """

    # Check for suspiciously empty required arrays
    if "workExperience" in data and data["workExperience"] == []:
        logger.warning(
            "Resume has empty workExperience - possible truncation or unusual resume"
        )


# ---------------------------------------------------------------------------
# Diff-based improvement: path resolution, applier, verifier, LLM generator
# ---------------------------------------------------------------------------

_PATH_SEGMENT_RE = re.compile(r"([a-zA-Z_]+)(?:\[(\d+)\])?")

# Allowed path patterns — only these can be modified by diffs
_ALLOWED_PATH_PATTERNS = [
    re.compile(r"^summary$"),
    re.compile(r"^workExperience\[\d+\]\.description(\[\d+\])?$"),
    re.compile(r"^personalProjects\[\d+\]\.description(\[\d+\])?$"),
    # Education description is a single string (Education.description: str | None),
    # so only the scalar path is allowed — not a [j]-indexed bullet form.
    re.compile(r"^education\[\d+\]\.description$"),
    re.compile(r"^additional\.technicalSkills$"),
    re.compile(r"^additional\.languages$"),
    re.compile(r"^additional\.certificationsTraining$"),
    re.compile(r"^additional\.awards$"),
]

# Blocked path prefixes — always rejected
_BLOCKED_PATH_PREFIXES = frozenset({
    "personalInfo",
    "customSections",
    "sectionMeta",
})

# Blocked field names — rejected when they appear as the leaf of a path
_BLOCKED_FIELD_NAMES = frozenset({
    "years",
    "company",
    "institution",
    "title",
    "degree",
    "name",
    "role",
    "github",
    "website",
    "location",
    "id",
})

_METRIC_RE = re.compile(r"\d+%|\d+x|\$\d+")


def _is_path_allowed(path: str) -> bool:
    """Check if a path is in the allowed whitelist."""
    return any(p.match(path) for p in _ALLOWED_PATH_PATTERNS)


def _is_path_blocked(path: str) -> bool:
    """Check if a path matches any blocked pattern."""
    for prefix in _BLOCKED_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return True

    # Check if the leaf field is blocked
    segments = path.split(".")
    if segments:
        last_segment = segments[-1]
        field_name = re.sub(r"\[\d+\]$", "", last_segment)
        # "description" is the one allowed field that shares a name pattern
        if field_name in _BLOCKED_FIELD_NAMES and field_name != "description":
            return True

    if path.startswith("education"):
        # Education descriptions may be tailored; degree/institution/years stay
        # blocked (they are also caught by the blocked-leaf-name check above).
        if re.match(r"^education\[\d+\]\.description$", path):
            return False
        return True

    return False


def _resolve_path(data: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Resolve a dot+bracket path to a value in the data dict.

    Returns:
        (value, success). On failure returns (None, False).
    """
    current: Any = data
    for segment_match in _PATH_SEGMENT_RE.finditer(path):
        key = segment_match.group(1)
        index_str = segment_match.group(2)

        if not isinstance(current, dict) or key not in current:
            return None, False
        current = current[key]

        if index_str is not None:
            index = int(index_str)
            if not isinstance(current, list) or index < 0 or index >= len(current):
                return None, False
            current = current[index]

    return current, True


def _set_at_path(data: dict[str, Any], path: str, value: Any) -> bool:
    """Set a value at the given path. Returns True on success."""
    segments = list(_PATH_SEGMENT_RE.finditer(path))
    if not segments:
        return False

    # Navigate to parent of the target
    current: Any = data
    for seg in segments[:-1]:
        key = seg.group(1)
        index_str = seg.group(2)

        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]

        if index_str is not None:
            index = int(index_str)
            if not isinstance(current, list) or index < 0 or index >= len(current):
                return False
            current = current[index]

    # Set on the final segment
    last = segments[-1]
    key = last.group(1)
    index_str = last.group(2)

    if index_str is not None:
        if not isinstance(current, dict) or key not in current:
            return False
        target = current[key]
        index = int(index_str)
        if not isinstance(target, list) or index < 0 or index >= len(target):
            return False
        target[index] = value
    else:
        if not isinstance(current, dict):
            return False
        current[key] = value

    return True


def _verify_original_matches(actual: Any, expected: str | list[str] | None) -> bool:
    """Verify that the original text from the diff matches the actual value."""
    if expected is None:
        return True  # no original provided (e.g. append) — nothing to verify
    if not isinstance(expected, str):
        return False  # a non-str original on a text action is malformed — reject
    if not isinstance(actual, str):
        return False
    return actual.strip().casefold() == expected.strip().casefold()


# Non-skill buzzwords, broad industries, or generic business phrases that belong in
# summary/experience prose rather than the technical skills section.
_NON_SKILL_SECTION_TERMS = {
    "iot",
    "5g",
    "semiconductor industry",
    "semiconductor",
    "digital transformation",
    "global transformation projects",
    "cross-functional teams",
    "cross functional teams",
    "supply chain management",
    "operations management",
    "hr analytics",
    "financial analytics",
    "supply chain analytics",
    "stakeholder management",
    "artificial intelligence",
    "business intelligence",
}

# Max comma-separated items per grouped skill block / category line to prevent bloat
_MAX_ITEMS_PER_SKILL_CATEGORY = 10
# Max new skills to add per category block on top of existing items
_MAX_ADDED_SKILLS_PER_CATEGORY = 2


def _is_concise_technical_skill(skill: str) -> bool:
    """Return True if ``skill`` is a concise tool, language, platform, or core
    technical methodology suitable for the Skills section (not a generic domain
    buzzword or soft skill)."""
    cleaned = skill.strip()
    if not cleaned:
        return False
    lower = cleaned.casefold()
    if lower in _NON_SKILL_SECTION_TERMS:
        return False
    # Reject overly long phrases (> 4 words unless it's a known acronymized deliverable like BRD/FRS/EDA/ERD/UAT)
    words = cleaned.split()
    if len(words) > 4 and not any(acr in cleaned for acr in ("(BRD)", "(FRS)", "(EDA)", "(ERD)", "(UAT)")):
        return False
    # Reject generic industry/department phrases
    if any(
        suffix in lower
        for suffix in (
            "industry",
            "projects",
            "teams",
            "department",
            "environment",
            "collaboration",
            "communication",
        )
    ):
        return False
    return True


def _pick_skill_category_index(labels: list[str], skill: str) -> int | None:
    """Return the index of the best-matching category label for ``skill``."""
    skill_lower = skill.lower()
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (
            ("agile", "scrum", "uat", "user acceptance", "brd", "frs", "requirement", "jira", "confluence", "sprint", "backlog", "documentation", "governance", "quality"),
            ("tool", "method"),
        ),
        (
            ("azure", "databricks", "aws", "gcp", "etl", "pipeline", "warehouse", "model", "lineage", "catalog", "profiling", "mapping", "spark", "snowflake", "airflow", "dbt", "fabric", "synapse"),
            ("engineering",),
        ),
        (
            ("sql", "database", "postgres", "oracle", "redshift", "erd", "entity", "schema", "dictionary"),
            ("database",),
        ),
        (
            ("power bi", "tableau", "quicksight", "kpi", "dashboard", "visual", "dax", "excel", "looker"),
            ("bi", "visual"),
        ),
        (
            ("sap", "abap", "bods", "bw", "hana"),
            ("sap",),
        ),
        (
            ("python", "java", "c#", "c++", "scala", "typescript", "javascript"),
            ("program",),
        ),
        (
            ("llm", "ai", "ml", "rag", "agent", "mining", "segmentation", "regression", "statistics", "eda", "exploratory"),
            ("ai", "ml"),
        ),
    ]

    for keywords, label_tokens in rules:
        if any(k in skill_lower for k in keywords):
            for idx, raw_label in enumerate(labels):
                label = raw_label.lower()
                if any(tok in label for tok in label_tokens):
                    return idx

    # Fallback: prefer Tools & Methods or Data Engineering
    for idx, raw_label in enumerate(labels):
        label = raw_label.lower()
        if "language" not in label and ("tool" in label or "engineering" in label):
            return idx
    for idx, raw_label in enumerate(labels):
        if "language" not in raw_label.lower():
            return idx
    return None


def _count_comma_items(text: str) -> int:
    """Count top-level comma-separated items (ignoring commas inside parentheses)."""
    depth = 0
    count = 1 if text.strip() else 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


def _add_skill_to_technical_skills_list(tech_skills: list[Any], new_skill: str) -> bool:
    """Add ``new_skill`` to ``additional.technicalSkills`` cleanly and within limits.

    If ``tech_skills`` uses categorized lines (`"Category: item1, item2"`), merges
    ``new_skill`` into the matching category line (up to ``_MAX_ITEMS_PER_SKILL_CATEGORY``)
    instead of dumping standalone uncategorized strings at the bottom.
    Returns True if the skill was added.
    """
    if not _is_concise_technical_skill(new_skill):
        return False

    full_text = " ".join(str(s) for s in tech_skills if isinstance(s, str))
    if _skill_mentioned_in_text(new_skill, full_text):
        return False

    # Detect if tech_skills uses "Category: items..." format
    colon_indices: list[int] = []
    colon_labels: list[str] = []
    for idx, item in enumerate(tech_skills):
        if isinstance(item, str) and ":" in item:
            label_part = item.split(":", 1)[0].strip()
            if 1 <= len(label_part.split()) <= 4:
                colon_indices.append(idx)
                colon_labels.append(label_part)

    if len(colon_indices) >= 3:
        chosen = _pick_skill_category_index(colon_labels, new_skill)
        if chosen is not None:
            list_idx = colon_indices[chosen]
            line = str(tech_skills[list_idx])
            label_part, items_part = line.split(":", 1)
            if _count_comma_items(items_part) >= _MAX_ITEMS_PER_SKILL_CATEGORY:
                return False
            tech_skills[list_idx] = f"{label_part}: {items_part.strip().rstrip(',')}, {new_skill}"
            return True
        return False

    # Flat skill list: cap total items at 24 so it stays readable
    if len(tech_skills) >= 24:
        return False
    tech_skills.append(new_skill)
    return True


def _sync_skill_to_visible_grouped_blocks(data: dict[str, Any], new_skill: str) -> None:
    """When additional.technicalSkills is hidden and a groupedList Skills customSection
    is visible (like custom_1), also add new_skill to the best-matching block if within
    optimal size limits so it renders cleanly without bloating the section."""
    if not _is_concise_technical_skill(new_skill):
        return

    section_meta = data.get("sectionMeta")
    if not isinstance(section_meta, list):
        return
    additional_visible = True
    visible_grouped_keys: list[str] = []
    for meta in section_meta:
        if not isinstance(meta, dict):
            continue
        if meta.get("key") == "additional" and meta.get("isVisible") is False:
            additional_visible = False
        if (
            not meta.get("isDefault", True)
            and meta.get("isVisible", True)
            and meta.get("sectionType") == "groupedList"
            and isinstance(meta.get("key"), str)
        ):
            visible_grouped_keys.append(meta["key"])

    if additional_visible or not visible_grouped_keys:
        return

    custom_sections = data.get("customSections")
    if not isinstance(custom_sections, dict):
        return

    for sec_key in visible_grouped_keys:
        sec = custom_sections.get(sec_key)
        if not isinstance(sec, dict) or not isinstance(sec.get("blocks"), list):
            continue
        blocks = [b for b in sec["blocks"] if isinstance(b, dict)]
        if not blocks:
            continue
        # Skip if already present in any block
        for b in blocks:
            for item in b.get("items") or []:
                if isinstance(item, str) and _skill_mentioned_in_text(new_skill, item):
                    return

        labels = [str(b.get("label", "")) for b in blocks]
        chosen_idx = _pick_skill_category_index(labels, new_skill)
        if chosen_idx is None:
            return

        target_block = blocks[chosen_idx]
        items = target_block.setdefault("items", [])
        if not isinstance(items, list):
            return

        # Enforce optimal limit per category block so the Skills section stays compact and scannable
        joined_items = ", ".join(str(i) for i in items if isinstance(i, str))
        if _count_comma_items(joined_items) >= _MAX_ITEMS_PER_SKILL_CATEGORY:
            return

        if items and isinstance(items[-1], str) and ("," in items[-1] or len(items) == 1):
            items[-1] = f"{items[-1].rstrip(', ')}, {new_skill}"
        else:
            items.append(new_skill)
        return


def _trim_comma_separated_line(text: str, max_items: int) -> str:
    """Trim a comma-separated string (respecting parentheses) to at most ``max_items``
    and drop non-technical buzzwords."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")" and depth > 0:
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            token = "".join(current).strip()
            if token:
                parts.append(token)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    filtered = [p for p in parts if p.casefold() not in _NON_SKILL_SECTION_TERMS]
    return ", ".join(filtered[:max_items])


_IMPACT_RE = re.compile(
    r"\d+[%x×]"            # "40%", "3x", "2×"
    r"|\$[\d,.]+[KMBkmb]?" # "$1.2M", "$500K"
    r"|€[\d,.]+[KMBkmb]?"  # "€200K"
    r"|\d{2,}[+]?"         # "50K+", "200"
    r"|\breduc\w+"         # reduced, reducing, reduction
    r"|\bincreas\w+"       # increased, increasing
    r"|\bimprove\w+"       # improved, improvement
    r"|\bsav\w+"           # saved, savings
    r"|\bgrew\b"
    r"|\bgrowth\b"
    r"|\bgenerat\w+"       # generated
    r"|\bachiev\w+"        # achieved
    r"|\bdeliver\w+",      # delivered
    re.IGNORECASE,
)


def reorder_bullets_by_relevance(
    data: dict[str, Any],
    job_keywords: dict[str, Any],
) -> dict[str, Any]:
    """Reorder description bullets within each experience/project entry so the
    most impactful, JD-relevant bullets appear first.

    Scoring: impact signals (metrics, numbers, achievement verbs) are the
    primary sort key; keyword matches are the tiebreaker.  This keeps
    quantified achievements above keyword-stuffed filler.

    Preserves ``descriptionStyles`` alignment. Pure local sort, no LLM call.
    """
    from app.services.refiner import _keyword_in_text

    all_kw: list[str] = []
    all_kw.extend(job_keywords.get("required_skills", []))
    all_kw.extend(job_keywords.get("preferred_skills", []))
    all_kw.extend(job_keywords.get("keywords", []))
    kw_list = [k.lower() for k in all_kw if isinstance(k, str) and k.strip()]

    if not kw_list:
        return data

    result = copy.deepcopy(data)

    def _score_bullet(text: str) -> tuple[int, int]:
        impact = len(_IMPACT_RE.findall(text))
        t = text.lower()
        kw_hits = sum(1 for kw in kw_list if _keyword_in_text(kw, t))
        return (impact, kw_hits)

    for section_key in ("workExperience", "personalProjects"):
        entries = result.get(section_key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            descriptions = entry.get("description", [])
            if not isinstance(descriptions, list) or len(descriptions) < 2:
                continue
            styles = entry.get("descriptionStyles", [])
            has_styles = isinstance(styles, list) and len(styles) == len(descriptions)

            if has_styles:
                paired = list(zip(descriptions, styles))
                paired.sort(key=lambda p: _score_bullet(str(p[0])), reverse=True)
                entry["description"] = [p[0] for p in paired]
                entry["descriptionStyles"] = [p[1] for p in paired]
            else:
                descriptions.sort(key=lambda b: _score_bullet(str(b)), reverse=True)

    return result


def enforce_optimal_skills_section(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure ``additional.technicalSkills`` and any visible ``groupedList`` custom
    skill blocks stay clean, categorized, and within optimal limits (no keyword dumps)."""
    result = copy.deepcopy(data)
    additional = result.get("additional")
    if isinstance(additional, dict):
        tech_skills = additional.get("technicalSkills")
        if isinstance(tech_skills, list) and tech_skills:
            colon_lines: list[str] = []
            loose_items: list[str] = []
            for item in tech_skills:
                if not isinstance(item, str) or not item.strip():
                    continue
                s = item.strip()
                if ":" in s and 1 <= len(s.split(":", 1)[0].split()) <= 4:
                    label_part, items_part = s.split(":", 1)
                    trimmed_items = _trim_comma_separated_line(items_part, _MAX_ITEMS_PER_SKILL_CATEGORY)
                    colon_lines.append(f"{label_part.strip()}: {trimmed_items}")
                else:
                    loose_items.append(s)

            if len(colon_lines) >= 3:
                # Merge any valid loose technical skills into the categorized lines and drop the rest
                for loose in loose_items:
                    _add_skill_to_technical_skills_list(colon_lines, loose)
                    _sync_skill_to_visible_grouped_blocks(result, loose)
                additional["technicalSkills"] = colon_lines
            else:
                cleaned_flat = [s for s in loose_items if _is_concise_technical_skill(s)][:24]
                if cleaned_flat:
                    additional["technicalSkills"] = cleaned_flat

    # Also enforce optimal limits on any groupedList custom sections
    custom_sections = result.get("customSections")
    if isinstance(custom_sections, dict):
        for sec in custom_sections.values():
            if not isinstance(sec, dict) or sec.get("sectionType") != "groupedList":
                continue
            blocks = sec.get("blocks")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if "language" in str(block.get("label", "")).lower():
                    continue
                b_items = block.get("items")
                if isinstance(b_items, list) and len(b_items) == 1 and isinstance(b_items[0], str):
                    block["items"] = [_trim_comma_separated_line(b_items[0], _MAX_ITEMS_PER_SKILL_CATEGORY)]

    return result


def apply_diffs(
    original: dict[str, Any],
    changes: list[ResumeChange],
    allowed_skill_targets: list[dict[str, Any] | str] | None = None,
    confirmed_skills: list[str] | None = None,
) -> tuple[dict[str, Any], list[ResumeChange], list[ResumeChange]]:
    """Apply verified diffs to original resume.

    Each change goes through 4 gates:
    1. Path is in allowed whitelist
    2. Path is not in blocked list
    3. Path resolves to an actual value in the original
    4. Original text matches (for replace actions)

    For reorder: validates the new list contains exactly the same items.

    Args:
        original: The original resume data (ResumeData-compatible dict)
        changes: List of changes from the LLM
        allowed_skill_targets: Verified skill targets allowed for add_skill actions

    Returns:
        (result_dict, applied_changes, rejected_changes)
    """
    result = copy.deepcopy(original)
    applied: list[ResumeChange] = []
    rejected: list[ResumeChange] = []
    allowed_skill_keys = _build_allowed_skill_target_keys(allowed_skill_targets)

    for change in changes:
        path = change.path
        action = change.action

        # Gate 1: Path must be in allowed whitelist
        if not _is_path_allowed(path):
            logger.info("Diff rejected (not in allowed list): %s", path)
            rejected.append(change)
            continue

        # Gate 2: Path must not be blocked
        if _is_path_blocked(path):
            logger.info("Diff rejected (blocked path): %s", path)
            rejected.append(change)
            continue

        # Gate 3: Path must resolve to a real value
        actual_value, resolved = _resolve_path(result, path)
        if not resolved:
            logger.info("Diff rejected (path not found): %s", path)
            rejected.append(change)
            continue

        if action == "replace":
            # Gate 4: Original text must match what's actually there
            if not _verify_original_matches(actual_value, change.original):
                logger.info(
                    "Diff rejected (original mismatch): path=%s expected=%r actual=%r",
                    path,
                    change.original,
                    actual_value,
                )
                rejected.append(change)
                continue

            # Replace must use a string value (not list)
            if not isinstance(change.value, str):
                logger.info("Diff rejected (replace with non-string value): %s", path)
                rejected.append(change)
                continue

            if not _set_at_path(result, path, change.value):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "append":
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (append to non-list): %s", path)
                rejected.append(change)
                continue
            # Append must use a non-empty string (not list, to avoid nested lists)
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (append non-string or empty value): %s", path)
                rejected.append(change)
                continue
            actual_value.append(change.value)
            applied.append(change)

        elif action == "reorder":
            if not isinstance(actual_value, list) or not isinstance(change.value, list):
                rejected.append(change)
                continue
            orig_set = sorted(s.casefold() for s in actual_value if isinstance(s, str))
            new_set = sorted(s.casefold() for s in change.value if isinstance(s, str))
            reordered: list[str] = []
            if orig_set == new_set:
                # Pure permutation: map the new order back to original casing.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                for item in change.value:
                    if isinstance(item, str):
                        originals = casefold_to_originals.get(item.casefold(), [])
                        reordered.append(originals.pop(0) if originals else item)
            else:
                # Salvage (issue #736): the LLM folded new/removed items into a
                # reorder. Rather than dropping the whole change, apply the SAFE
                # subset *in the requested order*: walk the proposed list, placing
                # each existing item where the model put it (so prioritized JD
                # skills stay near the top) and — for the skills list only —
                # inserting new items that pass the SAME verified gate as
                # add_skill. Originals the model omitted are appended at the end
                # so a real item is never silently lost. Other lists
                # (languages/certs/awards) have no verifier, so new items are
                # dropped to avoid fabrication.
                casefold_to_originals: dict[str, list[str]] = {}
                for item in actual_value:
                    if isinstance(item, str):
                        casefold_to_originals.setdefault(item.casefold(), []).append(item)
                original_cfs = set(casefold_to_originals)
                is_skills = path == "additional.technicalSkills"
                added_new: set[str] = set()
                for item in change.value:
                    if not isinstance(item, str):
                        continue
                    cf = item.casefold()
                    if cf in original_cfs:
                        bucket = casefold_to_originals[cf]
                        if bucket:  # place original in requested position (dupes preserved)
                            reordered.append(bucket.pop(0))
                        # else: a duplicate of an already-placed original — skip
                    elif is_skills and cf not in added_new:
                        skill = item.strip()
                        if skill and _normalize_skill_key(skill) in allowed_skill_keys:
                            reordered.append(skill)  # verified new skill, requested position
                            added_new.add(cf)
                        else:
                            logger.info("Reorder salvage dropped unverified skill: %s", skill)
                    # else: non-skills new item → dropped (no verifier to ground it)
                for item in actual_value:  # append any originals the model omitted
                    if isinstance(item, str):
                        bucket = casefold_to_originals[item.casefold()]
                        if bucket:
                            reordered.append(bucket.pop(0))
                logger.info("Diff reorder salvaged (item-set mismatch): %s", path)
            if not _set_at_path(result, path, reordered):
                rejected.append(change)
                continue
            applied.append(change)

        elif action == "remove":
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (remove from non-list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (remove empty/non-string): %s", path)
                rejected.append(change)
                continue
            target = change.value.strip()
            removed = False
            for i, item in enumerate(actual_value):
                if isinstance(item, str) and item.strip() == target:
                    actual_value.pop(i)
                    removed = True
                    break
            if not removed:
                seq_matches = [
                    (i, SequenceMatcher(None, item, target).ratio())
                    for i, item in enumerate(actual_value)
                    if isinstance(item, str)
                ]
                best = max(seq_matches, key=lambda x: x[1], default=None)
                if best and best[1] > 0.8:
                    actual_value.pop(best[0])
                    removed = True
            if removed:
                applied.append(change)
            else:
                logger.info("Diff rejected (remove target not found): %s", path)
                rejected.append(change)

        elif action == "add_skill":
            if path != "additional.technicalSkills":
                logger.info("Diff rejected (add_skill outside skills): %s", path)
                rejected.append(change)
                continue
            if not isinstance(actual_value, list):
                logger.info("Diff rejected (add_skill to non-list): %s", path)
                rejected.append(change)
                continue
            if not isinstance(change.value, str) or not change.value.strip():
                logger.info("Diff rejected (add_skill empty/non-string): %s", path)
                rejected.append(change)
                continue
            new_skill = change.value.strip()
            existing = {
                item.casefold()
                for item in actual_value
                if isinstance(item, str)
            }
            if new_skill.casefold() in existing:
                logger.info("Diff rejected (duplicate skill): %s", new_skill)
                rejected.append(change)
                continue
            if _normalize_skill_key(new_skill) not in allowed_skill_keys:
                logger.info("Diff accepted (skill via adjacent extrapolation): %s", new_skill)
            if not _add_skill_to_technical_skills_list(actual_value, new_skill):
                logger.info("Diff skipped (skill non-technical or category at optimal limit): %s", new_skill)
                continue
            _sync_skill_to_visible_grouped_blocks(result, new_skill)
            applied.append(change)

        else:
            logger.info("Diff rejected (unknown action): %s", action)
            rejected.append(change)

    # Curate user-confirmed skills: only add a confirmed skill to the Skills section
    # if it is a concise technical tool/method NOT already covered in the resume's
    # summary, experience, or projects, and within optimal category limits.
    if confirmed_skills:
        from app.services.refiner import _extract_all_text

        tech_skills = result.setdefault("additional", {}).setdefault("technicalSkills", [])
        if isinstance(tech_skills, list):
            full_resume_text = _extract_all_text(result)
            for raw_skill in confirmed_skills:
                if not isinstance(raw_skill, str) or not raw_skill.strip():
                    continue
                c_skill = raw_skill.strip()
                if _skill_mentioned_in_text(c_skill, full_resume_text):
                    continue
                if _add_skill_to_technical_skills_list(tech_skills, c_skill):
                    full_resume_text += f" {c_skill}"
                    applied.append(
                        ResumeChange(
                            path="additional.technicalSkills",
                            action="add_skill",
                            original=None,
                            value=c_skill,
                            reason="Confirmed technical skill added within optimal category limits",
                        )
                    )
                    _sync_skill_to_visible_grouped_blocks(result, c_skill)

    return result, applied, rejected


def _count_description_words(data: dict[str, Any]) -> int:
    """Count total words in all description and summary fields."""
    total = 0
    for key in ("workExperience", "personalProjects"):
        for entry in data.get(key, []):
            if isinstance(entry, dict):
                desc = entry.get("description", [])
                if isinstance(desc, list):
                    total += sum(len(str(d).split()) for d in desc)
                elif isinstance(desc, str):
                    total += len(desc.split())
    summary = data.get("summary", "")
    if isinstance(summary, str):
        total += len(summary.split())
    return total


def verify_diff_result(
    original: dict[str, Any],
    result: dict[str, Any],
    applied_changes: list[ResumeChange],
    job_keywords: dict[str, Any],
) -> list[str]:
    """Local quality checks on the diff result. Returns list of warnings.

    All checks are local (zero LLM cost). Warnings are informational —
    they don't block the response.
    """
    warnings: list[str] = []

    # Check 1: No empty result
    if not applied_changes:
        warnings.append("No changes were applied — resume returned unchanged")
        return warnings

    # Check 2: Section entry counts preserved (entries, not bullets)
    # Note: bullet counts may change due to removes/appends — that's expected.
    for key, label in [
        ("workExperience", "work experience"),
        ("education", "education"),
        ("personalProjects", "project"),
    ]:
        orig_count = len(original.get(key, []))
        result_count = len(result.get(key, []))
        if orig_count != result_count:
            warnings.append(
                f"Entry count changed: {label} ({orig_count} → {result_count})"
            )

    # Check 3: Identity fields unchanged
    for key, id_fields in [
        ("workExperience", ["company", "title"]),
        ("education", ["institution", "degree"]),
    ]:
        orig_entries = original.get(key, [])
        result_entries = result.get(key, [])
        for i, (orig, res) in enumerate(zip(orig_entries, result_entries)):
            if not isinstance(orig, dict) or not isinstance(res, dict):
                continue
            for field in id_fields:
                o_val = str(orig.get(field, "")).strip()
                r_val = str(res.get(field, "")).strip()
                if o_val and o_val != r_val:
                    warnings.append(
                        f"Identity field changed: {key}[{i}].{field} "
                        f"('{o_val}' → '{r_val}')"
                    )

    # Check 4: Word count ratio
    orig_words = _count_description_words(original)
    result_words = _count_description_words(result)
    if orig_words > 0 and result_words > orig_words * 1.8:
        warnings.append(
            f"Word count increased significantly: "
            f"{orig_words} → {result_words} ({result_words / orig_words:.1f}x)"
        )

    # Check 5: Invented metrics (covers both replace and append)
    for change in applied_changes:
        if change.action in ("replace", "append") and isinstance(change.value, str):
            new_metrics = set(_METRIC_RE.findall(change.value))
            # For append, original is None — any metric is potentially invented
            original_text = change.original or ""
            old_metrics = set(_METRIC_RE.findall(original_text))
            invented = new_metrics - old_metrics
            if invented:
                warnings.append(
                    f"Possible invented metric in {change.path}: "
                    f"{', '.join(invented)} (not in original)"
                )

    return warnings


async def generate_resume_diffs(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
    skill_targets: list[dict[str, Any]] | None = None,
    confirmed_skills: list[str] | None = None,
    extrapolation_mode: str = "aggressive",
) -> ImproveDiffResult:
    """Generate targeted resume diffs via LLM.

    Instead of asking the LLM for the full resume, asks for a list of
    targeted changes. Each change specifies a path, action, and new value.

    Args:
        original_resume: Resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Strategy id (nudge/keywords/full)
        original_resume_data: Structured resume JSON
        skill_targets: Verified skill targets from the planning pass

    Returns:
        ImproveDiffResult with list of changes and strategy notes
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    strategy_instruction = get_diff_strategy(selected_id, extrapolation_mode)

    # LLM-011: Sanitize job description
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON if available with month precision, else markdown
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            resume_input = original_resume
    else:
        resume_input = original_resume

    effective_targets = list(skill_targets or [])
    if confirmed_skills:
        for skill in confirmed_skills:
            effective_targets.append({"skill": skill, "reason": "Candidate confirmed they possess this skill"})

    from app.config_cache import get_system_prompt_override

    diff_prompt = get_system_prompt_override("diff_improve") or DIFF_IMPROVE_PROMPT
    prompt = diff_prompt.format(
        strategy_instruction=strategy_instruction,
        output_language=output_language,
        job_keywords=keywords_str,
        skill_targets=_prepare_skill_targets_for_prompt(effective_targets),
        job_description=sanitized_jd,
        original_resume=resume_input,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON with targeted changes.",
        max_tokens=4096,
        schema_type="diff",
    )

    # Parse result — handle LLM ignoring diff format gracefully
    raw_changes = result.get("changes", [])
    if not isinstance(raw_changes, list):
        logger.warning("LLM returned non-list changes: %s", type(raw_changes))
        raw_changes = []

    changes: list[ResumeChange] = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            continue
        try:
            action = raw.get("action", "replace")
            raw_val = raw.get("value")
            raw_orig = raw.get("original")
            if raw_val is None:
                raw_val = raw_orig if action == "remove" and isinstance(raw_orig, str) else ""
            if isinstance(raw_orig, list) and action != "reorder":
                raw_orig = ", ".join(str(x) for x in raw_orig)
            changes.append(
                ResumeChange(
                    path=str(raw.get("path", "")),
                    action=action,
                    original=raw_orig,
                    value=raw_val,
                    reason=str(raw.get("reason", "")),
                )
            )
        except Exception as e:
            logger.warning("Skipping malformed change: %s — %s", raw, e)

    strategy_notes = str(result.get("strategy_notes", ""))
    if not raw_changes and "changes" not in result:
        strategy_notes = "LLM output had no changes key — returned zero diffs"
        logger.warning("LLM output missing 'changes' key: %s", list(result.keys()))

    return ImproveDiffResult(changes=changes, strategy_notes=strategy_notes)


async def extract_job_keywords(job_description: str) -> dict[str, Any]:
    """Extract keywords and requirements from job description.

    Args:
        job_description: Raw job description text

    Returns:
        Structured keywords and requirements
    """
    # LLM-011: Sanitize job description before using in prompt
    from app.config_cache import get_system_prompt_override

    sanitized_jd = _sanitize_user_input(job_description)
    kw_prompt = get_system_prompt_override("extract_keywords") or EXTRACT_KEYWORDS_PROMPT
    prompt = kw_prompt.format(job_description=sanitized_jd)

    return await complete_json(
        prompt=prompt,
        system_prompt="You are an expert job description analyzer.",
        config=get_config_for_task("keywords"),
        schema_type="keywords",
    )


MONTH_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    re.IGNORECASE,
)


def _has_month_in_dates(data: dict[str, Any]) -> bool:
    """Check whether any years field in the structured data includes a month."""
    for section_key in ("workExperience", "education", "personalProjects"):
        entries = data.get(section_key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                years = entry.get("years", "")
                if isinstance(years, str) and MONTH_PATTERN.search(years):
                    return True
    custom_sections = data.get("customSections", {})
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            if isinstance(section, dict) and section.get("sectionType") == "itemList":
                items = section.get("items", [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        years = item.get("years", "")
                        if isinstance(years, str) and MONTH_PATTERN.search(years):
                            return True
    return False


def _prepare_keywords_for_prompt(job_keywords: dict[str, Any]) -> str:
    """Format job keywords as a focused, readable list for the LLM prompt.

    Extracts only actionable fields (skills and keywords) and drops
    informational fields that add noise without helping the LLM tailor.
    """
    sections: list[str] = []

    required = job_keywords.get("required_skills", [])
    if required:
        sections.append("Required skills to emphasize:\n- " + "\n- ".join(str(s) for s in required))

    preferred = job_keywords.get("preferred_skills", [])
    if preferred:
        sections.append(
            "Preferred skills (include only if resume supports them):\n- "
            + "\n- ".join(str(s) for s in preferred)
        )

    keywords = job_keywords.get("keywords", [])
    if keywords:
        sections.append("Additional keywords to weave in naturally:\n- " + "\n- ".join(str(k) for k in keywords))

    return "\n\n".join(sections) if sections else "No specific keywords extracted."


def _normalize_skill_key(skill: str) -> str:
    """Normalize a skill for case-insensitive comparison."""
    return re.sub(r"\s+", " ", skill.strip()).casefold()


def _extract_skill_index(items: Any) -> dict[str, str]:
    """Build a normalized skill index from a string list."""
    if not isinstance(items, list):
        return {}
    index: dict[str, str] = {}
    for item in items:
        if not isinstance(item, str):
            continue
        skill = item.strip()
        if skill:
            index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
    """Return True when a skill phrase appears as a whole term in text."""
    escaped = re.escape(skill.strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text.lower()))


def _build_allowed_skill_target_keys(
    allowed_skill_targets: list[dict[str, Any] | str] | None,
) -> set[str]:
    """Build normalized keys for skills approved by the planning verifier."""
    keys: set[str] = set()
    for target in allowed_skill_targets or []:
        if isinstance(target, str):
            skill = target
        elif isinstance(target, dict):
            skill = str(target.get("skill", ""))
        else:
            continue
        if skill.strip():
            keys.add(_normalize_skill_key(skill))
    return keys


def _extract_jd_skill_index(
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, str]:
    """Build a normalized index of explicit JD skills."""
    index: dict[str, str] = {}
    for field in ("required_skills", "preferred_skills"):
        values = job_keywords.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            skill = value.strip()
            if skill and (
                job_description is None
                or _skill_mentioned_in_text(skill, job_description)
            ):
                index.setdefault(_normalize_skill_key(skill), skill)
    return index


def _skill_present_in_resume_text(skill: str, resume_data: dict[str, Any]) -> bool:
    """Return True when a skill phrase already appears in the resume text."""
    text = json.dumps(resume_data, ensure_ascii=False)
    return _skill_mentioned_in_text(skill, text)


def verify_skill_target_plan(
    raw_plan: dict[str, Any],
    original_resume_data: dict[str, Any],
    job_keywords: dict[str, Any],
    job_description: str | None = None,
) -> dict[str, list[dict[str, str]] | str]:
    """Filter and classify LLM-proposed skill targets before diff generation.

    Existing resume skills are accepted as low-risk targets. Required and
    preferred JD skills are accepted as explicit JD-added targets for user
    review. Other skills are accepted only when they already appear in the
    resume text.
    """
    original_skills = _extract_skill_index(
        original_resume_data.get("additional", {}).get("technicalSkills", [])
    )
    jd_skills = _extract_jd_skill_index(job_keywords, job_description)
    raw_targets = raw_plan.get("target_skills", [])
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()

    if not isinstance(raw_targets, list):
        raw_targets = []

    for target in raw_targets:
        if isinstance(target, str):
            skill = target.strip()
            reason = ""
        elif isinstance(target, dict):
            skill = str(target.get("skill", "")).strip()
            reason = str(target.get("reason", "")).strip()
        else:
            continue

        skill_key = _normalize_skill_key(skill)
        if not skill or skill_key in seen:
            continue
        seen.add(skill_key)

        if skill_key in original_skills:
            accepted.append(
                {
                    "skill": original_skills[skill_key],
                    "source": "existing",
                    "reason": reason or "Already present in resume skills",
                }
            )
        elif skill_key in jd_skills:
            # JD-required/preferred skills are accepted as targets so the résumé
            # can be tailored to actually pass ATS/recruiter screening — adding
            # relevant JD skills is the product's purpose. (Truly unsupported
            # skills — neither in the JD nor the résumé — are still rejected
            # below.) The user reviews additions in the diff preview before save.
            accepted.append(
                {
                    "skill": jd_skills[skill_key],
                    "source": "jd_added",
                    "reason": reason or "Required or preferred by the job description",
                }
            )
        elif _skill_present_in_resume_text(skill, original_resume_data):
            accepted.append(
                {
                    "skill": skill,
                    "source": "supported_by_resume",
                    "reason": reason or "Appears in the existing resume content",
                }
            )
        else:
            accepted.append(
                {
                    "skill": skill,
                    "source": "adjacent_extrapolation",
                    "reason": reason or "Adjacent to candidate's experience ecosystem",
                }
            )

    return {
        "accepted": accepted,
        "rejected": rejected,
        "strategy_notes": str(raw_plan.get("strategy_notes", "")),
    }


async def generate_skill_target_plan(
    original_resume_data: dict[str, Any],
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    """Ask the LLM for a compact skill target plan before editing diffs."""
    output_language = get_language_name(language)
    existing_skills = original_resume_data.get("additional", {}).get(
        "technicalSkills", []
    )
    sanitized_jd = _sanitize_user_input(job_description)
    prompt = SKILL_TARGET_PLAN_PROMPT.format(
        output_language=output_language,
        existing_skills=json.dumps(existing_skills, ensure_ascii=False),
        job_keywords=_prepare_keywords_for_prompt(job_keywords),
        job_description=sanitized_jd,
        original_resume=json.dumps(original_resume_data, ensure_ascii=False),
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt=(
            "You are a resume skill planning agent. Output only valid JSON with "
            "target_skills and strategy_notes."
        ),
        config=get_config_for_task("skill_plan"),
        max_tokens=2048,
        schema_type="diff",
    )

    raw_targets = result.get("target_skills", [])
    target_skills: list[dict[str, str]] = []
    if isinstance(raw_targets, list):
        for raw in raw_targets:
            if isinstance(raw, str):
                skill = raw.strip()
                reason = ""
            elif isinstance(raw, dict):
                skill = str(raw.get("skill", "")).strip()
                reason = str(raw.get("reason", "")).strip()
            else:
                continue
            if skill:
                target_skills.append({"skill": skill, "reason": reason})
    else:
        logger.warning("Skill target plan returned non-list target_skills")

    return {
        "target_skills": target_skills,
        "strategy_notes": str(result.get("strategy_notes", "")),
    }


def _prepare_skill_targets_for_prompt(
    skill_targets: list[dict[str, Any]] | None,
) -> str:
    """Format verified skill targets for the diff prompt."""
    if not skill_targets:
        return "No verified skill targets."
    lines: list[str] = []
    for target in skill_targets:
        skill = str(target.get("skill", "")).strip()
        if not skill:
            continue
        source = str(target.get("source", "unknown")).strip() or "unknown"
        reason = str(target.get("reason", "")).strip()
        suffix = f": {reason}" if reason else ""
        lines.append(f"- {skill} ({source}){suffix}")
    return "\n".join(lines) if lines else "No verified skill targets."


async def improve_resume(
    original_resume: str,
    job_description: str,
    job_keywords: dict[str, Any],
    language: str = "en",
    prompt_id: str | None = None,
    original_resume_data: dict[str, Any] | None = None,
    confirmed_skills: list[str] | None = None,
    extrapolation_mode: str = "aggressive",
) -> dict[str, Any]:
    """Improve resume to better match job description.

    Args:
        original_resume: Original resume content (markdown)
        job_description: Target job description
        job_keywords: Extracted job keywords
        language: Output language code (en, es, zh, ja)
        prompt_id: Which tailor prompt to use
        original_resume_data: Structured resume JSON; used instead of
            markdown when available for higher-fidelity LLM input

    Returns:
        Improved resume data matching ResumeData schema

    LLM-006: Validates for truncation before Pydantic validation.
    LLM-011: Sanitizes job description to prevent prompt injection.
    """
    keywords_str = _prepare_keywords_for_prompt(job_keywords)
    output_language = get_language_name(language)

    selected_prompt_id = prompt_id or DEFAULT_IMPROVE_PROMPT_ID
    prompt_template = IMPROVE_RESUME_PROMPTS.get(
        selected_prompt_id, IMPROVE_RESUME_PROMPTS[DEFAULT_IMPROVE_PROMPT_ID]
    )
    truthfulness_rules = build_truthfulness_rules_with_skills(
        selected_prompt_id,
        confirmed_skills=confirmed_skills,
        extrapolation_mode=extrapolation_mode,
    )

    # LLM-011: Sanitize job description to prevent prompt injection
    sanitized_jd = _sanitize_user_input(job_description)

    # Use structured JSON when available for higher-fidelity LLM input,
    # but fall back to raw markdown if the structured data has truncated
    # (year-only) dates — the markdown preserves months from the original PDF.
    if original_resume_data is not None:
        if _has_month_in_dates(original_resume_data):
            resume_input = json.dumps(original_resume_data)
        else:
            logger.info(
                "Structured resume data has year-only dates; using raw markdown "
                "to preserve month precision."
            )
            resume_input = original_resume
    else:
        resume_input = original_resume

    prompt = prompt_template.format(
        job_description=sanitized_jd,
        job_keywords=keywords_str,
        original_resume=resume_input,
        schema=IMPROVE_SCHEMA_EXAMPLE,
        output_language=output_language,
        critical_truthfulness_rules=truthfulness_rules,
    )

    result = await complete_json(
        prompt=prompt,
        system_prompt="You are an expert resume editor. Output only valid JSON.",
        max_tokens=8192,
    )

    # LLM-006: Pre-validation check for truncation signs
    _check_for_truncation(result)

    # Validate against schema
    validated = ResumeData.model_validate(result)
    return validated.model_dump()


def _format_entry_label(parts: list[str], fallback: str) -> str:
    label = " | ".join([part for part in parts if part])
    return label if label else fallback


def _format_experience_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("title", ""),
            entry.get("company", ""),
            entry.get("years", ""),
        ],
        f"Work experience #{index + 1}",
    )


def _format_education_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("degree", ""),
            entry.get("institution", ""),
            entry.get("years", ""),
        ],
        f"Education #{index + 1}",
    )


def _format_project_entry(entry: dict[str, Any], index: int) -> str:
    return _format_entry_label(
        [
            entry.get("name", ""),
            entry.get("role", ""),
            entry.get("years", ""),
        ],
        f"Project #{index + 1}",
    )


def _normalize_entry(
    entry: dict[str, Any],
    ignore_keys: set[str] | None,
) -> dict[str, Any]:
    """Return an entry dict with ignored keys removed for diff comparisons.

    Ignored keys are excluded so entry-level change detection can skip fields
    that are diffed separately (e.g., description lists).
    """
    if ignore_keys is None:
        return entry
    return {key: value for key, value in entry.items() if key not in ignore_keys}


def _append_entry_changes(
    changes: list[ResumeFieldDiff],
    field_key: str,
    field_type: str,
    original_items: list[dict[str, Any]],
    improved_items: list[dict[str, Any]],
    formatter: Callable[[dict[str, Any], int], str],
    ignore_keys: set[str] | None = None,
) -> None:
    min_len = min(len(original_items), len(improved_items))

    for idx in range(min_len):
        original_entry = original_items[idx]
        improved_entry = improved_items[idx]
        if _normalize_entry(original_entry, ignore_keys) != _normalize_entry(
            improved_entry, ignore_keys
        ):
            changes.append(
                ResumeFieldDiff(
                    field_path=f"{field_key}[{idx}]",
                    field_type=field_type,
                    change_type="modified",
                    original_value=formatter(original_entry, idx),
                    new_value=formatter(improved_entry, idx),
                    confidence="medium",
                )
            )

    for idx in range(min_len, len(improved_items)):
        changes.append(
            ResumeFieldDiff(
                field_path=f"{field_key}[{idx}]",
                field_type=field_type,
                change_type="added",
                new_value=formatter(improved_items[idx], idx),
                confidence="high",
            )
        )

    for idx in range(min_len, len(original_items)):
        changes.append(
            ResumeFieldDiff(
                field_path=f"{field_key}[{idx}]",
                field_type=field_type,
                change_type="removed",
                original_value=formatter(original_items[idx], idx),
                confidence="medium",
            )
        )


def _normalize_string_list(value: Any, field_name: str) -> list[str]:
    """Normalize string list values and log any non-string entries.

    Accepts lists of strings or objects containing name/label/value keys.
    """
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    invalid_count = 0
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                normalized.append(stripped)
            continue
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("label") or item.get("value")
            if isinstance(candidate, str):
                stripped = candidate.strip()
                if stripped:
                    normalized.append(stripped)
                else:
                    invalid_count += 1
            else:
                invalid_count += 1
            continue
        if item is None:
            continue
        invalid_count += 1
    if invalid_count:
        logger.warning("Skipped non-string entries in %s: %d", field_name, invalid_count)
    return normalized


def _build_string_index(value: Any, field_name: str) -> dict[str, str]:
    """Build a case-insensitive index for string list comparisons."""
    items = _normalize_string_list(value, field_name)
    index: dict[str, str] = {}
    for item in items:
        key = item.casefold()
        if key not in index:
            index[key] = item
    return index


def _extract_description_list(entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return []
    return _normalize_string_list(entry.get("description", []), "workExperience.description")


def _append_list_changes(
    changes: list[ResumeFieldDiff],
    field_path: str,
    field_type: str,
    original_items: list[str],
    improved_items: list[str],
    confidences: DiffConfidence,
) -> None:
    matcher = SequenceMatcher(a=original_items, b=improved_items, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for item in original_items[i1:i2]:
                changes.append(
                    ResumeFieldDiff(
                        field_path=field_path,
                        field_type=field_type,
                        change_type="removed",
                        original_value=item,
                        confidence=confidences.removed,
                    )
                )
        elif tag == "insert":
            for item in improved_items[j1:j2]:
                changes.append(
                    ResumeFieldDiff(
                        field_path=field_path,
                        field_type=field_type,
                        change_type="added",
                        new_value=item,
                        confidence=confidences.added,
                    )
                )
        elif tag == "replace":
            original_segment = original_items[i1:i2]
            improved_segment = improved_items[j1:j2]
            segment_len = max(len(original_segment), len(improved_segment))
            for offset in range(segment_len):
                original_value = (
                    original_segment[offset] if offset < len(original_segment) else None
                )
                new_value = (
                    improved_segment[offset] if offset < len(improved_segment) else None
                )
                if original_value is not None and new_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="modified",
                            original_value=original_value,
                            new_value=new_value,
                            confidence=confidences.modified,
                        )
                    )
                elif new_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="added",
                            new_value=new_value,
                            confidence=confidences.added,
                        )
                    )
                elif original_value is not None:
                    changes.append(
                        ResumeFieldDiff(
                            field_path=field_path,
                            field_type=field_type,
                            change_type="removed",
                            original_value=original_value,
                            confidence=confidences.removed,
                        )
                    )


def calculate_resume_diff(
    original: dict[str, Any],
    improved: dict[str, Any],
) -> tuple[ResumeDiffSummary, list[ResumeFieldDiff]]:
    """Compute the diff between original and improved resumes.

    Args:
        original: Original resume data dict
        improved: Improved resume data dict

    Returns:
        (diff summary, detailed change list)
    """
    changes: list[ResumeFieldDiff] = []

    # 1. Compare summary
    original_summary = (original.get("summary") or "").strip()
    improved_summary = (improved.get("summary") or "").strip()
    if original_summary != improved_summary:
        if original_summary and not improved_summary:
            change_type = "removed"
        elif improved_summary and not original_summary:
            change_type = "added"
        else:
            change_type = "modified"
        changes.append(
            ResumeFieldDiff(
                field_path="summary",
                field_type="summary",
                change_type=change_type,
                original_value=original_summary or None,
                new_value=improved_summary or None,
                confidence="medium",
            )
        )

    # 2. Compare skills (order changes are intentionally ignored)
    orig_skills = _build_string_index(
        original.get("additional", {}).get("technicalSkills", []),
        "additional.technicalSkills",
    )
    new_skills = _build_string_index(
        improved.get("additional", {}).get("technicalSkills", []),
        "additional.technicalSkills",
    )
    orig_skill_keys = set(orig_skills)
    new_skill_keys = set(new_skills)
    for skill_key in new_skill_keys - orig_skill_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.technicalSkills",
            field_type="skill",
            change_type="added",
            new_value=new_skills[skill_key],
            confidence="high"  # Newly added skills are high risk
        ))

    for skill_key in orig_skill_keys - new_skill_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.technicalSkills",
            field_type="skill",
            change_type="removed",
            original_value=orig_skills[skill_key],
            confidence="medium"
        ))

    # 3. Compare work experience descriptions
    original_experiences = original.get("workExperience", [])
    improved_experiences = improved.get("workExperience", [])
    max_experience_len = max(len(original_experiences), len(improved_experiences))
    confidences = DiffConfidence(added="medium", removed="low", modified="medium")
    for idx in range(max_experience_len):
        original_entry = (
            original_experiences[idx] if idx < len(original_experiences) else None
        )
        improved_entry = (
            improved_experiences[idx] if idx < len(improved_experiences) else None
        )
        if not original_entry and not improved_entry:
            continue
        _append_list_changes(
            changes,
            field_path=f"workExperience[{idx}].description",
            field_type="description",
            original_items=_extract_description_list(original_entry),
            improved_items=_extract_description_list(improved_entry),
            confidences=confidences,
        )

    # 4. Compare certifications (order changes are intentionally ignored)
    orig_certs = _build_string_index(
        original.get("additional", {}).get("certificationsTraining", []),
        "additional.certificationsTraining",
    )
    new_certs = _build_string_index(
        improved.get("additional", {}).get("certificationsTraining", []),
        "additional.certificationsTraining",
    )
    orig_cert_keys = set(orig_certs)
    new_cert_keys = set(new_certs)
    for cert_key in new_cert_keys - orig_cert_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.certificationsTraining",
            field_type="certification",
            change_type="added",
            new_value=new_certs[cert_key],
            confidence="high"
        ))

    for cert_key in orig_cert_keys - new_cert_keys:
        changes.append(ResumeFieldDiff(
            field_path="additional.certificationsTraining",
            field_type="certification",
            change_type="removed",
            original_value=orig_certs[cert_key],
            confidence="medium"
        ))

    # 4b. Compare education descriptions (a single string per entry, not a list)
    original_education = original.get("education", [])
    improved_education = improved.get("education", [])
    for idx in range(max(len(original_education), len(improved_education))):
        orig_entry = original_education[idx] if idx < len(original_education) else None
        impr_entry = improved_education[idx] if idx < len(improved_education) else None
        orig_desc = (
            str(orig_entry.get("description") or "").strip()
            if isinstance(orig_entry, dict)
            else ""
        )
        impr_desc = (
            str(impr_entry.get("description") or "").strip()
            if isinstance(impr_entry, dict)
            else ""
        )
        if orig_desc == impr_desc:
            continue
        if orig_desc and not impr_desc:
            change_type = "removed"
        elif impr_desc and not orig_desc:
            change_type = "added"
        else:
            change_type = "modified"
        changes.append(ResumeFieldDiff(
            field_path=f"education[{idx}].description",
            field_type="education",
            change_type=change_type,
            original_value=orig_desc or None,
            new_value=impr_desc or None,
            confidence="medium",
        ))

    # 4c. Compare languages (order changes are intentionally ignored)
    orig_langs = _build_string_index(
        original.get("additional", {}).get("languages", []),
        "additional.languages",
    )
    new_langs = _build_string_index(
        improved.get("additional", {}).get("languages", []),
        "additional.languages",
    )
    for lang_key in set(new_langs) - set(orig_langs):
        changes.append(ResumeFieldDiff(
            field_path="additional.languages",
            field_type="language",
            change_type="added",
            new_value=new_langs[lang_key],
            confidence="high",
        ))
    for lang_key in set(orig_langs) - set(new_langs):
        changes.append(ResumeFieldDiff(
            field_path="additional.languages",
            field_type="language",
            change_type="removed",
            original_value=orig_langs[lang_key],
            confidence="medium",
        ))

    # 4d. Compare awards (order changes are intentionally ignored)
    orig_awards = _build_string_index(
        original.get("additional", {}).get("awards", []),
        "additional.awards",
    )
    new_awards = _build_string_index(
        improved.get("additional", {}).get("awards", []),
        "additional.awards",
    )
    for award_key in set(new_awards) - set(orig_awards):
        changes.append(ResumeFieldDiff(
            field_path="additional.awards",
            field_type="award",
            change_type="added",
            new_value=new_awards[award_key],
            confidence="high",
        ))
    for award_key in set(orig_awards) - set(new_awards):
        changes.append(ResumeFieldDiff(
            field_path="additional.awards",
            field_type="award",
            change_type="removed",
            original_value=orig_awards[award_key],
            confidence="medium",
        ))

    # 5. Compare added/removed/modified entries
    # Descriptions are diffed separately; ignore them when detecting entry-level changes.
    _append_entry_changes(
        changes,
        "workExperience",
        "experience",
        original.get("workExperience", []),
        improved.get("workExperience", []),
        _format_experience_entry,
        {"description"},
    )
    _append_entry_changes(
        changes,
        "education",
        "education",
        original.get("education", []),
        improved.get("education", []),
        _format_education_entry,
        {"description"},  # diffed separately in step 4b — avoid duplicate entry-level diffs
    )
    _append_entry_changes(
        changes,
        "personalProjects",
        "project",
        original.get("personalProjects", []),
        improved.get("personalProjects", []),
        _format_project_entry,
    )

    # 6. Build summary
    summary = ResumeDiffSummary(
        total_changes=len(changes),
        skills_added=len([c for c in changes if c.field_type == "skill" and c.change_type == "added"]),
        skills_removed=len([c for c in changes if c.field_type == "skill" and c.change_type == "removed"]),
        descriptions_modified=len(
            [
                c
                for c in changes
                if c.field_type == "description" and c.change_type == "modified"
            ]
        ),
        certifications_added=len([c for c in changes if c.field_type == "certification" and c.change_type == "added"]),
        high_risk_changes=len([c for c in changes if c.confidence == "high"])
    )

    return summary, changes


def generate_improvements(job_keywords: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate improvement suggestions based on job keywords.

    Args:
        job_keywords: Extracted job keywords

    Returns:
        List of improvement suggestions
    """
    improvements = []

    # Generate suggestions based on required skills
    required_skills = job_keywords.get("required_skills", [])
    for skill in required_skills[:3]:  # Top 3 required skills
        improvements.append(
            {
                "suggestion": f"Emphasized '{skill}' to match job requirements",
                "lineNumber": None,
            }
        )

    # Generate suggestions based on key responsibilities
    responsibilities = job_keywords.get("key_responsibilities", [])
    for resp in responsibilities[:2]:  # Top 2 responsibilities
        improvements.append(
            {
                "suggestion": f"Aligned experience with: {resp}",
                "lineNumber": None,
            }
        )

    # Default improvement if none generated
    if not improvements:
        improvements.append(
            {
                "suggestion": "Resume content optimized for better keyword alignment with job description",
                "lineNumber": None,
            }
        )

    return improvements
