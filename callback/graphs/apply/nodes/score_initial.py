"""Apply node: score the source resume against JD keywords."""

import logging

from callback.config.observability import record_decision, trace_node
from callback.graphs.apply.scoring import run_score
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState

logger = logging.getLogger("callback.apply_nodes")


@trace_node("apply", "score_initial")
def score_initial(state: ApplyState) -> dict:
    """Score the parsed resume against JD keywords using scorer.py."""
    log_enter(logger, "score_initial", state)
    score = run_score(
        state.parsed_initial,
        state.keywords,
        closeable_by="source_pdf",
        candidate_years=state.candidate_years,
    )
    record_decision("experience_evaluated", score["experience_evaluated"])
    record_decision("no_section_headers", score["ats_input_suspect"])
    return {"score_initial": score}
