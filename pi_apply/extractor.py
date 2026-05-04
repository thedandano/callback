"""Resume text extraction — PDF, DOCX, TXT. Pure I/O, no scoring logic."""

from __future__ import annotations

import re
from pathlib import Path

from pi_apply.section_map import (
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

_BULLET_RE = re.compile(r"^[\-\•\*\d]")
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
    r"(?:" + "|".join(_MONTHS) + r"|\d{4}|present)",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}|\d{4})"
    r"\s*[-–—]\s*"
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}|\d{4}|present)",
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
    # All-caps (at least one alpha char) → use lowercased text as key
    if clean == clean.upper() and any(c.isalpha() for c in clean):
        return lower
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


def _parse_skills(raw: list[str]) -> SkillsSection:
    flat: list[str] = []
    categorized: dict[str, list[str]] = {}
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if ":" in stripped:
            cat, _, rest = stripped.partition(":")
            items = [s.strip() for s in rest.split(",") if s.strip()]
            categorized[cat.strip()] = items
        else:
            tokens = [s.strip() for s in stripped.split(",") if s.strip()]
            flat.extend(tokens)
    return SkillsSection(flat=flat, categorized=categorized)


def _is_entry_header(line: str) -> bool:
    """True if *line* looks like an experience or project entry header."""
    stripped = line.strip()
    if not stripped or _BULLET_RE.match(stripped):
        return False
    if _canonical_header(line) is not None:
        return False
    return bool(_DATE_RE.search(stripped)) or "|" in stripped or "–" in stripped


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


def _parse_experience(raw: list[str]) -> list[ExperienceEntry]:
    entries: list[ExperienceEntry] = []
    current: ExperienceEntry | None = None
    for line in raw:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_entry_header(line):
            company, role, start, end = _parse_entry_header(line)
            current = ExperienceEntry(company=company, role=role, start_date=start, end_date=end)
            entries.append(current)
        elif _BULLET_RE.match(stripped):
            bullet = re.sub(r"^[\-\•\*]\s*", "", stripped)
            if current is None:
                current = ExperienceEntry(company="Unknown", role="")
                entries.append(current)
            current.bullets.append(bullet)
        else:
            if current is None:
                current = ExperienceEntry(company=stripped, role="")
                entries.append(current)
    return entries


def _parse_projects(raw: list[str]) -> list[ProjectEntry]:
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


def extract_sections(text: str) -> SectionMap:
    """Parse resume plain text into a structured SectionMap."""
    lines = text.splitlines()
    groups = _group_by_section(lines)

    summary = _parse_summary(groups.get("summary", []))
    skills = _parse_skills(groups.get("skills", []))
    experience = _parse_experience(groups.get("experience", []))
    projects = _parse_projects(groups.get("projects", []))
    education = _parse_education(groups.get("education", []))

    contact_lines = [ln.strip() for ln in groups.get("contact", []) if ln.strip()]
    contact = "\n".join(contact_lines) if contact_lines else None

    certifications = [ln.strip() for ln in groups.get("certifications", []) if ln.strip()]
    awards = [ln.strip() for ln in groups.get("awards", []) if ln.strip()]

    return SectionMap(
        summary=summary,
        skills=skills,
        experience=experience,
        projects=projects,
        education=education,
        contact=contact,
        certifications=certifications,
        awards=awards,
    )


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
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    text = "\n".join(pages).strip()
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
