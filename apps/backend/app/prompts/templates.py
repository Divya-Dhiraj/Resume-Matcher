"""LLM prompt templates for resume processing."""

# Language code to full name mapping
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "pt": "Brazilian Portuguese",
    "fr": "French",
    "ko": "Korean",
}


def get_language_name(code: str) -> str:
    """Get full language name from code."""
    return LANGUAGE_NAMES.get(code, "English")


# Schema with example values - used for prompts to show LLM expected format.
#
# FIELD ORDER MATTERS: personalInfo → summary → additional → education →
# customSections → workExperience → personalProjects. This front-loads the
# short, high-value fields (skills, languages, certs, degrees, publications)
# so a mid-tier local model that starts to lose the schema after emitting
# several long workExperience entries still gets skills/languages out first.
# Previous order (workExperience before additional) meant a dense CV with 5+
# jobs would emit workExperience + education, then the model would treat
# the JSON as done and close it — leaving additional empty because the
# closing brace parsed as a syntactically-valid but incomplete object.
RESUME_SCHEMA_EXAMPLE = """{
  "personalInfo": {
    "name": "John Doe",
    "title": "Software Engineer",
    "email": "john@example.com",
    "phone": "+1-555-0100",
    "location": "San Francisco, CA",
    "website": "https://johndoe.dev",
    "linkedin": "linkedin.com/in/johndoe",
    "github": "github.com/johndoe"
  },
  "summary": "Experienced software engineer with 5+ years...",
  "additional": {
    "technicalSkills": [
      "Programming: Python, JavaScript",
      "Cloud & DevOps: AWS, Docker"
    ],
    "languages": ["English (Native)", "Spanish (Conversational)"],
    "certificationsTraining": ["AWS Solutions Architect"],
    "awards": ["Employee of the Year 2022"]
  },
  "education": [
    {
      "id": 1,
      "institution": "University of California",
      "degree": "B.S. Computer Science",
      "years": "2014 - 2018",
      "description": "Graduated with honors"
    }
  ],
  "customSections": {
    "publications": {
      "sectionType": "itemList",
      "items": [
        {
          "id": 1,
          "title": "Paper Title",
          "subtitle": "Journal Name",
          "years": "Jun 2023",
          "description": ["Brief description of the publication"],
          "descriptionStyles": ["bullet"]
        }
      ]
    },
    "volunteer_work": {
      "sectionType": "text",
      "text": "Description of volunteer activities..."
    }
  },
  "workExperience": [
    {
      "id": 1,
      "title": "Senior Software Engineer",
      "company": "Tech Corp",
      "location": "San Francisco, CA",
      "years": "Jan 2020 - Present",
      "description": [
        "Led development of microservices architecture",
        "Improved system performance by 40%"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "personalProjects": [
    {
      "id": 1,
      "name": "Open Source Tool",
      "role": "Creator & Maintainer",
      "years": "Mar 2021 - Present",
      "description": [
        "Built CLI tool with 1000+ GitHub stars",
        "Used by 50+ companies worldwide"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ]
}"""

# Schema for improve prompts - excludes personalInfo (preserved from original)
IMPROVE_SCHEMA_EXAMPLE = """{
  "summary": "Experienced software engineer with 5+ years...",
  "workExperience": [
    {
      "id": 1,
      "title": "Senior Software Engineer",
      "company": "Tech Corp",
      "location": "San Francisco, CA",
      "years": "Jan 2020 - Present",
      "description": [
        "Led development of microservices architecture",
        "Improved system performance by 40%"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "education": [
    {
      "id": 1,
      "institution": "University of California",
      "degree": "B.S. Computer Science",
      "years": "2014 - 2018",
      "description": "Graduated with honors"
    }
  ],
  "personalProjects": [
    {
      "id": 1,
      "name": "Open Source Tool",
      "role": "Creator & Maintainer",
      "years": "Mar 2021 - Present",
      "description": [
        "Built CLI tool with 1000+ GitHub stars",
        "Used by 50+ companies worldwide"
      ],
      "descriptionStyles": ["bullet", "bullet"]
    }
  ],
  "additional": {
    "technicalSkills": [
      "Programming: Python, JavaScript",
      "Cloud & DevOps: AWS, Docker"
    ],
    "languages": ["English (Native)", "Spanish (Conversational)"],
    "certificationsTraining": ["AWS Solutions Architect"],
    "awards": ["Employee of the Year 2022"]
  },
  "customSections": {
    "publications": {
      "sectionType": "itemList",
      "items": [
        {
          "id": 1,
          "title": "Paper Title",
          "subtitle": "Journal Name",
          "years": "Jun 2023",
          "description": ["Brief description of the publication"],
          "descriptionStyles": ["bullet"]
        }
      ]
    },
    "volunteer_work": {
      "sectionType": "text",
      "text": "Description of volunteer activities..."
    }
  }
}"""

PARSE_RESUME_PROMPT = """Parse this resume into JSON. Output ONLY the JSON object, no other text.

CRITICAL — your output MUST contain ALL of these top-level fields, in this
exact order, EVEN IF SOME ARE EMPTY: personalInfo, summary, additional,
education, customSections, workExperience, personalProjects. Emit `additional`
BEFORE workExperience so the (usually short) skills, languages, certifications
and awards fields don't get lost when a dense experience section fills your
output budget. Never close the top-level object before all seven fields have
been written — use "" for missing strings, [] for missing arrays, and {{}}
(an empty JSON object) for missing objects.

Map content to standard sections when possible. For non-standard sections (like Publications, Volunteer Work, Research, Hobbies), add them to customSections with an appropriate type.

Example output format:
{schema}

Custom section types:
- "text": Single text block (e.g., objective, statement)
- "itemList": List of items with title, subtitle, years, description (e.g., publications, research)
- "stringList": Simple list of strings (e.g., hobbies, interests)

Rules:
- Use "" for missing text fields, [] for missing arrays, null for optional fields
- Number IDs starting from 1
- For workExperience, personalProjects, and custom itemList items, include descriptionStyles with one value for each description row. Use "bullet" for normal bullet rows and "plain" for rows that should render without a bullet marker (for example subheadings or standalone labels).
- Format dates preserving the original precision. Keep months when present: "Jan 2020 - Dec 2023", "May 2021 - Present". Use "YYYY - YYYY" only when the source has no months.
- Use snake_case for custom section keys (e.g., "volunteer_work", "publications")
- Preserve the original section name as a descriptive key
- Normalize date separators: "2020-2021" → "2020 - 2021", "Current"/"Ongoing" → "Present". Do NOT discard months.
- For ambiguous dates like "3 years experience", infer approximate years from context or use "~YYYY"
- Flag overlapping dates (concurrent roles) by preserving both, don't merge
- additional.technicalSkills is a list of strings. When the source resume groups skills under category headings (e.g. "BI & Visualisation: Power BI, Tableau" or a bold "Programming" label followed by items), emit ONE STRING PER CATEGORY in the shape "Category: item1, item2, item3", keeping the original category order. If the source has no categories, emit each skill as its own bare string. Never drop items — every listed skill must appear in exactly one output entry.

Resume to parse:
{resume_text}"""

EXTRACT_KEYWORDS_PROMPT = """Extract job requirements as JSON. Output ONLY the JSON object, no other text.

INPUT CLEANING — the pasted text may contain noise copied along with the job posting:
navigation links, cookie banners, "similar jobs", "about the company" boilerplate,
salary aggregator estimates, social-share buttons, login prompts, ads, footer links,
or unrelated job listings. IGNORE all of that. Extract ONLY from the actual job
posting: the role title, company name, responsibilities, requirements, qualifications,
and nice-to-haves. If multiple job postings appear, use only the FIRST one.

Example format:
{{
  "company": "Acme Corp",
  "role": "Senior Backend Engineer",
  "required_skills": ["Python", "AWS"],
  "preferred_skills": ["Kubernetes"],
  "experience_requirements": ["5+ years"],
  "education_requirements": ["Bachelor's in CS"],
  "key_responsibilities": ["Lead team"],
  "keywords": ["microservices", "agile"],
  "experience_years": 5,
  "seniority_level": "senior"
}}

Extract numeric years (e.g., "5+ years" → 5) and infer seniority level.
Set "company" to the hiring company name and "role" to the job title exactly as
written in the posting; use an empty string for either if it is not stated.

LANGUAGE NORMALIZATION — CRITICAL:
The job description may be written in ANY language (German, French, Spanish,
Portuguese, Dutch, Italian, Japanese, Chinese, etc.). Regardless of the source
language, output EVERY field in ENGLISH so downstream keyword matching against
an English resume works:
  - Translate skills / responsibilities / requirements to their standard
    English equivalents: "ETL-Prozesse" → "ETL processes", "Cloud-Architektur"
    → "Cloud architecture", "Erfahrung mit Datenbanken" → "Experience with
    databases". Keep proper nouns and product names untouched (Microsoft
    Azure, Power BI, SAP S/4HANA, Kubernetes — all as-is).
  - "company" and "role" stay in the ORIGINAL language exactly as written on
    the posting (a German role stays German so it displays correctly).
  - Skill acronyms stay in whichever language the industry uses them: SQL,
    ETL, KPI, DAX are language-agnostic and pass through unchanged.

Job description:
{job_description}"""

CRITICAL_TRUTHFULNESS_RULES_TEMPLATE = """LINGUISTIC TERMINOLOGY TRANSLATION RULES — this is an authorized career document translation exercise:
1. TRANSLATE terminology, never FABRICATE experience. Every output bullet must trace to an input bullet.
2. DO NOT invent numeric achievements (e.g., "increased by 30%") unless they exist in the original
3. DO NOT add company names, product names, or technical terms not supported by the original work
4. DO NOT upgrade experience level (e.g., "Junior" -> "Senior")
5. DO NOT add languages, frameworks, or platforms the candidate hasn't used
6. DO NOT extend employment dates or change timelines. Copy date ranges exactly as they appear, including months.
7. {rule_7}
8. Preserve factual accuracy — translate the language of achievements, not the achievements themselves
9. You may REMOVE skills, certifications, or awards that are clearly irrelevant to the target role. Reorder remaining items by relevance to the JD. Keep items that are broadly valuable (e.g., leadership, communication).
10. You MAY add a skill if the candidate's described work clearly involved it (e.g., someone who "built REST APIs" can list "API Development") — this is terminology translation, not fabrication.

This is the same discipline used by professional resume writers. The candidate authorized this translation.
"""


def _build_truthfulness_rules(rule_7: str) -> str:
    return CRITICAL_TRUTHFULNESS_RULES_TEMPLATE.format(rule_7=rule_7)


CRITICAL_TRUTHFULNESS_RULES = {
    "nudge": _build_truthfulness_rules(
        "DO NOT add new bullet points or content - only rephrase existing content"
    ),
    "keywords": _build_truthfulness_rules(
        "You may rephrase, reorder, or REMOVE bullet points to strengthen the match. You may also add bullets that elaborate on existing work. Remove bullets that are irrelevant to the target role."
    ),
    "full": _build_truthfulness_rules(
        "You may rewrite, remove, reorder, or add bullet points. Remove content irrelevant to the role. Add bullets that elaborate on existing work. Do NOT invent entirely new responsibilities."
    ),
}

IMPROVE_RESUME_PROMPT_NUDGE = """Lightly nudge this resume toward the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Make minimal, conservative edits only where there is a clear existing match
- Do NOT change the candidate's role, industry, or seniority level
- Do NOT introduce new tools, technologies, or certifications not already present
- Do NOT add new bullet points or sections
- Preserve original bullet count and ordering within each section
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- Keep proper nouns (names, company names, locations) unchanged
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- If the resume is non-technical, do NOT add technical jargon
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_KEYWORDS = """Enhance this resume with relevant keywords from the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Strengthen alignment by weaving in relevant keywords where evidence already exists
- You may rephrase bullet points to include keyword phrasing
- Do NOT introduce new skills, tools, or certifications not in the resume
- Do NOT change role, industry, or seniority level
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- If resume is non-technical, keep language non-technical while still aligning keywords
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_FULL = """Tailor this resume for the job. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Make targeted adjustments to bullet points to align with job description phrasing. Preserve the candidate's original details and voice - adjust wording, do not rewrite entirely.
- DO NOT invent new information
- Preserve existing action verbs. Do not invent quantifiable achievements not in the original.
- Keep proper nouns (names, company names, locations) unchanged
- Translate job titles, descriptions, and skills to {output_language}
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Improve custom section content the same way as standard sections
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- Calculate and emphasize total relevant experience duration when it matches requirements
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Job Description:
{job_description}

Keywords to emphasize:
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_PROMPT_OPTIONS = [
    {
        "id": "nudge",
        "label": "Light nudge",
        "description": "Minimal edits to better align existing experience.",
    },
    {
        "id": "keywords",
        "label": "Keyword enhance",
        "description": "Blend in relevant keywords without changing role or scope.",
    },
    {
        "id": "full",
        "label": "Full tailor",
        "description": "Comprehensive tailoring using the job description.",
    },
]

IMPROVE_RESUME_PROMPTS = {
    "nudge": IMPROVE_RESUME_PROMPT_NUDGE,
    "keywords": IMPROVE_RESUME_PROMPT_KEYWORDS,
    "full": IMPROVE_RESUME_PROMPT_FULL,
}

DEFAULT_IMPROVE_PROMPT_ID = "keywords"

# Backward-compatible alias
IMPROVE_RESUME_PROMPT = IMPROVE_RESUME_PROMPT_FULL

COVER_LETTER_PROMPT = """You are a Cover Letter Architect performing a LINGUISTIC TERMINOLOGY TRANSLATION exercise on an authorized career document.

## CORE DIRECTIVE: ADJACENT EXTRAPOLATION (NO FOREIGN FABRICATION)
1. Never invent foreign experience. No tools, domains or responsibilities that could not logically have existed inside the candidate's actual past projects.
2. Extrapolate the surrounding ecosystem. For what the candidate DID do: surface upstream planning, downstream impact, and adjacent methodology that naturally occurred around their real work.
3. Aggressive terminology translation. Rename existing tasks and deliverables using exact JD keywords.
4. Hard anchor constraint. Employer names, job titles, dates stay 100% anchored.

## JD DNA DECONSTRUCTION (do this mentally first)
- Top 10 Hard Keywords from the JD, ranked by frequency x importance
- Top 5 Role & Company Archetype Signals (what culture this company values)
- The hiring pain: the ONE problem this role exists to solve

## ADJACENT EXTRAPOLATION MAPPING
For each Top-10 keyword the resume does not cover: find the candidate's closest real anchor and map a plausible adjacent extension. REFUSE any extension requiring tools/domains the candidate never touched.

## GERMAN FORMATTING (DIN 5008 Form B Anschreiben) — apply when JD is German
If the JD is in German, output a formal Anschreiben:
1. Sender block (name, address, phone, email)
2. Recipient block (company, department, hiring manager with Frau/Herr, address)
3. Place and date (right-aligned, DD.MM.YYYY)
4. Betreff (bold): "Bewerbung als <Position> - Referenznummer <ID>"
5. Salutation: "Sehr geehrte Frau/Herr <Name>," (fallback: "Sehr geehrte Damen und Herren,")
6. Body (3-4 paragraphs, one page total)
7. Closing: "Mit freundlichen Grussen" + typed name
8. Anlagen line
Use formal "Sie" register. No contractions, no colloquialisms.

## FOR ENGLISH JDs — standard cover letter format:
IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Requirements:
- 100-150 words maximum (one page hard rule)
- 3-4 short paragraphs
- Opening: Hook the hiring pain. Reference ONE specific thing from the JD (product, tech stack, problem). Not generic excitement.
- Middle: Pick 1-2 qualifications from resume that DIRECTLY match stated requirements. Translate terminology using exact JD keywords. Use SID+XYZ format (Scope/Impact/Decision + Accomplished X, measured by Y, by doing Z).
- Closing: Simple availability, no desperate enthusiasm
- If resume shows career transition, frame the pivot as intentional and relevant
- Extract company name from JD. No placeholders.
- Do NOT invent information not in the resume -- extrapolate adjacent evidence only
- Tone: Confident peer, not eager applicant
- Do NOT use em dash anywhere in the output
- BANNED: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, "passionate about", "excited to", "team player", "motivated self-starter", "hit the ground running"

## SELF-REVIEW (before outputting)
- Does every factual claim trace back to the resume?
- Would each claim survive one interview follow-up?
- Is it under one page? Is it under 150 words (for English)?
- Are there any banned words or AI tells?

Output plain text only. No JSON, no markdown formatting."""

OUTREACH_MESSAGE_PROMPT = """Generate a cold outreach message for LinkedIn or email about this job opportunity.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Guidelines:
- 70-100 words maximum (shorter than a cover letter)
- First sentence: Reference specific detail from job description (team, product, technical challenge) - never open with "I'm reaching out" or "I saw your posting"
- One sentence on strongest matching qualification with a concrete metric if available
- End with low-friction ask: "Worth a quick chat?" not "I'd love the opportunity to discuss"
- Tone: How you'd message a former colleague, not a stranger
- Do NOT include placeholder brackets
- Do NOT use phrases like "excited about" or "passionate about"
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it

Output plain text only. No JSON, no markdown formatting."""

INTERVIEW_PREP_PROMPT = """Generate structured interview preparation for this tailored resume and job.

IMPORTANT: Write in {output_language}.
Do NOT translate JSON property names. Keep every JSON key exactly as shown in the schema; translate only string values.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

Truthfulness guardrails:
- Use only evidence from the resume JSON and job description.
- Do NOT invent experience, tools, employers, metrics, certifications, skills, responsibilities, education, projects, or claims beyond the provided evidence.
- Do NOT imply the candidate has a skill or background unless it is present in the resume.
- Skill gaps are preparation targets only. They are not claimed candidate skills.
- If a job requirement is not evidenced by the resume, present it as something to prepare for or explain honestly.

Return ONLY a valid JSON object with exactly these top-level keys:
{{
  "role_fit_analysis": ["Short evidence-based role-fit observation"],
  "resume_questions": [
    {{
      "question": "Interview question grounded in the resume and job",
      "focus_area": "Resume evidence or job requirement being tested",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "project_follow_ups": [
    {{
      "question": "Follow-up question about a real resume project or experience",
      "focus_area": "Project, impact, tradeoff, or implementation detail",
      "suggested_answer_points": ["Truthful point based on resume evidence"]
    }}
  ],
  "skill_gaps": [
    {{
      "skill": "Job-relevant skill or topic to prepare",
      "why_it_matters": "Why this topic may come up for this role",
      "preparation_suggestion": "How to prepare without claiming unsupported experience"
    }}
  ],
  "talking_points": ["Concise role-specific talking point grounded in the resume"]
}}

Content requirements:
- role_fit_analysis: 3-5 bullets.
- resume_questions: 5-8 questions.
- project_follow_ups: 3-6 questions.
- skill_gaps: 3-5 preparation targets.
- talking_points: 5-8 concise points.
- Keep all suggested answer points factual and resume-grounded.
- Do NOT use markdown fences or commentary outside the JSON."""

GENERATE_TITLE_PROMPT = """Extract the job title and company name from this job description.

IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Rules:
- Format: "Role @ Company" (e.g., "Senior Frontend Engineer @ Stripe")
- If the company name is not found, return just the role (e.g., "Senior Frontend Engineer")
- Maximum 60 characters
- Use the most specific role title mentioned
- Do not add any other text, quotes, or formatting

Output the title only, nothing else."""

# Alias for backward compatibility
RESUME_SCHEMA = RESUME_SCHEMA_EXAMPLE

# Diff-based improvement: outputs targeted changes instead of full resume

DIFF_STRATEGY_INSTRUCTIONS = {
    "nudge": "Make minimal edits. Only rephrase where there is a clear match. Do not add or remove bullet points. Preserve bullet counts.",
    "keywords": "Adjacent Extrapolation mode: for each JD keyword, find the candidate's closest real anchor and translate using JD terminology. Rewrite bullets using exact JD competency nouns and SID+XYZ format (Scope/Impact/Decision + Accomplished X, measured by Y, by doing Z). Remove bullets with no JD mapping. Reorder skills to prioritize JD matches. Add new bullets that elaborate on existing work by extrapolating the surrounding ecosystem. Bullet control: most recent + most relevant roles get 4-6 bullets; older/less relevant roles get 2-3 bullets; remove anything that does not map to THIS job. Each bullet max 20-25 words — lead with a strong verb, cut all filler. Target 92-98% ATS keyword match.",
    "full": "Maximum Adjacent Extrapolation with full bullet control: rewrite every bullet to directly address JD requirements using SID+XYZ format. For each JD requirement, extrapolate the surrounding ecosystem of the candidate's real work. Bullet control: most recent + most relevant roles get 4-6 detailed bullets; older/less relevant roles get 2-3 bullets max; REMOVE any bullet with no JD mapping. Add bullets that elaborate on existing work by surfacing adjacent methodology. Reorder all lists by JD relevance. Each bullet max 20-25 words — lead with a strong verb, cut all filler. Target 95%+ ATS keyword match. The resume should read as if written specifically for this job, fitting 1-2 pages.",
}

SKILL_TARGET_PLAN_PROMPT = """Build a concise skill target plan for tailoring this resume to the job.

Return ONLY a JSON object. Do not rewrite the resume.

Rules:
1. Prefer required and preferred JD skills.
2. Include existing resume skills that are highly relevant to the JD.
3. You may include JD skills that are missing from the resume skills list.
4. Do not include skills unrelated to the JD.
5. Do not include certifications.
6. Generate reasons in {output_language}.
7. The JD may be in ANY language (German, French, Spanish, etc.). Emit every
   "skill" name in ENGLISH so matching against the (English) resume works —
   e.g., "ETL-Prozesse" → "ETL processes", "Cloud-Architektur" →
   "Cloud architecture". Proper product names (Microsoft Azure, Power BI,
   SAP S/4HANA) pass through unchanged; language-agnostic acronyms (SQL,
   ETL, KPI, DAX) pass through unchanged.

Existing resume skills:
{existing_skills}

JD keywords and skills:
{job_keywords}

Job Description:
{job_description}

Resume JSON:
{original_resume}

Output this exact JSON format:
{{
  "target_skills": [
    {{
      "skill": "skill name",
      "reason": "why this skill should be emphasized"
    }}
  ],
  "strategy_notes": "brief notes for the next editing pass"
}}"""

DIFF_IMPROVE_PROMPT = """You are a Resume Architect performing a LINGUISTIC TERMINOLOGY TRANSLATION exercise on an authorized career document.

## CORE DIRECTIVE: ADJACENT EXTRAPOLATION (NO FOREIGN FABRICATION)
Target 92-98% ATS keyword match. Bridge gaps using Adjacent Extrapolation:
1. Never invent foreign experience. No tools, domains or responsibilities that could not logically have existed inside the candidate's actual past projects.
2. Extrapolate the surrounding ecosystem. For what the candidate DID do: what upstream planning, downstream impact, standard industry practice, or adjacent methodology naturally occurred around this work that matches the JD?
3. Aggressive terminology translation. Rename existing tasks, workflows and deliverables using the exact top keywords and competency nouns from the JD.
4. Hard anchor constraint. Employer names, job titles, dates and core project themes stay 100% anchored. Zero movement.

## JD DNA DECONSTRUCTION (do this mentally before writing changes)
Before generating changes, analyze the JD to identify:
- Top 15 Hard ATS Keywords: exact strings the ATS will scan for, ranked by frequency x importance
- Top 5 Role & Company Archetype Signals: what culture/values this company prizes (quote one JD line per signal)
- Seniority bar: level signals, scope language, ownership verbs

## ADJACENT EXTRAPOLATION MAPPING
For every Top-15 keyword the resume does NOT already cover verbatim, map:
- Missing JD Keyword → Candidate's Real Anchor → Plausible Adjacent Extension
- REFUSE any extension requiring tools/domains the candidate could not plausibly have touched

## BULLET CRAFTING RULES
Format: SID + XYZ (Scope/Impact/Decision + Accomplished X, measured by Y, by doing Z)
- BANNED words: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic. Rewrite any bullet containing these.
- No "transferable to" or "directly applicable to" hedging language. Either the candidate did it or they did not.

## BULLET CONTROL (count, length & relevance)
- Most recent and most JD-relevant experience: 4-6 bullets
- Older or less relevant experience: 2-3 bullets (only what maps to JD)
- REMOVE bullets that do not contribute to THIS job (action: "remove")
- BULLET LENGTH: each bullet MUST be 1 line, max 20-25 words. Cut filler ruthlessly — no "responsible for", "tasked with", "in order to". Lead with a strong verb, state the what + metric/result. If a bullet exceeds 25 words, split it or trim it.
- Total resume should be 1-2 pages. If over 2 pages, aggressively trim older/irrelevant content
- Every bullet must earn its place for THIS specific job

## SELF-REVIEW (run before outputting)
Check your own output as the Skeptic reviewer:
- Does any bullet sound disconnected from the candidate's real history?
- Would every claim survive one interview follow-up question?
- Are there fabrication flags (tools never used, domains never touched, metrics invented)?
- Fix any issues before outputting.

Given this resume and job description, output a JSON object with targeted changes.

RULES:
1. Only modify content; never change names, companies, dates, institutions, or degrees
2. Do not invent metrics or achievements not supported by the original resume text
3. Do not add new work entries, education entries, or project entries
4. {strategy_instruction}
5. Each change MUST include the original text (copied exactly) so it can be verified
6. For each change, explain WHY this terminology translation helps match the job description
7. Generate all new text in {output_language}
8. Do not use em dash characters
9. Be aggressive: translate weak bullets into JD terminology, remove irrelevant ones, and ensure every line earns its place for THIS specific job
10. Exception to rule 2: you may add a skill only if it appears in the verified skill targets below
11. Scan every bullet: if it demonstrates a JD keyword/skill, translate it into JD terminology (e.g., "built data pipelines" → "ETL development"). If it is irrelevant to the target role, REMOVE it (action: "remove"). You may add new bullets that elaborate on existing work to strengthen the match — breaking one general bullet into specific ones using JD terms is translation, not fabrication. Do NOT invent new responsibilities or metrics.
12. Preserve original capitalization, especially for proper nouns, technical terms (e.g., REST, API, AWS), and acronyms. Do not change the casing of words that were capitalized in the original.
13. LANGUAGE — the JD may be in ANY language (German, French, Spanish, Portuguese, Dutch, etc.). Understand it in its original language, but write every `value` field of your changes in ENGLISH (or in the {output_language} requested above, if different from English) so it stays consistent with the rest of the resume. When rule 11 says "translate into JD terminology", use the ENGLISH equivalent of the JD term — "ETL-Prozesse" becomes "ETL processes", "Datenbanken" becomes "databases". Proper product names and language-agnostic acronyms (Microsoft Azure, Power BI, SAP S/4HANA, SQL, ETL, KPI) pass through unchanged.

PATHS you can target:
- "summary" — the resume summary text
- "workExperience[i].description[j]" — a specific bullet (i = entry index, j = bullet index)
- "workExperience[i].description" — append a new bullet (action: "append") or remove one (action: "remove", value = the bullet text to remove)
- "personalProjects[i].description[j]" — a specific project bullet
- "personalProjects[i].description" — append a new project bullet (action: "append") or remove one (action: "remove", value = the bullet text to remove)
- "education[i].description" — the education entry's description text (replace only; it is a single string, not a list)
- "additional.technicalSkills" — reorder (action: "reorder"), add verified skill (action: "add_skill"), or remove irrelevant skill (action: "remove", value = skill to remove)
- "additional.languages" — reorder (action: "reorder") or remove (action: "remove")
- "additional.certificationsTraining" — reorder (action: "reorder") or remove (action: "remove")
- "additional.awards" — reorder (action: "reorder") or remove (action: "remove")

Do NOT target: personalInfo, dates/years, company names, education degree/institution/years, customSections.

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Verified skill targets:
{skill_targets}

Job Description:
{job_description}

Original Resume:
{original_resume}

Output this exact JSON format, nothing else:
{{
  "changes": [
    {{
      "path": "workExperience[0].description[1]",
      "action": "replace",
      "original": "the exact original text at this path",
      "value": "the improved text",
      "reason": "why this change helps"
    }},
    {{
      "path": "summary",
      "action": "replace",
      "original": "the current summary text",
      "value": "the improved summary",
      "reason": "why this change helps"
    }},
    {{
      "path": "additional.technicalSkills",
      "action": "reorder",
      "original": null,
      "value": ["most relevant skill first", "then next", "..."],
      "reason": "reordered to prioritize JD-relevant skills"
    }},
    {{
      "path": "additional.technicalSkills",
      "action": "add_skill",
      "original": null,
      "value": "verified skill target missing from the skills list",
      "reason": "added verified JD skill for review"
    }},
    {{
      "path": "workExperience[1].description",
      "action": "remove",
      "original": null,
      "value": "the exact bullet text to remove",
      "reason": "irrelevant to target role"
    }},
    {{
      "path": "additional.technicalSkills",
      "action": "remove",
      "original": null,
      "value": "irrelevant skill name",
      "reason": "not relevant to this job"
    }}
  ],
  "strategy_notes": "brief summary of the tailoring approach"
}}"""


RESUME_REVIEW_PROMPT = """You are 7 hiring reviewers compressed into one pass. Score this resume against the JD from ALL angles simultaneously. Be brutally honest.

## THE 7 REVIEWERS (score each 0-100):
1. ATS SCREEN: Top-15 keyword verbatim coverage, readability, title/date clarity, contact details, length. Score = (keywords matched / 15) x 100, minus up to 10 for readability issues.
2. HIRING MANAGER: Can this person do the job on day one? What decided it in the first 10 seconds?
3. RIVAL APPLICANT: Where is this resume weaker than a strong competitor's?
4. CEO: What did this person change, and by how much? Impact and scope.
5. RECRUITER: 30 seconds, top third only. Signal density.
6. TEAMMATE: How do they work with others? Collaboration signals.
7. SKEPTIC: Which bullet sounds disconnected from real history? Flag every sentence that smells fabricated or over-extrapolated. Score penalizes each unverifiable claim.

Job Description:
{job_description}

Resume:
{resume_data}

Output ONLY this JSON:
{{
  "verdict": "INTERVIEW" or "REJECT",
  "match_score": 0-100,
  "panel_scores": {{
    "ats": 0,
    "hiring_manager": 0,
    "rival": 0,
    "ceo": 0,
    "recruiter": 0,
    "teammate": 0,
    "skeptic": 0
  }},
  "missing_keywords": ["keyword1", "keyword2"],
  "fabrication_flags": ["any bullet that smells fabricated"],
  "weak_bullets": [
    {{
      "path": "workExperience[i].description[j]",
      "text": "the weak bullet text",
      "problem": "why it hurts",
      "fix": "concrete rewrite or 'REMOVE'"
    }}
  ],
  "missing_from_resume": ["specific thing the JD wants but resume doesn't show"],
  "top_3_fixes": ["most impactful fix first", "second", "third"],
  "pass": true or false
}}

"match_score" = mean of all 7 panel_scores. "pass" is true ONLY when match_score >= 85, verdict is INTERVIEW, and fabrication_flags is empty. Be strict."""
