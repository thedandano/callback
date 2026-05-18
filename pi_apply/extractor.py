"""Resume text extraction — PDF, DOCX, TXT. Pure I/O, no scoring logic."""

from __future__ import annotations

import re
from pathlib import Path

from pi_apply.section_map import (
    ContactInfo,
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    SectionMap,
    SkillsSection,
)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# Section-map extraction
# ---------------------------------------------------------------------------

_KNOWN_SECTIONS: dict[str, str] = {
    "summary": "summary",
    "objective": "summary",
    "profile": "summary",
    "skills": "skills",
    "skills & abilities": "skills",
    "technologies": "skills",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "projects": "projects",
    "education": "education",
    "certifications": "certifications",
    "awards": "awards",
    "contact": "contact",
    "publications": "certifications",
}

_BULLET_RE = re.compile(r"^(?:[\-\•\*]|\d+[\.)])")
_MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)
_DATE_RE = re.compile(
    r"\b(?:" + "|".join(_MONTHS) + r")\w*\b|\b\d{4}\b|\bpresent\b",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}\b|\b\d{4}\b)"
    r"\s*[-–—]\s*"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}\b|\b\d{4}\b|\bpresent\b)",
    re.IGNORECASE,
)


def _clean_header_text(line: str) -> str | None:
    """Return clean header text or None if line can't be a header."""
    stripped = line.strip()
    if not stripped or len(stripped) > 40 or _BULLET_RE.match(stripped):
        return None
    return stripped.rstrip(":").strip()


def _canonical_header(line: str) -> str | None:
    """Return canonical section key if *line* is a section header, else None."""
    clean = _clean_header_text(line)
    if clean is None:
        return None
    lower = clean.lower()
    if lower in _KNOWN_SECTIONS:
        return _KNOWN_SECTIONS[lower]
    return None


def _group_by_section(lines: list[str]) -> dict[str, list[str]]:
    """Split lines into a mapping of canonical section → raw lines."""
    groups: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"
    for line in lines:
        key = _canonical_header(line)
        if key is not None:
            current = key
            if current not in groups:
                groups[current] = []
        else:
            groups[current].append(line)
    return groups


def _parse_summary(raw: list[str]) -> str | None:
    parts = [ln.strip() for ln in raw if ln.strip()]
    return " ".join(parts) if parts else None


def _parse_preamble_summary(raw: list[str], contact: ContactInfo) -> str | None:
    parts: list[str] = []
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == contact.name:
            continue
        if contact.email and contact.email in stripped:
            continue
        if contact.linkedin and contact.linkedin in stripped:
            continue
        parts.append(stripped)
    return "\n".join(parts) if parts else None


def _parse_skills(raw: list[str]) -> SkillsSection:
    flat: list[str] = []
    categorized: dict[str, list[str]] = {}
    current_category: str | None = None
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            cat, _, rest = stripped.partition(":")
            current_category = cat.strip()
            items = [s.strip() for s in rest.split(",") if s.strip()]
            categorized[current_category] = items
        else:
            tokens = [s.strip() for s in stripped.split(",") if s.strip()]
            if current_category is not None:
                categorized.setdefault(current_category, []).extend(tokens)
            else:
                flat.extend(tokens)
    return SkillsSection(flat=flat, categorized=categorized)


def _is_entry_header(line: str) -> bool:
    """True if *line* looks like an experience or project entry header."""
    stripped = line.strip()
    if not stripped or _BULLET_RE.match(stripped):
        return False
    if _canonical_header(line) is not None:
        return False
    return bool(_DATE_RANGE_RE.search(stripped)) or "|" in stripped


def _extract_dates(text: str) -> tuple[str | None, str | None]:
    m = _DATE_RANGE_RE.search(text)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _parse_entry_header(line: str) -> tuple[str, str, str | None, str | None]:
    """Return (company, role, start_date, end_date) from a job header line."""
    stripped = line.strip()
    start, end = _extract_dates(stripped)
    # Remove the date portion for company/role splitting
    clean = _DATE_RANGE_RE.sub("", stripped).strip(" |–—-").strip()
    if "|" in clean:
        parts = [p.strip() for p in clean.split("|")]
        company = parts[0] if len(parts) > 0 else clean
        role = parts[1] if len(parts) > 1 else ""
    elif "–" in clean or "—" in clean:
        parts = re.split(r"[–—]", clean, maxsplit=1)
        company = parts[0].strip()
        role = parts[1].strip() if len(parts) > 1 else ""
    else:
        company = clean
        role = ""
    return company, role, start, end


def _parse_experience(raw: list[str]) -> list[ExperienceEntry]:  # noqa: C901
    entries: list[ExperienceEntry] = []
    current: ExperienceEntry | None = None
    pending_company: str | None = None
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_entry_header(line):
            company, role, start, end = _parse_entry_header(line)
            if pending_company and not role:
                role = company
                company = pending_company
            pending_company = None
            current = ExperienceEntry(company=company, role=role, start_date=start, end_date=end)
            entries.append(current)
        elif _BULLET_RE.match(stripped):
            bullet = re.sub(r"^[\-\•\*]\s*", "", stripped)
            if current is None:
                current = ExperienceEntry(company=pending_company or "Unknown", role="")
                entries.append(current)
                pending_company = None
            current.bullets.append(bullet)
        else:
            if current is None:
                pending_company = stripped
            elif current.bullets:
                current.bullets[-1] = f"{current.bullets[-1]} {stripped}"
    return entries


def _parse_projects(raw: list[str]) -> list[ProjectEntry]:  # noqa: C901
    entries: list[ProjectEntry] = []
    current: ProjectEntry | None = None
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if _BULLET_RE.match(stripped):
            bullet = re.sub(r"^[\-\•\*]\s*", "", stripped)
            if current is None:
                current = ProjectEntry(name="Unknown")
                entries.append(current)
            current.bullets.append(bullet)
        elif current is not None and current.bullets:
            current.bullets[-1] = f"{current.bullets[-1]} {stripped}"
        elif current is None or (current.description is not None and _is_new_project(stripped)):
            current = ProjectEntry(name=stripped)
            entries.append(current)
        elif current.description is None:
            current.description = stripped
        else:
            current.bullets.append(stripped)
    return entries


def _is_new_project(line: str) -> bool:
    """True if *line* likely starts a new project (not a description continuation)."""
    # Short lines or lines without lowercase likely to be names
    stripped = line.strip()
    if not stripped:
        return False
    words = stripped.split()
    has_upper_start = any(w[0].isupper() or not w[0].isalpha() for w in words if w)
    return has_upper_start or len(words) <= 3


def _parse_education(raw: list[str]) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    institution: str | None = None
    for line in raw:
        stripped = line.strip()
        if not stripped:
            if institution:
                entries.append(EducationEntry(institution=institution))
                institution = None
            continue
        if institution is None:
            institution = stripped
        else:
            entries.append(EducationEntry(institution=institution, degree=stripped))
            institution = None
    if institution:
        entries.append(EducationEntry(institution=institution))
    return entries


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"[\+\(]?[\d\s\(\)\-\.]{7,15}\d")
_URL_RE = re.compile(r"https?://\S+")


def _process_url_line(stripped: str) -> tuple[str | None, str | None]:
    """Return (linkedin, website) found in stripped, both may be None."""
    url_m = _URL_RE.search(stripped)
    if url_m:
        url = url_m.group(0)
        return (url, None) if "linkedin.com" in url else (None, url)
    if "linkedin.com" in stripped.lower():
        li_m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com\S*", stripped, re.IGNORECASE)
        if li_m:
            return li_m.group(0), None
    return None, None


def _extract_phone_candidate(stripped: str) -> str | None:
    """Return phone string if a valid candidate is found, else None."""
    ph = _PHONE_RE.search(stripped)
    if not ph:
        return None
    candidate = ph.group(0).strip()
    return candidate if len(re.sub(r"\D", "", candidate)) >= 7 else None


def _extract_location_from_contact_line(stripped: str) -> str | None:
    if "|" not in stripped:
        return None
    for part in (p.strip() for p in stripped.split("|")):
        if (
            part
            and part.count(",") == 1
            and len(part) <= 40
            and ":" not in part
            and "@" not in part
            and "linkedin.com" not in part.lower()
            and _extract_phone_candidate(part) is None
        ):
            return part
    return None


def _phase1_classify(
    lines: list[str],
) -> tuple[str | None, str | None, str | None, str | None, set[int], set[int], set[int]]:
    """Classify each line as email/URL/phone and extract first-found values."""
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    website: str | None = None
    email_lines: set[int] = set()
    phone_lines: set[int] = set()
    url_lines: set[int] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        em = _EMAIL_RE.search(stripped)
        if em:
            email_lines.add(i)
            email = email or em.group(0)
        lin, web = _process_url_line(stripped)
        if lin or web:
            url_lines.add(i)
            linkedin = linkedin or lin
            website = website or web
        if i not in email_lines:
            phone_val = _extract_phone_candidate(stripped)
            if phone_val:
                phone_lines.add(i)
                phone = phone or phone_val
    return email, phone, linkedin, website, email_lines, phone_lines, url_lines


def _phase2_find_name(lines: list[str], pre_classified: set[int]) -> tuple[str, int | None]:
    """Return (name, name_idx) — first non-empty unclassified line."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and i not in pre_classified:
            return stripped, i
    return "", None


def _phase3_find_location(
    lines: list[str], email_lines: set[int], url_lines: set[int], name_idx: int | None
) -> str | None:
    """Return first city/state-shaped line, never the name line."""
    location: str | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            stripped
            and i not in email_lines
            and i not in url_lines
            and i != name_idx
            and stripped.count(",") == 1
            and len(stripped) <= 40
            and ":" not in stripped
            and "@" not in stripped
            and not (stripped == stripped.upper() and any(c.isalpha() for c in stripped))
            and location is None
        ):
            location = stripped
    return location


def _parse_contact_info(lines: list[str]) -> ContactInfo:
    """Extract ContactInfo fields from the first lines of a resume header.

    Three-phase approach: classify email/URL/phone → claim name (first
    unclassified line) → classify location, never stealing the name line.
    """
    email, phone, linkedin, website, email_lines, phone_lines, url_lines = _phase1_classify(lines)
    pre_classified = email_lines | phone_lines | url_lines
    name, name_idx = _phase2_find_name(lines, pre_classified)
    contact_line_location = next(
        (
            loc
            for line in lines
            if (loc := _extract_location_from_contact_line(line.strip())) is not None
        ),
        None,
    )
    location = contact_line_location or _phase3_find_location(
        lines,
        email_lines,
        url_lines,
        name_idx,
    )
    return ContactInfo(
        name=name,
        email=email,
        phone=phone,
        location=location,
        linkedin=linkedin,
        website=website,
    )


def extract_sections(text: str) -> SectionMap:
    """Parse resume plain text into a structured SectionMap."""
    lines = text.splitlines()
    groups = _group_by_section(lines)

    contact = _parse_contact_info(lines[:15])
    summary = _parse_summary(groups.get("summary", [])) or _parse_preamble_summary(
        groups.get("_preamble", []), contact
    )
    skills = _parse_skills(groups.get("skills", []))
    experience = _parse_experience(groups.get("experience", []))
    projects = _parse_projects(groups.get("projects", []))
    education = _parse_education(groups.get("education", []))

    certifications = [ln.strip() for ln in groups.get("certifications", []) if ln.strip()]
    awards = [ln.strip() for ln in groups.get("awards", []) if ln.strip()]

    section_map = SectionMap(
        summary=summary,
        skills=skills,
        experience=experience,
        projects=projects,
        education=education,
        contact=contact,
        certifications=certifications,
        awards=awards,
    )

    if section_map.contact is None or section_map.contact.name == "":
        raise ValueError("extract_sections: could not determine candidate name from resume")

    return section_map


def extract(path: str | Path) -> str:
    """Extract plain text from a resume file.

    Supports .pdf, .docx, and .txt.
    Raises FileNotFoundError, ValueError (bad format / too large), or RuntimeError.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"extractor: file not found: {p}")

    size = p.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"extractor: file too large ({size} bytes, max {MAX_FILE_BYTES})")

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(p)
    if suffix in (".docx", ".doc"):
        return _extract_docx(p)
    if suffix == ".txt":
        return p.read_text(encoding="utf-8").strip()

    raise ValueError(f"extractor: unsupported format {suffix!r} — expected .pdf, .docx, or .txt")


def _extract_pdf(path: Path) -> str:
    from collections import defaultdict

    import pdfplumber

    def _normalize_pdf_word(text: str) -> str:
        # Some embedded fonts emit bullet glyphs as private-use codepoints.
        # Normalize them so downstream bullet parsing remains stable.
        return "".join("•" if 0xE000 <= ord(ch) <= 0xF8FF else ch for ch in text)

    page_texts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # x_tolerance=2 handles PDFs with tight inter-word spacing (~2.6px)
            # that extract_text()'s default x_tolerance=3 merges into one token.
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
            if not words:
                continue
            lines_by_y: dict[int, list] = defaultdict(list)
            for w in words:
                y_key = round(w["top"] / 3) * 3
                lines_by_y[y_key].append(w)
            lines: list[str] = []
            for y in sorted(lines_by_y):
                row = sorted(lines_by_y[y], key=lambda w: w["x0"])
                lines.append(" ".join(_normalize_pdf_word(w["text"]) for w in row))
            page_texts.append("\n".join(lines))
    text = "\n".join(page_texts).strip()
    if not text:
        raise RuntimeError(f"extractor: PDF yielded no text: {path}")
    return text


def _extract_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not text:
        raise RuntimeError(f"extractor: DOCX yielded no text: {path}")
    return text
