"""Apply graph node implementations.

Stub implementations of apply graph nodes. Each node logs entry and returns
sentinel values as placeholders. In real implementations, these will:
- jd_fetch: fetch or accept a job description
- keywords_extract: extract required and preferred keywords from JD
- parse_initial: extract text from the original resume
- score_initial: score resume against JD keywords
- tailor: rewrite resume bullets to match JD
- render: render the tailored resume to PDF
- parse_final: extract text from the rendered PDF
- score_final: score the rendered PDF text against JD keywords
- report: generate a comparison report
- finalize: archive the application record
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pi_apply.state import ApplyState

logger = logging.getLogger(__name__)

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


def _parse_resume(source_path: str | None) -> str:
    """Shared no-op parse of resume text.

    Real impl will use pdfplumber/python-docx/txt extraction.
    Stub returns sentinel showing the path was valid.
    """
    if source_path is None:
        return "<noop:parse:no-source>"

    p = Path(source_path)
    if not p.exists():
        return f"<noop:parse:missing:{source_path}>"

    if p.stat().st_size == 0:
        return f"<noop:parse:empty:{source_path}>"

    # Real impl reads file. Stub shows path was real.
    return f"<noop:parse:ok:{source_path}>"


def _score(parsed_text: str | None, keywords: dict | None) -> dict:
    """Shared no-op score computation.

    Real impl will use scorer.compute_score.
    Stub returns fixed dict with stub marker.
    """
    return {
        "total": 0,
        "stub": True,
        "parsed_chars": len(parsed_text or ""),
    }


def jd_fetch(state: ApplyState) -> dict:
    """Fetch or accept a job description.

    If jd_url is set, return a sentinel showing fetch attempt.
    If jd_raw_text is set, return it as-is.
    If neither, return error.
    """
    _log_enter("jd_fetch", state)

    if state.jd_url:
        return {"jd_text": f"<noop:jd_fetch:url:{state.jd_url}>"}

    if state.jd_raw_text:
        return {"jd_text": state.jd_raw_text}

    return {"error": "neither jd_url nor jd_raw_text provided"}


def keywords_extract(state: ApplyState) -> dict:
    """Extract required and preferred keywords from JD.

    Stub returns empty keyword lists with stub marker.
    """
    _log_enter("keywords_extract", state)
    return {
        "keywords": {
            "required": [],
            "preferred": [],
            "stub": True,
        }
    }


def parse_initial(state: ApplyState) -> dict:
    """Parse the original resume from resume_path."""
    _log_enter("parse_initial", state)
    return {"parsed_initial": _parse_resume(state.resume_path)}


def score_initial(state: ApplyState) -> dict:
    """Score the initial parsed resume against keywords."""
    _log_enter("score_initial", state)
    return {"score_initial": _score(state.parsed_initial, state.keywords)}


def tailor(state: ApplyState) -> dict:
    """Rewrite resume bullets to match JD.

    Stub returns noop sentinel with original text appended.
    """
    _log_enter("tailor", state)
    return {"tailored": f"<noop:tailor>{state.parsed_initial or ''}"}


def render(state: ApplyState) -> dict:
    """Render tailored resume to PDF.

    Stub writes a real empty file at apps_dir/<session_id>.pdf.
    Real impl will generate a full PDF.
    """
    _log_enter("render", state)

    apps_dir = _get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = apps_dir / f"{state.session_id}.pdf"
    pdf_path.write_bytes(b"")  # Empty PDF stub

    return {"pdf_path": str(pdf_path)}


def parse_final(state: ApplyState) -> dict:
    """Parse the rendered PDF.

    Reads from pdf_path. If file exists (even if empty), stub succeeds.
    """
    _log_enter("parse_final", state)
    return {"parsed_final": _parse_resume(state.pdf_path)}


def score_final(state: ApplyState) -> dict:
    """Score the final parsed text against keywords.

    Stub returns same structure as score_initial.
    """
    _log_enter("score_final", state)
    return {"score_final": _score(state.parsed_final, state.keywords)}


def report(state: ApplyState) -> dict:
    """Generate a comparison report between initial and final scores.

    Stub returns empty report dict with stub marker.
    """
    _log_enter("report", state)
    return {
        "report": {
            "stub": True,
            "delta_total": 0,
        },
        "uncovered_skills": [],
    }


def finalize(state: ApplyState) -> dict:
    """Archive the complete application record.

    Writes a JSON archive to apps_dir/<session_id>.json containing all
    required fields per spec. Sets finalized=True.
    """
    _log_enter("finalize", state)

    apps_dir = _get_apps_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Build archive record with all required fields
    archive = {
        "session_id": state.session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "jd_url": state.jd_url,
        "jd_text": state.jd_text,
        "keywords": state.keywords,
        "tailored_resume_text": state.tailored,
        "pdf_path": state.pdf_path,
        "scores": {
            "initial": state.score_initial,
            "final": state.score_final,
            "scoring_engine_version": "noop-0",
        },
        "uncovered_skills": state.uncovered_skills or [],
    }

    # Write archive JSON
    archive_path = apps_dir / f"{state.session_id}.json"
    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2)

    return {"finalized": True}
