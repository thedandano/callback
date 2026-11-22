"""Apply node: accept host-submitted JDData."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState

logger = logging.getLogger("callback.apply_nodes")


@trace_node("apply", "keywords_accept")
def keywords_accept(state: ApplyState) -> dict:
    """Accept host-submitted JDData without extracting from jd_text.

    The host owns keyword extraction. This node only verifies that validated
    JDData-shaped keywords were injected before the graph resumes.
    """
    log_enter(logger, "keywords_accept", state)
    if not state.keywords:
        raise ValueError("keywords missing; submit validated JDData before resuming")
    return {}
