"""Minimal DOCX renderers for export.

Two entry points:
    - render_cv_docx(resume_data, out_path): writes a Word version of the
      structured ResumeData. Simple, portable layout (no template-system
      tie-in) so recruiters can open it in Word / Google Docs / Pages.
    - render_cover_letter_docx(text, out_path): writes a cover letter from
      plain text, one blank-line-delimited block per paragraph.

Design notes:
    * We deliberately do NOT try to mirror the fancy resume templates here —
      a lossy DOCX of a Swiss-grid layout is worse than a clean, readable
      plain DOCX. Recruiters who want pixel-perfect fidelity use the PDF.
    * python-docx (1.2.0) is already in pyproject — no new dep.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    # Force black heading color — default blue theme ink reads as "AI slop"
    # to a hiring manager; the whole doc stays monochrome for seriousness.
    for run in h.runs:
        run.font.color.rgb = None


def _add_bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(text, style="List Bullet")
    p.paragraph_format.space_after = Pt(2)


def _as_list(x: Any) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _joined(xs: Any, sep: str = " · ") -> str:
    return sep.join(str(x).strip() for x in _as_list(xs) if str(x).strip())


def _personal_header(doc: Document, pi: dict) -> None:
    name = (pi.get("name") or "").strip()
    if name:
        h = doc.add_heading(name, level=0)
        for run in h.runs:
            run.font.color.rgb = None
    title = (pi.get("title") or "").strip()
    if title:
        p = doc.add_paragraph()
        r = p.add_run(title)
        r.italic = True

    # One contact line, comma-separated.
    parts: list[str] = []
    for k in ("location", "email", "phone", "website", "linkedin", "github"):
        v = (pi.get(k) or "").strip()
        if v:
            parts.append(v)
    if parts:
        p = doc.add_paragraph(" | ".join(parts))
        p.paragraph_format.space_after = Pt(6)


def _work_experience(doc: Document, items: list[dict]) -> None:
    if not items:
        return
    _add_heading(doc, "Work Experience", level=1)
    for item in items:
        role = (item.get("title") or item.get("role") or "").strip()
        company = (item.get("company") or "").strip()
        location = (item.get("location") or "").strip()
        dates = (item.get("dates") or item.get("date") or "").strip()

        header_bits = [b for b in (role, company) if b]
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(" — ".join(header_bits) or "Role")
        r.bold = True

        meta_bits = [b for b in (location, dates) if b]
        if meta_bits:
            p = doc.add_paragraph(" | ".join(meta_bits))
            p.paragraph_format.space_after = Pt(2)

        bullets = _as_list(item.get("description") or item.get("responsibilities") or item.get("bullets"))
        for b in bullets:
            if str(b).strip():
                _add_bullet(doc, str(b).strip())


def _education(doc: Document, items: list[dict]) -> None:
    if not items:
        return
    _add_heading(doc, "Education", level=1)
    for item in items:
        degree = (item.get("degree") or "").strip()
        institution = (item.get("institution") or item.get("school") or "").strip()
        dates = (item.get("dates") or item.get("date") or "").strip()
        location = (item.get("location") or "").strip()

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(" — ".join(x for x in (degree, institution) if x) or "Education")
        r.bold = True
        meta_bits = [x for x in (location, dates) if x]
        if meta_bits:
            mp = doc.add_paragraph(" | ".join(meta_bits))
            mp.paragraph_format.space_after = Pt(2)

        for b in _as_list(item.get("description") or item.get("details")):
            if str(b).strip():
                _add_bullet(doc, str(b).strip())


def _projects(doc: Document, items: list[dict]) -> None:
    if not items:
        return
    _add_heading(doc, "Projects", level=1)
    for item in items:
        name = (item.get("name") or item.get("title") or "").strip()
        tech = _joined(item.get("technologies") or item.get("tech"))
        dates = (item.get("dates") or item.get("date") or "").strip()

        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(name or "Project")
        r.bold = True
        meta_bits = [x for x in (tech, dates) if x]
        if meta_bits:
            mp = doc.add_paragraph(" | ".join(meta_bits))
            mp.paragraph_format.space_after = Pt(2)

        for b in _as_list(item.get("description") or item.get("bullets")):
            if str(b).strip():
                _add_bullet(doc, str(b).strip())


def _additional(doc: Document, section: dict) -> None:
    fields = [
        ("technicalSkills", "Technical Skills"),
        ("languages", "Languages"),
        ("certificationsTraining", "Certifications & Training"),
        ("awards", "Awards"),
    ]
    rows: list[tuple[str, str]] = []
    for key, label in fields:
        items = section.get(key) or []
        # Grouped skills (new): list of {label, items} blocks.
        if items and isinstance(items[0], dict) and "items" in items[0]:
            for block in items:
                sub_label = (block.get("label") or label).strip()
                sub_items = _joined(block.get("items") or [], sep=", ")
                if sub_items:
                    rows.append((sub_label, sub_items))
        else:
            text = _joined(items, sep=", ")
            if text:
                rows.append((label, text))

    # Extra grouped blocks appended by the user
    for block in section.get("extraBlocks") or []:
        lbl = (block.get("label") or "").strip()
        items_txt = _joined(block.get("items") or [], sep=", ")
        if lbl and items_txt:
            rows.append((lbl, items_txt))

    if not rows:
        return
    _add_heading(doc, "Skills & Awards", level=1)
    for label, text in rows:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        lr = p.add_run(f"{label}: ")
        lr.bold = True
        p.add_run(text)


def _custom_sections(doc: Document, custom: dict, meta: list[dict]) -> None:
    # Render custom sections in the order defined by sectionMeta; skip
    # hidden ones so the Word output matches the UI's visibility toggles.
    seen: set[str] = set()
    order: list[tuple[str, str]] = []
    for m in meta or []:
        if not m or m.get("hidden"):
            continue
        key = m.get("key") or ""
        if key in custom and key not in seen:
            order.append((key, m.get("displayName") or key))
            seen.add(key)
    for key, cs in custom.items():
        if key not in seen:
            order.append((key, (cs or {}).get("displayName") or key))

    for key, display in order:
        cs = custom.get(key) or {}
        kind = cs.get("sectionType")
        text = cs.get("text")
        items = cs.get("items") or cs.get("strings") or []
        blocks = cs.get("blocks") or []

        if not (text or items or blocks):
            continue
        _add_heading(doc, display, level=1)

        if text:
            doc.add_paragraph(str(text).strip())
        for b in items:
            if isinstance(b, dict):
                headline = (b.get("title") or b.get("heading") or "").strip()
                # Description can be either a single string OR a list of
                # bullet strings depending on the template. Normalise both
                # into "lines to render as paragraphs/bullets".
                raw_desc = b.get("description") or b.get("text") or ""
                if headline:
                    p = doc.add_paragraph()
                    r = p.add_run(headline)
                    r.bold = True
                if isinstance(raw_desc, list):
                    for line in raw_desc:
                        if str(line).strip():
                            _add_bullet(doc, str(line).strip())
                elif str(raw_desc).strip():
                    doc.add_paragraph(str(raw_desc).strip())
            else:
                _add_bullet(doc, str(b).strip())
        for block in blocks:
            lbl = (block.get("label") or "").strip()
            block_items = block.get("items") or []
            if lbl:
                p = doc.add_paragraph()
                r = p.add_run(lbl)
                r.bold = True
            for it in block_items:
                _add_bullet(doc, str(it).strip())


def render_cv_docx(resume_data: dict, out_path: str | Path) -> Path:
    """Render a ResumeData dict to a .docx file at out_path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Pt(36)  # ~0.5 in
        section.left_margin = section.right_margin = Pt(54)  # ~0.75 in

    _personal_header(doc, resume_data.get("personalInfo") or {})

    summary = (resume_data.get("summary") or "").strip()
    if summary:
        _add_heading(doc, "Summary", level=1)
        doc.add_paragraph(summary)

    _work_experience(doc, _as_list(resume_data.get("workExperience")))
    _education(doc, _as_list(resume_data.get("education")))
    _projects(doc, _as_list(resume_data.get("projects")))
    _additional(doc, resume_data.get("additional") or {})
    _custom_sections(doc, resume_data.get("customSections") or {}, resume_data.get("sectionMeta") or [])

    doc.save(str(out))
    return out


def render_cover_letter_docx(text: str, out_path: str | Path) -> Path:
    """Render a plain-text cover letter to .docx — one paragraph per
    blank-line-delimited block."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Pt(54)
        section.left_margin = section.right_margin = Pt(72)

    # One paragraph per blank-line-delimited block; preserves intentional
    # paragraph breaks without turning single newlines into visible breaks.
    for block in (text or "").strip().split("\n\n"):
        stripped = block.strip()
        if not stripped:
            continue
        p = doc.add_paragraph(stripped)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(10)

    doc.save(str(out))
    return out
