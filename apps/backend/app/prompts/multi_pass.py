"""Focused per-section prompts for the multi-pass resume parser.

Each prompt takes ONLY the text of a single section (produced by the regex
section splitter in services/multi_pass_parser.py) and returns just the JSON
for that section. Splitting the work this way avoids the "5+ jobs fill the
output budget, everything after is dropped" failure mode of the single-shot
prompt on a 14B local model — every call now has one small job.
"""

# --------------------------------------------------------------------------- #
# Personal info
# --------------------------------------------------------------------------- #

PERSONAL_INFO_PROMPT = """Extract personal / contact info from this resume header
into JSON. Output ONLY the JSON object, no other text.

Shape:
{{
  "name": "",
  "title": "",
  "email": "",
  "phone": "",
  "location": "",
  "website": "",
  "linkedin": "",
  "github": ""
}}

Rules:
- `title` is the professional headline that usually sits on a line RIGHT UNDER
  the name (e.g. "Senior Data Engineer", "BI Specialist & Data Engineer —
  4 years across ..."). If absent, use "".
- Return "" (not null) for any missing string. Never invent values that
  aren't in the source text.
- `location` is the city / country line. Include the country when present.
- `linkedin` / `github` / `website` — strip protocol if the source has it
  bare ("linkedin.com/in/foo" stays as-is; "https://linkedin.com/in/foo"
  becomes "linkedin.com/in/foo").

Header text:
{block}"""


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #

SUMMARY_PROMPT = """Extract the professional summary from this text as a
single JSON string. Output ONLY the string wrapped in a top-level "summary"
field, no other text.

Shape: {{"summary": "..."}}

Rules:
- If the source has MULTIPLE labeled summary variants (e.g. "[A] Data
  Engineer ...", "[B] BI Consultant ..."), concatenate them with blank
  lines, keeping the labels. Never drop a variant.
- Preserve the source's wording; don't summarize further.
- If no summary is present, return {{"summary": ""}}.

Text:
{block}"""


# --------------------------------------------------------------------------- #
# Work experience
# --------------------------------------------------------------------------- #

EXPERIENCE_PROMPT = """Extract every work experience entry from this text into
JSON. Output ONLY the JSON object, no other text.

Shape:
{{
  "workExperience": [
    {{
      "id": 1,
      "title": "Job title",
      "company": "Company name",
      "location": "City, Country",
      "years": "Mon YYYY - Mon YYYY",
      "description": ["bullet 1", "bullet 2"],
      "descriptionStyles": ["bullet", "bullet"]
    }}
  ]
}}

Rules:
- ONE entry per role. If the source lists 5 jobs, output 5 entries.
- Do NOT invent or merge roles. Do NOT put research / education / publications
  here — those live in other sections.
- `years` preserves the source's precision. Keep months when present
  ("Mar 2025 - Feb 2026"). Use "YYYY - YYYY" only when the source has no
  months. Normalize separators to " - " and "Ongoing"/"Current" to "Present".
- `descriptionStyles` MUST have the same length as `description[]`. Use
  "bullet" for normal bullets, "plain" for a subheading/label row.
- Strip inline tag markers like [SCOPE], [MGMT], [A,B,C] from bullets.
- Preserve numeric metrics verbatim; never round or drop numbers.
- Number ids starting from 1 in source order.
- If the section is empty, return {{"workExperience": []}}.

Experience section text:
{block}"""


# --------------------------------------------------------------------------- #
# Education
# --------------------------------------------------------------------------- #

EDUCATION_PROMPT = """Extract every education entry from this text into JSON.
Output ONLY the JSON object, no other text.

Shape:
{{
  "education": [
    {{
      "id": 1,
      "institution": "University / School name",
      "degree": "Degree name",
      "years": "Mon YYYY - Mon YYYY",
      "description": "One-line summary of grades, focus, thesis, etc."
    }}
  ]
}}

Rules:
- ONE entry per school / program.
- Merge grades, focus areas, thesis mentions, publications into `description`
  as one string.
- `years` follows the same precision + normalization rules as experience.
- Do NOT put internships or working-student jobs here — those are work
  experience.
- If the section is empty, return {{"education": []}}.

Education section text:
{block}"""


# --------------------------------------------------------------------------- #
# Technical skills
# --------------------------------------------------------------------------- #

SKILLS_PROMPT = """Extract technical skills from this text into a JSON list of
strings. Output ONLY the JSON object, no other text.

Shape: {{"technicalSkills": ["Category: item1, item2, item3", ...]}}

Rules:
- When the source groups skills under category headings (e.g.
  "BI & Visualisation: Power BI, Tableau" or a bold "Programming" label
  followed by items), emit ONE STRING PER CATEGORY as
  "Category: item1, item2, item3", preserving the source order.
- When the source has no categories, emit one bare skill per string.
- NEVER drop items. Every listed skill must appear exactly once.
- Preserve inline qualifiers verbatim: "SQL (window functions, CTEs)" stays
  as one item, not fragmented on its inner commas.
- If the section is empty, return {{"technicalSkills": []}}.

Skills section text:
{block}"""


# --------------------------------------------------------------------------- #
# Languages / certifications / awards — one prompt handles the three flat lists
# --------------------------------------------------------------------------- #

FLAT_LIST_PROMPT = """Extract a flat list of items from this text into a JSON
list of strings. Output ONLY the JSON object, no other text.

Shape: {{"{field}": ["item 1", "item 2"]}}

Rules:
- One string per item exactly as written in the source (preserve level
  markers, dates, issuers).
- For languages: keep the proficiency in parentheses: "English (C1)",
  "German (A2)".
- Never invent items. If the section is empty, return {{"{field}": []}}.

{label} section text:
{block}"""


# --------------------------------------------------------------------------- #
# Custom section (research, publications, volunteer, talks, …)
# --------------------------------------------------------------------------- #

CUSTOM_SECTION_PROMPT = """Extract this section into a JSON custom section
entry. Output ONLY the JSON object, no other text.

Shape:
{{
  "sectionType": "itemList",
  "items": [
    {{
      "id": 1,
      "title": "Primary title",
      "subtitle": "Institution / venue / author (optional)",
      "location": "City, Country (optional)",
      "years": "Mon YYYY - Mon YYYY",
      "description": ["bullet 1", "bullet 2"],
      "descriptionStyles": ["bullet", "bullet"]
    }}
  ]
}}

Rules:
- Use "itemList" when items have titles + dates (research projects,
  publications, volunteer roles, talks).
- Use "text" with a single "text" field when the section is a single
  paragraph.
- Use "stringList" with a "strings" field when the section is a bare list
  (hobbies, interests).
- ONE entry per item. `description[]` and `descriptionStyles[]` MUST match
  in length.
- Strip inline tag markers.
- Do NOT invent items. Do NOT put entries here that belong in workExperience,
  education, or technicalSkills.
- If the section is empty, return {{"sectionType": "itemList", "items": []}}.

Section text (heading was: "{heading}"):
{block}"""
