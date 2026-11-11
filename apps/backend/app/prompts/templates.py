"""LLM prompt templates for resume processing."""

# Language code to full name mapping
LANGUAGE_NAMES = {
    "en": "English",
    "de": "German",
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

AGGRESSIVE_TRUTHFULNESS_TEMPLATE = """LINGUISTIC TERMINOLOGY TRANSLATION RULES — this is an authorized career document. The candidate has approved this translation exercise for maximum JD alignment.

CORE PRINCIPLE: AGGRESSIVE ADJACENT EXTRAPOLATION
The candidate's real work ecosystem is MUCH broader than what they wrote down. For every role, think about:
- Upstream: planning, requirements gathering, stakeholder alignment, architecture decisions
- Core: the tools, frameworks, methodologies, and practices standard in that domain
- Downstream: deployment, monitoring, reporting, impact measurement, documentation
- Adjacent: cross-functional collaboration, mentoring, process improvement, compliance

1. TRANSLATE and EXPAND using the JD's exact terminology. Map every candidate experience to JD keywords — use the JD's words, not synonyms.
2. {rule_7}
3. AGGRESSIVELY add JD keywords to the skills section. If the candidate worked in a domain, they can list the standard tools and practices of that domain that appear in the JD. A web developer can list specific frameworks from the JD. A data person can list specific BI tools. A team lead can list stakeholder management, cross-functional collaboration, etc.
4. Reorder all skills and bullets by JD relevance. Remove content irrelevant to this role.
5. Keep employer names, job titles, and date ranges exactly as they appear.
6. Each bullet max 20-25 words. Lead with a strong action verb + JD keyword.
{confirmed_skills_block}
This is professional resume writing — the same discipline used by career consultants. The candidate authorized this translation.
"""

CONSERVATIVE_TRUTHFULNESS_TEMPLATE = """LINGUISTIC TERMINOLOGY TRANSLATION RULES — this is an authorized career document translation exercise:
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
{confirmed_skills_block}
This is the same discipline used by professional resume writers. The candidate authorized this translation.
"""

EXTRAPOLATION_MODE_TEMPLATES = {
    "aggressive": AGGRESSIVE_TRUTHFULNESS_TEMPLATE,
    "conservative": CONSERVATIVE_TRUTHFULNESS_TEMPLATE,
}


def _build_truthfulness_rules(
    rule_7: str,
    confirmed_skills: list[str] | None = None,
    extrapolation_mode: str = "aggressive",
) -> str:
    if confirmed_skills:
        block = "\nThe candidate has CONFIRMED they possess these skills. Add them to the skills section and weave them into relevant bullet points:\n" + ", ".join(confirmed_skills) + "\n"
    else:
        block = ""
    template = EXTRAPOLATION_MODE_TEMPLATES.get(extrapolation_mode, AGGRESSIVE_TRUTHFULNESS_TEMPLATE)
    return template.format(rule_7=rule_7, confirmed_skills_block=block)


AGGRESSIVE_RULE7 = {
    "nudge": "Rephrase existing content to use JD terminology. You may add adjacent skills to the skills section.",
    "keywords": "Rewrite bullets using exact JD keywords. Add new bullets that surface adjacent experience. Add all JD-adjacent skills to the skills section. Remove irrelevant content aggressively.",
    "full": "Maximum extrapolation mode. Rewrite every bullet to directly address JD requirements. Add bullets that elaborate on existing work by surfacing the full ecosystem. Pack the skills section with every JD keyword the candidate's experience is adjacent to. Remove everything irrelevant.",
}

CONSERVATIVE_RULE7 = {
    "nudge": "DO NOT add new bullet points or content - only rephrase existing content",
    "keywords": "You may rephrase, reorder, or REMOVE bullet points to strengthen the match. You may also add bullets that elaborate on existing work. Remove bullets that are irrelevant to the target role.",
    "full": "You may rewrite, remove, reorder, or add bullet points. Remove content irrelevant to the role. Add bullets that elaborate on existing work. Do NOT invent entirely new responsibilities.",
}

CRITICAL_TRUTHFULNESS_RULES_TEMPLATES = AGGRESSIVE_RULE7

CRITICAL_TRUTHFULNESS_RULES = {
    k: _build_truthfulness_rules(v, extrapolation_mode="aggressive")
    for k, v in AGGRESSIVE_RULE7.items()
}


def build_truthfulness_rules_with_skills(
    prompt_id: str,
    confirmed_skills: list[str] | None = None,
    extrapolation_mode: str = "aggressive",
) -> str:
    """Build truthfulness rules with optional confirmed skills and extrapolation mode."""
    rule7_map = AGGRESSIVE_RULE7 if extrapolation_mode == "aggressive" else CONSERVATIVE_RULE7
    rule_7 = rule7_map.get(prompt_id, rule7_map["keywords"])
    return _build_truthfulness_rules(rule_7, confirmed_skills=confirmed_skills, extrapolation_mode=extrapolation_mode)

IMPROVE_RESUME_PROMPT_NUDGE = """Lightly nudge this resume toward the job description. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- Rephrase existing bullets to use JD terminology where the experience is adjacent
- You may add JD-adjacent skills to the skills section
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- Keep proper nouns (names, company names, locations) unchanged
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do not generate descriptions for items that had none.
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- Do not use em dash characters anywhere in the output
- Each bullet max 20-25 words. Cut filler: no "responsible for", "tasked with", "in order to".
- BANNED words: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, utilized, facilitated, endeavored, proactively, holistic, robust, cutting-edge, state-of-the-art. Rewrite any bullet containing these.

Job Description:
{job_description}

Keywords to emphasize (only if already supported by resume content):
{job_keywords}

Original Resume:
{original_resume}

Output in this JSON format:
{schema}"""

IMPROVE_RESUME_PROMPT_KEYWORDS = """Enhance this resume with relevant keywords from the job description using aggressive adjacent extrapolation. Output ONLY the JSON object, no other text.

{critical_truthfulness_rules}

IMPORTANT: Generate ALL text content (summary, descriptions, skills) in {output_language}.
Do NOT include personalInfo in your output - it will be preserved from the original resume.

Rules:
- AGGRESSIVELY weave JD keywords into bullet points using adjacent extrapolation — if the candidate's work naturally touched a JD keyword's domain, use that exact keyword
- Add JD keywords to the skills section whenever the candidate's experience is adjacent (e.g., someone who built web apps can list the specific frameworks from the JD if they are in the same ecosystem)
- Rephrase bullet points to use the EXACT terminology from the JD, not synonyms
- Do NOT change role, industry, or seniority level
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do NOT generate descriptions for items that had none.
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- If resume is non-technical, keep language non-technical while still aligning keywords
- Do NOT use em dash ("—") anywhere in the writing/output, even if it exists, remove it
- Each bullet max 20-25 words. Cut filler: no "responsible for", "tasked with", "in order to".
- Use simple, strong verbs (built, designed, wrote, ran, shipped, created, automated, deployed, tested, integrated). Never repeat the same leading verb within one role.
- BANNED words: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, utilized, facilitated, endeavored, proactively, holistic, robust, cutting-edge, state-of-the-art. Rewrite any bullet containing these.

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
- AGGRESSIVELY rewrite every bullet to use JD terminology. This is maximum extrapolation mode.
- Add bullets that surface the full ecosystem of the candidate's work — upstream planning, downstream impact, adjacent methodologies
- Pack the skills section with every JD keyword the candidate's experience is even remotely adjacent to
- Use simple, strong action verbs (built, designed, wrote, ran, shipped, created, automated, deployed, tested, integrated). Do not repeat the same leading verb within one role.
- Keep proper nouns (names, company names, locations) unchanged
- Translate job titles, descriptions, and skills to {output_language}
- Preserve descriptionStyles arrays and keep them aligned one-to-one with description arrays
- For customSections: preserve exact structure, item count, titles, subtitles, and years. If an item's description is an empty array [] in the original, keep it empty []. Do not generate descriptions for items that had none.
- Improve custom section content the same way as standard sections
- Copy the "years" field values EXACTLY as they appear in the original resume (including any month prefixes like "Jan 2020 - Present"). Do not shorten, reformat, or drop months.
- Calculate and emphasize total relevant experience duration when it matches requirements
- Do not use em dash characters anywhere in the output
- Each bullet max 20-25 words. Cut filler: no "responsible for", "tasked with", "in order to".
- BANNED words: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, utilized, facilitated, endeavored, proactively, holistic, robust, cutting-edge, state-of-the-art. Rewrite any bullet containing these.

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

## FOR ALL COVER LETTERS (English or other non-German JDs):
IMPORTANT: Write in {output_language}.

Job Description:
{job_description}

Candidate Resume (JSON):
{resume_data}

## STRUCTURE (include ALL of these sections):
1. HEADER BLOCK:
   - Candidate full name, address, phone, email (from resume personalInfo)
   - Blank line
   - Date (today's date in locale-appropriate format)
   - Blank line
   - Recipient: Hiring Manager / HR Department name (extract from JD if available)
   - Company name and address (extract from JD)
   - Blank line
   - Subject line: "Re: Application for <Role Title>" (extract role from JD)
   - Blank line
   - Salutation: "Dear Hiring Manager," or "Dear <Name>," if named in JD

2. BODY (3-4 substantial paragraphs, 250-400 words total):
   - Opening paragraph: Hook the hiring pain. Reference ONE specific thing from the JD (product, tech stack, business problem). Not generic excitement. State the role you are applying for.
   - Middle paragraph(s): Pick 2-3 qualifications from resume that DIRECTLY match stated requirements. Translate terminology using exact JD keywords. Be specific — name the tools, the scale, the outcome. Each paragraph should address a different JD requirement cluster.
   - Closing paragraph: Restate fit in one sentence, state availability, provide a simple call to action. No desperate enthusiasm.

3. SIGN-OFF:
   - "Sincerely," (or locale-appropriate equivalent)
   - Candidate full name

## RULES:
- If resume shows career transition, frame the pivot as intentional and relevant
- Extract company name and role from JD. No placeholders like [Company] or [Position].
- Use adjacent extrapolation to connect resume experience to JD requirements
- Tone: Confident peer, not eager applicant. Professional but not stiff.
- Do NOT use em dash anywhere in the output
- BANNED: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, utilized, facilitated, "passionate about", "excited to", "team player", "motivated self-starter", "hit the ground running"

## SELF-REVIEW (before outputting)
- Does every factual claim trace back to the resume?
- Would each claim survive one interview follow-up?
- Is it one page (250-400 words body)?
- Does it have a proper header with To address and subject line?
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

DIFF_STRATEGY_AGGRESSIVE = {
    "nudge": "Make minimal edits. Only rephrase where there is a clear match. Do not add or remove bullet points. Preserve bullet counts.",
    "keywords": "Adjacent Extrapolation mode: for each JD keyword, find the candidate's closest real anchor and translate using JD terminology. Rewrite bullets using exact JD competency nouns — keyword-rich, value-oriented, drop metrics that don't strengthen the bullet for THIS role. Remove bullets with no JD mapping. Reorder skills to prioritize JD matches. Add new bullets that elaborate on existing work by extrapolating the surrounding ecosystem. Bullet control: most recent + most relevant roles get 4-6 bullets; older/less relevant roles get 2-3 bullets; remove anything that does not map to THIS job. Each bullet max 20-25 words — lead with a strong verb, cut all filler. Target 92-98% ATS keyword match.",
    "full": "Maximum Adjacent Extrapolation with full bullet control: rewrite every bullet to directly address JD requirements — keyword-rich, value-oriented, drop metrics that don't strengthen the bullet for THIS role. For each JD requirement, extrapolate the surrounding ecosystem of the candidate's real work. Bullet control: most recent + most relevant roles get 4-6 detailed bullets; older/less relevant roles get 2-3 bullets max; REMOVE any bullet with no JD mapping. Add bullets that elaborate on existing work by surfacing adjacent methodology. Reorder all lists by JD relevance. Each bullet max 20-25 words — lead with a strong verb, cut all filler. Target 95%+ ATS keyword match. The resume should read as if written specifically for this job, fitting 1-2 pages.",
}

DIFF_STRATEGY_CONSERVATIVE = {
    "nudge": "Make minimal edits. Only rephrase where there is a clear match. Do not add or remove bullet points. Preserve bullet counts.",
    "keywords": "Strengthen alignment by weaving in relevant keywords where evidence already exists. You may rephrase bullet points to include keyword phrasing. Do NOT introduce new skills, tools, or certifications not in the resume. Reorder skills to prioritize JD matches. Each bullet max 20-25 words.",
    "full": "Tailor the resume for the job with targeted adjustments. Rephrase bullet points to align with JD phrasing. You may add bullets that elaborate on existing work but do NOT invent entirely new responsibilities. Reorder skills by relevance. Each bullet max 20-25 words.",
}

DIFF_STRATEGY_INSTRUCTIONS = DIFF_STRATEGY_AGGRESSIVE


def get_diff_strategy(prompt_id: str, extrapolation_mode: str = "aggressive") -> str:
    """Get diff strategy instruction based on mode."""
    strategies = DIFF_STRATEGY_AGGRESSIVE if extrapolation_mode == "aggressive" else DIFF_STRATEGY_CONSERVATIVE
    return strategies.get(prompt_id, strategies["keywords"])

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

## CORE DIRECTIVE: MAXIMUM ADJACENT EXTRAPOLATION
This is an authorized linguistic terminology translation exercise. Target 95%+ ATS keyword match.
1. Extrapolate the FULL surrounding ecosystem. For what the candidate did: what upstream planning, downstream impact, standard industry practice, and adjacent methodology naturally occurred around this work? Map ALL of it to JD keywords.
2. Aggressive terminology translation. Rename existing tasks, workflows and deliverables using the exact top keywords and competency nouns from the JD. Use the JD's words, never synonyms.
3. Anchor constraint: Employer names, job titles, and dates stay unchanged.

## JD DNA DECONSTRUCTION (do this mentally before writing changes)
Before generating changes, analyze the JD to identify:
- Top 15 Hard ATS Keywords: exact strings the ATS will scan for, ranked by frequency x importance
- Top 5 Role & Company Archetype Signals: what culture/values this company prizes (quote one JD line per signal)
- Seniority bar: level signals, scope language, ownership verbs

## ADJACENT EXTRAPOLATION MAPPING
For every Top-15 keyword the resume does NOT already cover verbatim, map:
- Missing JD Keyword → Candidate's Closest Anchor → Adjacent Extension
- Be generous — if the candidate worked in the same domain, the keyword is fair game

## BULLET CRAFTING RULES
Format: keyword-rich, value-oriented bullets. Lead with a strong action verb + JD keyword + concrete outcome.
- METRICS ASSESSMENT — for every metric in a bullet, run this two-lens test before keeping it:
  TECHNICAL LENS: Does this number demonstrate a competency the JD asks for? A query optimization time ("reduced p95 latency from 800ms to 120ms") matters for a data engineering role; a generic "improved efficiency by 30%" does not because it says nothing about HOW.
  MANAGEMENT LENS: Does this number signal scope, ownership, or business impact that matches the seniority bar of THIS role? "Managed $4M annual cloud budget" signals senior ownership — keep it for a senior role, drop it for an intern/junior posting where it reads as inflated. "Team of 12" matters for a lead role, is noise for an IC role.
  PLAUSIBILITY LENS: Does this metric sound believable for the candidate's role level, company size, and tenure? Red flags: suspiciously round percentages ("improved by 40%"), impossibly large scope for a junior role ("managed 50-person team" for an intern), vague unverifiable claims ("saved $2M annually"), metrics that repeat the same pattern across multiple bullets ("reduced X by Y%" three times). If a metric fails this lens, REWRITE the bullet without the number — describe WHAT was done with JD keywords instead.
  KEEP the metric if it passes the plausibility lens AND at least one of the two lenses above. DROP it if it fails plausibility OR fails both technical and management lenses — replace with a tighter keyword-rich phrase that shows what was done. A bullet with the right JD keywords and no metric is stronger than one padded with an irrelevant or implausible number.
- METRIC DENSITY: if more than 60% of bullets in one role contain metrics, the role reads as inflated. Thin them out — keep only the 2-3 strongest, most verifiable numbers per role and let the rest speak through JD keywords and concrete actions.
- ACTION VERB RULES:
  1. Use simple, strong, widely understood verbs — the kind every hiring manager reads without pausing: built, designed, wrote, ran, shipped, set up, created, automated, analyzed, configured, deployed, tested, integrated, migrated, refactored, optimized, tracked, documented, resolved, implemented, developed, maintained, defined, delivered, mapped, modeled, trained, parsed, cleaned, validated, generated, connected, extended, reduced, streamlined, consolidated, standardized, published, scheduled, processed, extracted, transformed, loaded.
  2. NEVER repeat the same leading verb within one role's bullets. Scan your output: if two bullets under the same job start with the same verb, rewrite one. Across different roles, occasional repeats are acceptable.
  3. BANNED words: spearheaded, delve, testament, tapestry, seasoned, results-driven, synergy, leveraged, orchestrated, pivotal, dynamic, utilized, facilitated, endeavored, proactively, holistic, robust, cutting-edge, state-of-the-art. Rewrite any bullet containing these.
- No "transferable to" or "directly applicable to" hedging language. Either the candidate did it or they did not.

## BULLET CONTROL (count, length & relevance)
- Most recent and most JD-relevant experience: 4-6 bullets
- Older or less relevant experience: 2-3 bullets (only what maps to JD)
- REMOVE bullets that do not contribute to THIS job (action: "remove")
- BULLET LENGTH: each bullet MUST be 1 line, max 20-25 words. Cut filler ruthlessly — no "responsible for", "tasked with", "in order to". Lead with a strong verb, state the what + metric/result. If a bullet exceeds 25 words, split it or trim it.
- Total resume should be 1-2 pages. If over 2 pages, aggressively trim older/irrelevant content
- Every bullet must earn its place for THIS specific job

## SELF-REVIEW (run before outputting)
- Is every JD keyword present somewhere in the resume (skills, bullets, or summary)?
- Are bullets concise (20-25 words) and keyword-rich?
- Is the skills section packed with JD-relevant terms?

Given this resume and job description, output a JSON object with targeted changes.

RULES:
1. Keep names, companies, dates, institutions, and degrees unchanged
2. {strategy_instruction}
3. Each change MUST include the original text (copied exactly) so it can be verified
4. For each change, explain WHY this terminology translation helps match the JD
5. Generate all new text in {output_language}
6. Do not use em dash characters
7. Be AGGRESSIVE: translate every bullet into JD terminology, remove irrelevant ones, and ensure every line earns its place for THIS specific job
8. You may add skills from the verified skill targets below AND any JD keyword that is adjacent to demonstrated experience
9. Scan every bullet: translate it into JD terminology. If irrelevant to the target role, REMOVE it. Add new bullets that elaborate on existing work — breaking one general bullet into specific ones using JD terms is translation. Surface the full ecosystem of the candidate's work.
10. Preserve original capitalization for proper nouns and technical terms.
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
7. SKEPTIC: Which bullet would be hardest to discuss in an interview? Note areas where the candidate should prepare talking points. Score based on how well the resume tells a coherent story.

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
  "fabrication_flags": [],
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

"match_score" = mean of all 7 panel_scores. "pass" is true when match_score >= 85 and verdict is INTERVIEW. Focus on JD alignment and keyword coverage, not skepticism about adjacent extrapolation — this is a professional terminology translation exercise."""
