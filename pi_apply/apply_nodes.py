"""Apply graph node implementations.

Stub implementations of apply graph nodes. Each node logs entry and returns
sentinel values as placeholders. In real implementations, these will:
- jd_fetch: fetch or accept a job description
- keywords_accept: accept validated host-provided JDData
- parse_initial: extract text from the original resume
- score_initial: score resume against JD keywords
- tailor: rewrite resume bullets to match JD
- render: render the tailored resume to PDF
- parse_final: extract text from the rendered PDF
- score_final: score the rendered PDF text against JD keywords
- report: generate a comparison report
- finalize: archive the application record
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pi_apply import extractor as resume_extractor
from pi_apply import scorer
from pi_apply.jd_fetcher import MIN_MARKDOWN_CHARS, JDFetchError, fetch_url_to_markdown
from pi_apply.section_map import SectionMap
from pi_apply.state import ApplyState, TailoredResume
from pi_apply.wiki import WikiStore

logger = logging.getLogger(__name__)
jd_fetcher_logger = logging.getLogger("pi_apply.jd_fetcher")


# Module-level constant for applications directory, overridable by env var
def _get_apps_dir() -> Path:
    """Get applications directory from env var or default."""
    import os

    env_path = os.getenv("PI_APPLY_APPS_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "share" / "pi-apply" / "applications"


def _log_enter(node: str, state: ApplyState) -> None:
    """Log entry to a node with structured JSON."""
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))


def _log_jd_fetch(level: int, event: str, **fields: object) -> None:
    """Emit one JSON-encoded jd_fetch lifecycle log record."""
    jd_fetcher_logger.log(level, json.dumps({"event": event, **fields}))


def _run_score(text: str, keywords: dict) -> dict:
    if not text or not text.strip():
        raise ValueError("_run_score: text must not be empty")
    if not keywords.get("required"):
        raise ValueError("_run_score: keywords['required'] must be non-empty")
    r = scorer.score(
        text,
        keywords["required"],
        keywords["preferred"],
        required_years=keywords["required_years"],
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
    }


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


def keywords_accept(state: ApplyState) -> dict:
    """Accept host-submitted JDData without extracting from jd_text.

    The host owns keyword extraction. This node only verifies that validated
    JDData-shaped keywords were injected before the graph resumes.
    """
    _log_enter("keywords_accept", state)
    if not state.keywords:
        raise ValueError("keywords missing; submit validated JDData before resuming")
    return {}


def _sections_to_text(section_map: SectionMap) -> str:
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
        parts.append("\n".join(skill_chunks))
    for exp in section_map.experience:
        header = f"{exp.company} | {exp.role}"
        lines = [header] + exp.bullets
        parts.append("\n".join(lines))
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


def parse_initial(state: ApplyState) -> dict:
    """Load sections.json from wiki, fall back to text extraction if missing."""
    _log_enter("parse_initial", state)
    if state.resume_path is None:
        return {"parsed_initial": "<noop:parse:no-source>"}
    resume_label = Path(state.resume_path).stem
    sections_json, wiki_index, resume_text = _load_wiki_sections(resume_label)
    if sections_json:
        section_map = SectionMap.model_validate_json(sections_json)
        return {
            "parsed_initial": resume_text,
            "sections": section_map.model_dump(),
            "resume_label": resume_label,
            "wiki_index": wiki_index,
        }
    text = resume_extractor.extract(state.resume_path)
    return {"parsed_initial": text, "resume_label": resume_label}


def score_initial(state: ApplyState) -> dict:
    """Score the parsed resume against JD keywords using scorer.py."""
    _log_enter("score_initial", state)
    if state.parsed_initial is None or state.parsed_initial.startswith("<noop:"):
        return {"score_initial": {"total": 0, "stub": True, "parsed_chars": 0}}
    keywords = state.keywords
    if not keywords:
        return {"score_initial": {"total": 0, "stub": True, "parsed_chars": 0}}
    return {"score_initial": _run_score(state.parsed_initial, keywords)}


def tailor(state: ApplyState) -> dict:
    """Deterministic skeleton tailor: build TailoredResume from parsed_initial and keywords."""
    _log_enter("tailor", state)

    parsed = state.parsed_initial or ""
    non_empty_lines = [line.strip() for line in parsed.splitlines() if line.strip()]

    # name: first non-empty line, fallback to "Candidate Name"
    name = non_empty_lines[0] if non_empty_lines else "Candidate Name"

    # summary: next up to 5 non-empty lines joined with spaces
    summary_lines = non_empty_lines[1:6]
    summary = " ".join(summary_lines) if summary_lines else None

    # experience_raw: all remaining non-empty lines joined with \n
    remaining_lines = non_empty_lines[6:]
    experience_raw = "\n".join(remaining_lines) if remaining_lines else None

    # skills_raw: top-3 required keywords absent from parsed_initial (case-insensitive)
    required_keywords: list[str] = (state.keywords or {}).get("required", [])
    parsed_lower = parsed.lower()
    missing = [kw for kw in required_keywords if kw.lower() not in parsed_lower]
    top3_missing = missing[:3]
    skills_raw = f"Tools: {', '.join(top3_missing)}" if top3_missing else None

    keyword_count = len(required_keywords)
    output_fields = {
        k: v
        for k, v in {
            "name": name,
            "summary": summary,
            "skills_raw": skills_raw,
            "experience_raw": experience_raw,
        }.items()
        if v is not None
    }
    logger.info(
        json.dumps(
            {
                "node": "tailor",
                "session_id": state.session_id,
                "keyword_count": keyword_count,
                "output_fields": list(output_fields.keys()),
            }
        )
    )

    return {
        "tailored": TailoredResume(
            name=name,
            summary=summary,
            skills_raw=skills_raw,
            experience_raw=experience_raw,
            max_pages=1,
        )
    }


def _detect_uncovered_skills(section_map: SectionMap) -> list[str]:
    """Return skills added to skills section but absent from all experience bullets."""
    all_skills = list(section_map.skills.flat)
    for items in section_map.skills.categorized.values():
        all_skills.extend(items)

    bullet_text = " ".join(b for exp in section_map.experience for b in exp.bullets).lower()

    return [s for s in all_skills if s.lower() not in bullet_text]


def _resolve_tailored_text(state: ApplyState) -> str:
    """Return tailored resume text from tailored_sections; state.tailored is now TailoredResume."""
    if state.tailored_sections:
        section_map = SectionMap.model_validate(state.tailored_sections)
        return _sections_to_text(section_map)
    return ""


def render(state: ApplyState) -> dict:
    """Render tailored resume to PDF (stub) and write plain-text for parse_final."""
    _log_enter("render", state)

    apps_dir = _get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Write empty PDF stub (real fpdf2 rendering is out of scope)
    pdf_path = apps_dir / f"{state.session_id}.pdf"
    pdf_path.write_bytes(b"")

    # Derive tailored text from sections if available, else fall back to state.tailored
    tailored_text = _resolve_tailored_text(state)

    # Write plain-text alongside PDF for parse_final to read
    txt_path = apps_dir / f"{state.session_id}.txt"
    txt_path.write_text(tailored_text, encoding="utf-8")

    return {"pdf_path": str(pdf_path)}


def parse_final(state: ApplyState) -> dict:
    """Extract text from the rendered PDF for final ATS scoring."""
    _log_enter("parse_final", state)
    if not state.pdf_path:
        return {"parsed_final": "<noop:parse:no-pdf-path>"}
    p = Path(state.pdf_path)
    if not p.exists() or p.stat().st_size == 0:
        return {"parsed_final": "<noop:parse:empty-pdf>"}
    return {"parsed_final": resume_extractor.extract(str(p))}


def score_final(state: ApplyState) -> dict:
    """Score the extracted PDF text against JD keywords."""
    _log_enter("score_final", state)
    if state.parsed_final is None or state.parsed_final.startswith("<noop:"):
        return {"score_final": {"total": 0, "stub": True, "parsed_chars": 0}}
    keywords = state.keywords
    if not keywords:
        return {"score_final": {"total": 0, "stub": True, "parsed_chars": 0}}
    return {"score_final": _run_score(state.parsed_final, keywords)}


def report(state: ApplyState) -> dict:
    """Compute score delta between initial and final pass."""
    _log_enter("report", state)
    initial_total = (state.score_initial or {}).get("total") or 0.0
    final_total = (state.score_final or {}).get("total") or 0.0
    return {
        "report": {
            "delta_total": round(final_total - initial_total, 2),
            "score_initial_total": initial_total,
            "score_final_total": final_total,
        }
    }


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

    # Build archive record with all required fields
    archive = {
        "session_id": state.session_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "jd_url": state.jd_url,
        "jd_text": state.jd_text,
        "keywords": state.keywords,
        "tailored_resume_text": tailored_text,
        "pdf_path": state.pdf_path,
        "scores": {
            "initial": state.score_initial,
            "final": state.score_final,
            "scoring_engine_version": "1",
        },
        "uncovered_skills": state.uncovered_skills or [],
    }

    # Write archive JSON
    archive_path = apps_dir / f"{state.session_id}.json"
    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2)

    return {"finalized": True}
