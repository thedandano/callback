"""Apply node: score the rendered PDF text against JD keywords."""

import logging

from callback.config.observability import record_decision, trace_node
from callback.graphs.apply.scoring import run_score
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState

logger = logging.getLogger("callback.apply_nodes")


@trace_node("apply", "score_final")
def score_final(state: ApplyState) -> dict:
    """Score the extracted PDF text against JD keywords."""
    log_enter(logger, "score_final", state)
    score = run_score(
        state.parsed_final,
        state.keywords,
        closeable_by="render",
        candidate_years=state.candidate_years,
    )
    record_decision("experience_evaluated", score["experience_evaluated"])
    return {"score_final": score}
