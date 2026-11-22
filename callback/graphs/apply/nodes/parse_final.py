"""Apply node: extract text from the rendered PDF."""

import json
import logging
from pathlib import Path

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState
from callback.services import extractor as resume_extractor

logger = logging.getLogger("callback.apply_nodes")


@trace_node("apply", "parse_final")
def parse_final(state: ApplyState) -> dict:
    """Extract text from the rendered PDF for final ATS scoring."""
    log_enter(logger, "parse_final", state)
    if not state.pdf_path:
        return {"error": "parse_final: no pdf_path in state"}
    p = Path(state.pdf_path)
    try:
        if not p.exists():
            return {"error": f"parse_final: pdf file not found: {state.pdf_path}"}
        if p.stat().st_size == 0:
            return {"error": f"parse_final: pdf file is empty: {state.pdf_path}"}
        text = resume_extractor.extract(state.pdf_path)
    except Exception as exc:
        logger.error(
            json.dumps({"node": "parse_final", "session_id": state.session_id, "error": str(exc)})
        )
        return {"error": f"parse_final: extract failed: {exc}"}
    if not text.strip():
        return {"error": "parse_final: PDF extracted to empty text"}
    logger.info(
        json.dumps({"node": "parse_final", "session_id": state.session_id, "chars": len(text)})
    )
    return {"parsed_final": text}
