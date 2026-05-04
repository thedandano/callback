"""Resume text extraction — PDF, DOCX, TXT. Pure I/O, no scoring logic."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pi_apply.section_map import ExperienceEntry, SectionMap, SkillsSection

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


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


# ---------------------------------------------------------------------------
# Section-map extraction
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^([A-Z][A-Z &/]+)$")
_KNOWN_SECTIONS = {
    "SUMMARY": "summary",
    "PROFESSIONAL SUMMARY": "summary",
    "OBJECTIVE": "summary",
    "SKILLS": "skills",
    "TECHNICAL SKILLS": "skills",
    "CORE COMPETENCIES": "skills",
    "EXPERIENCE": "experience",
    "WORK EXPERIENCE": "experience",
    "PROFESSIONAL EXPERIENCE": "experience",
    "EMPLOYMENT": "experience",
    "PROJECTS": "projects",
    "PROJECT EXPERIENCE": "projects",
    "EDUCATION": "education",
    "CERTIFICATIONS": "certifications",
    "AWARDS": "awards",
    "CONTACT": "contact",
}


def _classify_section(line: str) -> str | None:
    """Return canonical section name for an all-caps header line, or None."""
    stripped = line.strip()
    if not _HEADER_RE.match(stripped):
        return None
    return _KNOWN_SECTIONS.get(stripped.upper())


def _parse_experience_line(line: str) -> tuple[str, str] | None:
    """Return (company, role) if line looks like 'Company | Role | ...'."""
    parts = re.split(r"\s*[|–\-—]\s*", line, maxsplit=1)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return None


def _parse_skills(skills_lines: list[str]) -> SkillsSection:
    """Parse skill lines into flat or categorized SkillsSection."""
    from pi_apply.section_map import SkillsSection

    skills = SkillsSection()
    for sl in skills_lines:
        if ":" in sl:
            cat, _, rest = sl.partition(":")
            items = [i.strip() for i in re.split(r"[,;]", rest) if i.strip()]
            skills.categorized.setdefault(cat.strip(), []).extend(items)
        else:
            items = [i.strip() for i in re.split(r"[,;]", sl) if i.strip()]
            skills.flat.extend(items)
    return skills


def _parse_experience_block(block: list[str]) -> ExperienceEntry:
    """Convert a raw text block into an ExperienceEntry."""
    from pi_apply.section_map import ExperienceEntry

    pair = _parse_experience_line(block[0])
    company = pair[0] if pair else block[0]
    role = pair[1] if pair else ""
    date_match = re.search(r"(\d{4})\s*[–\-—]\s*(\d{4}|Present|Current)", role)
    start = date_match.group(1) if date_match else None
    end = date_match.group(2) if date_match else None
    bullets = [
        ln.lstrip("•-– ").strip()
        for ln in block[1:]
        if ln.strip() and not re.match(r"^\d{4}", ln.strip())
    ]
    return ExperienceEntry(
        company=company, role=role, start_date=start, end_date=end, bullets=bullets
    )


class _SectionBuckets:
    """Accumulator for per-section line buckets during line scanning."""

    def __init__(self) -> None:
        self.summary: list[str] = []
        self.skills: list[str] = []
        self.experience: list[list[str]] = []
        self.projects: list[list[str]] = []
        self.education: list[str] = []
        self.certifications: list[str] = []
        self.awards: list[str] = []
        self.contact: list[str] = []
        self._simple: dict[str, list[str]] = {
            "summary": self.summary,
            "skills": self.skills,
            "education": self.education,
            "certifications": self.certifications,
            "awards": self.awards,
            "contact": self.contact,
        }

    def flush(self, section: str | None, buf: list[str]) -> None:
        """Flush buf into the appropriate bucket for section."""
        bucket = self._simple.get(section or "")
        if bucket is not None:
            bucket.extend(buf)


def _scan_lines(lines: list[str]) -> _SectionBuckets:
    """Scan resume lines into per-section buckets."""
    buckets = _SectionBuckets()
    current_section: str | None = None
    buf: list[str] = []

    for raw in lines:
        line = raw.rstrip()
        section = _classify_section(line)
        if section is not None:
            buckets.flush(current_section, buf)
            buf = []
            current_section = section
            if section == "experience":
                buckets.experience.append([])
                buf = buckets.experience[-1]
            elif section == "projects":
                buckets.projects.append([])
                buf = buckets.projects[-1]
        elif line.strip() and current_section is not None:
            buf.append(line.strip())

    buckets.flush(current_section, buf)
    return buckets


def extract_sections(text: str) -> SectionMap:
    """Parse plain-text resume into a SectionMap.

    Uses uppercase-header detection. Best-effort: unrecognized sections are
    silently skipped. Returns an empty SectionMap on blank input.
    """
    from pi_apply.section_map import EducationEntry, ProjectEntry, SectionMap

    b = _scan_lines(text.splitlines())

    summary = " ".join(b.summary).strip() or None
    skills = _parse_skills(b.skills)
    experience = [_parse_experience_block(blk) for blk in b.experience if blk]
    projects = [
        ProjectEntry(
            name=blk[0],
            bullets=[ln.lstrip("•-– ").strip() for ln in blk[1:] if ln.strip()],
        )
        for blk in b.projects
        if blk
    ]
    education = [EducationEntry(institution=el) for el in b.education if el]
    certifications = [c for c in b.certifications if c]
    awards = [a for a in b.awards if a]
    contact = " ".join(b.contact).strip() or None

    return SectionMap(
        summary=summary,
        skills=skills,
        experience=experience,
        projects=projects,
        education=education,
        certifications=certifications,
        awards=awards,
        contact=contact,
    )


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
