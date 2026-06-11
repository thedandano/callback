"""Apply graph node implementations.

Implements the 10 nodes of the linear apply pipeline:
- jd_fetch: fetches the job description via URL (Crawl4AI) or accepts raw text
- keywords_accept: stores host-validated JDData; re-enters at parse_initial
- parse_initial: extracts text and sections from the source resume file
- score_initial: scores the resume against JD keywords (deterministic scorer)
- tailor: interrupts for host to submit edits to the resume SectionMap
- render: renders the tailored SectionMap to PDF via HTML + Playwright
- parse_final: extracts text from the rendered PDF for final scoring
- score_final: scores the rendered PDF text against JD keywords
- report: generates a before/after comparison report
- finalize: archives the application PDF and JSON record to PI_APPLY_APPS_DIR
"""

import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from pi_apply import extractor as resume_extractor
from pi_apply import scorer
from pi_apply.jd_fetcher import MIN_MARKDOWN_CHARS, JDFetchError, fetch_url_to_markdown
from pi_apply.observability import trace_node
from pi_apply.render import render_resume
from pi_apply.repository.resumes import ResumeNotFoundError, get_resume
from pi_apply.section_map import SectionMap
from pi_apply.state import ApplyState, TailoredResume
from pi_apply.wiki import WikiStore

logger = logging.getLogger(__name__)
jd_fetcher_logger = logging.getLogger("pi_apply.jd_fetcher")
_DASH_RE = re.compile(r"[-‐–—\u00ad\u2011\u200b]")
_WS_RE = re.compile(r"\s+")


# Module-level constant for applications directory, overridable by env var
def _get_apps_dir() -> Path:
    env_path = os.getenv("PI_APPLY_APPS_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "share" / "pi-apply" / "applications"


def _resume_filename_part(value: str | None, fallback: str) -> str:
    raw = (value or "").strip() or fallback
    safe = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_") or fallback
    return "_".join(part.capitalize() for part in safe.split("_"))


def _resume_pdf_filename(candidate_name: str | None, company_name: str | None) -> str:
    candidate = _resume_filename_part(candidate_name, "Candidate")
    company = _resume_filename_part(company_name, "Company")
    return f"{candidate}_{company}_Resume.pdf"


def _normalize_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _DASH_RE.sub(" ", normalized)
    return _WS_RE.sub(" ", normalized).strip()


def _log_enter(node: str, state: ApplyState) -> None:
    """Log entry to a node with structured JSON."""
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))


def _log_jd_fetch(level: int, event: str, **fields: object) -> None:
    """Emit one JSON-encoded jd_fetch lifecycle log record."""
    jd_fetcher_logger.log(level, json.dumps({"event": event, **fields}))


def _run_score(
    text: str | None,
    keywords: dict | None,
    closeable_by: str = "source_pdf",
) -> dict:
    if not text or not text.strip():
        raise ValueError("_run_score: text must not be empty")
    if not keywords or not keywords.get("required"):
        raise ValueError("_run_score: keywords['required'] must be non-empty")
    r = scorer.score(
        text,
        keywords["required"],
        keywords["preferred"],
        required_years=keywords["required_years"],
        closeable_by=closeable_by,  # type: ignore[arg-type]
    )
    return {
        "total": r.breakdown.total(),
        "keyword_match": r.breakdown.keyword_match,
        "experience_fit": r.breakdown.experience_fit,
        "impact_evidence": r.breakdown.impact_evidence,
        "ats_format": r.breakdown.ats_format,
        "readability": r.breakdown.readability,
        "req_matched": r.keywords.req_matched,
        "req_unmatched": r.keywords.req_unmatched,
        "pref_matched": r.keywords.pref_matched,
        "pref_unmatched": r.keywords.pref_unmatched,
        "ats_diagnostics": [
            {
                "expected": d.expected,
                "observed": d.observed,
                "matched": d.matched,
                "closeable_by": d.closeable_by,
            }
            for d in r.breakdown.ats_diagnostics
        ],
    }


@trace_node("apply", "jd_fetch")
def jd_fetch(state: ApplyState) -> dict:
    """Fetch or accept a job description.

    URL input is preferred when present. Raw text is used directly only when no
    URL is provided, or as the approved fallback for URL I/O failures.
    """
    _log_enter("jd_fetch", state)

    if state.jd_url:
        start = perf_counter()
        _log_jd_fetch(logging.INFO, "fetch_start", session_id=state.session_id, jd_url=state.jd_url)

        try:
            markdown = asyncio.run(fetch_url_to_markdown(state.jd_url))
        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            error_fields = {
                "session_id": state.session_id,
                "jd_url": state.jd_url,
                "duration_ms": duration_ms,
                "error_class": exc.__class__.__name__,
                "error_msg": str(exc),
            }

            if state.jd_raw_text:
                _log_jd_fetch(logging.WARNING, "fallback_used", **error_fields)
                return {"jd_text": state.jd_raw_text}

            _log_jd_fetch(logging.ERROR, "fetch_error", **error_fields)
            raise JDFetchError(reason="fetch_failed", url=state.jd_url, cause=exc) from exc

        duration_ms = int((perf_counter() - start) * 1000)
        byte_count = len(markdown.encode("utf-8"))
        log_fields = {
            "session_id": state.session_id,
            "jd_url": state.jd_url,
            "bytes": byte_count,
            "duration_ms": duration_ms,
        }

        if len(markdown.strip()) <= MIN_MARKDOWN_CHARS:
            _log_jd_fetch(logging.ERROR, "fetch_empty", **log_fields)
            raise JDFetchError(reason="empty_result", url=state.jd_url)

        _log_jd_fetch(logging.INFO, "fetch_ok", **log_fields)
        return {"jd_text": markdown}

    if state.jd_raw_text:
        return {"jd_text": state.jd_raw_text}

    _log_jd_fetch(logging.ERROR, "no_input", session_id=state.session_id)
    raise ValueError("neither jd_url nor jd_raw_text provided")


@trace_node("apply", "keywords_accept")
def keywords_accept(state: ApplyState) -> dict:
    """Accept host-submitted JDData without extracting from jd_text.

    The host owns keyword extraction. This node only verifies that validated
    JDData-shaped keywords were injected before the graph resumes.
    """
    _log_enter("keywords_accept", state)
    if not state.keywords:
        raise ValueError("keywords missing; submit validated JDData before resuming")
    return {}


def _sections_to_text(section_map: SectionMap) -> str:  # noqa: C901
    """Convert a SectionMap to flat text suitable for scoring."""
    parts: list[str] = []
    if section_map.summary:
        parts.append(section_map.summary)
    skills = section_map.skills
    skill_chunks: list[str] = []
    if skills.flat:
        skill_chunks.append(", ".join(skills.flat))
    for cat, items in skills.categorized.items():
        skill_chunks.append(f"{cat}: {', '.join(items)}")
    if skill_chunks:
        parts.append("Skills")
        parts.append("\n".join(skill_chunks))
    if section_map.experience:
        parts.append("Experience")
    for exp in section_map.experience:
        header = f"{exp.company} | {exp.role}"
        lines = [header] + exp.bullets
        parts.append("\n".join(lines))
    if section_map.education:
        parts.append("Education")
    for edu in section_map.education:
        parts.append(edu.institution or "")
    for proj in section_map.projects:
        lines = [proj.name] + proj.bullets
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _load_wiki_sections(resume_label: str) -> tuple[str, str, str]:
    """Load sections.json and index.md from wiki.

    Returns (sections_json, wiki_index, resume_text) where resume_text is empty
    when sections_json is empty.
    """
    store = WikiStore()
    pages = store.read_pages(resume_label, ["sections.json", "index.md"])
    sections_json = pages.get("sections.json", "")
    wiki_index = pages.get("index.md", "")
    if not sections_json:
        return "", "", ""
    section_map = SectionMap.model_validate_json(sections_json)
    resume_text = _sections_to_text(section_map)
    return sections_json, wiki_index, resume_text


@trace_node("apply", "parse_initial")
def parse_initial(state: ApplyState) -> dict:
    """Load sections.json from wiki for tailoring; extract original PDF for scoring."""
    _log_enter("parse_initial", state)
    if state.resume_label is None:
        return {"parsed_initial": "<noop:parse:no-source>"}

    sections_json, wiki_index, sections_text = _load_wiki_sections(state.resume_label)
    base: dict = {}
    if sections_json:
        section_map = SectionMap.model_validate_json(sections_json)
        base = {"sections": section_map.model_dump(), "wiki_index": wiki_index}

    try:
        resume_path = get_resume(state.resume_label)
    except ResumeNotFoundError:
        fallback = sections_text if sections_json else "<noop:parse:no-source>"
        logger.warning(
            json.dumps(
                {
                    "node": "parse_initial",
                    "event": "resume_not_found",
                    "resume_label": state.resume_label,
                    "fallback": "sections_text" if sections_json else "noop",
                }
            )
        )
        return {**base, "parsed_initial": fallback}

    text = resume_extractor.extract(resume_path)
    return {**base, "parsed_initial": text}


@trace_node("apply", "score_initial")
def score_initial(state: ApplyState) -> dict:
    """Score the parsed resume against JD keywords using scorer.py."""
    _log_enter("score_initial", state)
    return {
        "score_initial": _run_score(state.parsed_initial, state.keywords, closeable_by="source_pdf")
    }


def _build_skills_raw(skills) -> str | None:
    lines: list[str] = []
    for cat, items in skills.categorized.items():
        lines.append(f"{cat}: {', '.join(items)}")
    if skills.flat:
        lines.append(f"Additional: {', '.join(skills.flat)}")
    return "\n".join(lines) or None


def _build_experience_raw(experience) -> str | None:
    blocks: list[str] = []
    for exp in experience:
        lines = [exp.company]
        role_line = exp.context_line if exp.context_line is not None else exp.role
        start = exp.start_date or ""
        end = exp.end_date or ""
        date_range = f"{start} – {end}" if (start or end) else ""
        if role_line and date_range:
            lines.append(f"{role_line} | {date_range}")
        elif role_line:
            lines.append(role_line)
        elif date_range:
            lines[-1] = f"{lines[-1]} | {date_range}"
        lines.extend(f"• {b}" for b in exp.bullets)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or None


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _parse_resume_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"present", "current"}:
        now = datetime.now(UTC)
        return now.year, now.month
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})", normalized):
        return int(match.group(1)), int(match.group(2))
    if match := re.fullmatch(r"([a-z]+)\s+(\d{4})", normalized):
        month = _MONTHS.get(match.group(1))
        if month:
            return int(match.group(2)), month
    if match := re.fullmatch(r"(\d{4})", normalized):
        return int(match.group(1)), 1
    return None


def _candidate_experience_years(experience) -> float | None:
    months = 0
    for exp in experience:
        start = _parse_resume_month(exp.start_date)
        end = _parse_resume_month(exp.end_date)
        if not start or not end:
            continue
        start_index = start[0] * 12 + start[1]
        end_index = end[0] * 12 + end[1]
        if end_index >= start_index:
            months += end_index - start_index + 1
    if months == 0:
        return None
    return round(months / 12, 2)


def _split_title_summary(summary: str | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if len(lines) > 1 and lines[0] == lines[0].upper() and any(c.isalpha() for c in lines[0]):
        return lines[0], " ".join(lines[1:])
    return None, summary


def _normalize_resume_title(title: str | None) -> str | None:
    if not isinstance(title, str):
        return None
    stripped = title.strip()
    return stripped.upper() if stripped else None


def _section_map_to_tailored_resume(
    section_map: SectionMap,
    fallback_title: str | None = None,
) -> TailoredResume:
    """Convert a SectionMap to a TailoredResume for rendering."""
    contact = section_map.contact
    if contact is None:
        raise ValueError("_section_map_to_tailored_resume: section_map.contact is required")
    title, summary = _split_title_summary(section_map.summary)
    title = title or _normalize_resume_title(fallback_title)
    proj_blocks: list[str] = []
    for proj in section_map.projects:
        block_lines = [proj.name]
        if proj.description is not None:
            block_lines.append(proj.description)
        block_lines.extend(f"• {b}" for b in proj.bullets)
        proj_blocks.append("\n".join(block_lines))
    edu_blocks = [f"{edu.institution}\n{edu.degree or ''}" for edu in section_map.education]
    return TailoredResume(
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        location=contact.location,
        linkedin=contact.linkedin,
        website=contact.website,
        title=title,
        summary=summary,
        skills_raw=_build_skills_raw(section_map.skills),
        experience_raw=_build_experience_raw(section_map.experience),
        projects_raw="\n\n".join(proj_blocks) or None,
        education_raw="\n\n".join(edu_blocks) or None,
        candidate_experience_years=_candidate_experience_years(section_map.experience),
        max_pages=1,
    )


@trace_node("apply", "tailor")
def tailor(state: ApplyState) -> dict:
    """Convert tailored_sections SectionMap to TailoredResume, or skip if no_coverage."""
    _log_enter("tailor", state)
    if state.no_coverage:
        return {}  # conditional edge routes to report
    if state.tailored_sections:
        try:
            section_map = SectionMap.model_validate(state.tailored_sections)
            fallback_title = None
            if isinstance(state.keywords, dict):
                fallback_title = state.keywords.get("title")
            return {"tailored": _section_map_to_tailored_resume(section_map, fallback_title)}
        except (ValidationError, ValueError) as exc:
            return {"error": f"tailor: invalid tailored_sections: {exc}"}
    return {"error": "tailor: no tailored_sections and no_coverage not set"}


def _detect_uncovered_skills(section_map: SectionMap) -> list[str]:
    """Return skills added to skills section but absent from all experience bullets."""
    all_skills = list(section_map.skills.flat)
    for items in section_map.skills.categorized.values():
        all_skills.extend(items)

    bullet_text = " ".join(b for exp in section_map.experience for b in exp.bullets)

    def _covered(skill: str) -> bool:
        return bool(re.search(rf"\b{re.escape(skill)}\b", bullet_text, re.IGNORECASE))

    return [s for s in all_skills if not _covered(s)]


def _resolve_tailored_text(state: ApplyState) -> str:
    """Return tailored resume text from tailored_sections; state.tailored is now TailoredResume."""
    if state.tailored_sections:
        section_map = SectionMap.model_validate(state.tailored_sections)
        return _sections_to_text(section_map)
    return ""


@trace_node("apply", "render")
def render(state: ApplyState) -> dict:
    """Render tailored resume to PDF via HTML + Playwright."""
    _log_enter("render", state)
    if state.tailored is None:
        return {"error": "render: state.tailored is None — tailor node must run first"}

    base_dir = Path(state.output_dir) if state.output_dir else _get_apps_dir()
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"error": f"render: cannot create output dir {base_dir}: {exc}"}
    company_name = state.keywords.get("company") if state.keywords else None
    output_path = str(base_dir / _resume_pdf_filename(state.tailored.name, company_name))

    result = render_resume(state.tailored.model_dump(), output_path)
    if result["success"]:
        logger.info(
            json.dumps({"node": "render", "session_id": state.session_id, "pdf_path": output_path})
        )
        return {
            "pdf_path": output_path,
            "render_page_count": result.get("page_count"),
            "render_warnings": result.get("warnings") or [],
        }
    else:
        logger.error(
            json.dumps({"node": "render", "session_id": state.session_id, "error": result["error"]})
        )
        return {"error": f"render: {result['error']}"}


@trace_node("apply", "parse_final")
def parse_final(state: ApplyState) -> dict:
    """Extract text from the rendered PDF for final ATS scoring."""
    _log_enter("parse_final", state)
    if not state.pdf_path:
        return {"error": "parse_final: no pdf_path in state"}
    p = Path(state.pdf_path)
    if not p.exists():
        return {"error": f"parse_final: pdf file not found: {state.pdf_path}"}
    if p.stat().st_size == 0:
        return {"error": f"parse_final: pdf file is empty: {state.pdf_path}"}
    text = resume_extractor.extract(state.pdf_path)
    if not text.strip():
        return {"error": "parse_final: PDF extracted to empty text"}
    logger.info(
        json.dumps({"node": "parse_final", "session_id": state.session_id, "chars": len(text)})
    )
    return {"parsed_final": text}


@trace_node("apply", "score_final")
def score_final(state: ApplyState) -> dict:
    """Score the extracted PDF text against JD keywords."""
    _log_enter("score_final", state)
    return {"score_final": _run_score(state.parsed_final, state.keywords, closeable_by="render")}


_SCORE_DIMS = (
    "total",
    "keyword_match",
    "experience_fit",
    "impact_evidence",
    "ats_format",
    "readability",
)


def _compute_tailor_diagnostics(
    applied_skill_values: list[str] | None, parsed_final: str | None
) -> list[dict]:
    if not applied_skill_values:
        return []
    rendered = parsed_final or ""
    rendered_lower = rendered.lower()
    result = []
    for value in applied_skill_values:
        present = value.lower() in rendered_lower
        result.append(
            {
                "value": value,
                "applied_to_map": True,
                "present_in_rendered_text": present,
                "suggested_alternatives": [] if present else [_normalize_for_match(value)],
            }
        )
    return result


@trace_node("apply", "report")
def report(state: ApplyState) -> dict:
    """Compute per-dimension score delta and format gap between initial and final pass.

    When no_coverage=True, use score_initial as both si and sf so delta is all-zero.
    """
    _log_enter("report", state)
    si = state.score_initial or {}
    sf = si if state.no_coverage else (state.score_final or {})
    delta = {dim: round((sf.get(dim) or 0.0) - (si.get(dim) or 0.0), 2) for dim in _SCORE_DIMS}
    format_gap_chars = len(state.parsed_final or "") - len(state.parsed_initial or "")
    tailor_diagnostics = _compute_tailor_diagnostics(state.applied_skill_values, state.parsed_final)
    notes: list[str] = []
    sf_diag = sf.get("ats_diagnostics") or []
    for d in sf_diag:
        if not d.get("matched") and d.get("closeable_by") != "tailor":
            notes.append(
                f"ATS format: '{d['expected']}' header not found in rendered PDF "
                f"(closeable_by={d['closeable_by']}). Tailoring cannot fix this."
            )
    for warning in state.render_warnings or []:
        message = warning.get("message")
        if message:
            notes.append(str(message))
    return {
        "report": {
            "before": {dim: si.get(dim) for dim in _SCORE_DIMS},
            "after": {dim: sf.get(dim) for dim in _SCORE_DIMS},
            "delta": delta,
            "format_gap_chars": format_gap_chars,
            "no_coverage": bool(state.no_coverage),
            "uncovered_skills": state.uncovered_skills or [],
            "notes": notes,
        },
        "tailor_diagnostics": tailor_diagnostics,
    }


@trace_node("apply", "finalize")
def finalize(state: ApplyState) -> dict:
    """Archive the complete application record.

    Writes a JSON archive to apps_dir/<session_id>.json containing all
    required fields per spec. Sets finalized=True.
    """
    _log_enter("finalize", state)

    apps_dir = _get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Derive tailored resume text from sections or tailored object
    tailored_text = _resolve_tailored_text(state)

    finalized_at = datetime.now(UTC).isoformat()

    # Build archive record with all required fields
    archive = {
        "session_id": state.session_id,
        "timestamp": finalized_at,
        "jd_url": state.jd_url,
        "jd_text": state.jd_text,
        "keywords": state.keywords,
        "tailored_resume_text": tailored_text,
        "pdf_path": state.pdf_path,
        "render_page_count": state.render_page_count,
        "render_warnings": state.render_warnings or [],
        "scores": {
            "initial": state.score_initial,
            "final": state.score_initial if state.no_coverage else state.score_final,
            "delta": (state.report or {}).get("delta"),
            "scoring_engine_version": "v1",
        },
        "uncovered_skills": state.uncovered_skills or [],
        "outcome": {
            "no_coverage": bool(state.no_coverage),
            "reason": "no wiki stories cover required keywords" if state.no_coverage else None,
        },
    }

    # Write archive JSON
    archive_path = apps_dir / f"{state.session_id}.json"
    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2)

    return {"finalized": True, "finalized_at": finalized_at}
