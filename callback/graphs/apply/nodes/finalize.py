"""Apply node: record the finished run in the ledger."""

import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

from callback.config import paths
from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.ledger import RunRecord
from callback.models.section_map import SectionMap
from callback.models.state import ApplyState
from callback.repositories import ledger
from callback.services import scorer
from callback.services.section_text import sections_to_text

logger = logging.getLogger("callback.apply_nodes")


def _resolve_tailored_text(state: ApplyState) -> str:
    """Return tailored resume text from tailored_sections; state.tailored is now TailoredResume."""
    if state.tailored_sections:
        section_map = SectionMap.model_validate(state.tailored_sections)
        return sections_to_text(section_map)
    return ""


@trace_node("apply", "finalize")
def finalize(state: ApplyState) -> dict:
    """Record the finished run in the ledger (one row per session; a retry overwrites it)."""
    log_enter(logger, "finalize", state)

    finalized_at = datetime.now(UTC).isoformat()
    try:
        run = RunRecord(
            session_id=state.session_id,
            timestamp=finalized_at,
            jd_url=state.jd_url,
            jd_text=state.jd_text,
            keywords=state.keywords,
            tailored_resume_text=_resolve_tailored_text(state),
            pdf_path=state.pdf_path,
            render_page_count=state.render_page_count,
            render_warnings=state.render_warnings or [],
            scores={
                "initial": state.score_initial,
                "final": state.score_initial if state.no_coverage else state.score_final,
                "delta": (state.report or {}).get("delta"),
                "scoring_engine_version": scorer.SCORING_ENGINE_VERSION,
            },
            uncovered_skills=state.uncovered_skills or [],
            outcome={
                "no_coverage": bool(state.no_coverage),
                "reason": "no wiki stories cover required keywords" if state.no_coverage else None,
            },
        )
        with closing(ledger.connect()) as conn:
            ledger.record_run(conn, run)
    except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
        logger.error(
            json.dumps(
                {
                    "node": "finalize",
                    "session_id": state.session_id,
                    "ledger_path": str(paths.ledger_path()),
                    "error": str(exc),
                }
            )
        )
        return {"error": f"finalize: cannot write ledger: {exc}"}

    return {"finalized_at": finalized_at}
