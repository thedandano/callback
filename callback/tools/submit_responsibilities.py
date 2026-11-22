"""MCP tool `submit_responsibilities`."""

from callback.config.logging import log
from callback.config.observability import (
    trace_tool,
)
from callback.graphs.apply.graph import (
    SCORE_INITIAL_NODE,
    TAILOR_NODE,
    get_apply_graph,
)
from callback.graphs.apply.graph import (
    make_config as make_apply_config,
)
from callback.models.envelope import err, ok
from callback.models.jd_data import JDDataError
from callback.services.jd_parsing import (
    clean_responsibilities,
    drop_scored_duplicates,
    non_atomic_responsibilities,
)
from callback.tools.errors import graph_or_err
from callback.tools.workflow import NEXT_FETCH_WIKI_THEN_TAILOR, submit_keywords_workflow


def submit_responsibilities(session_id: str, key_responsibilities: list[str]) -> dict:
    """Store pass 2 of keyword extraction: the key_responsibilities list.

    Call after submit_keywords and before submit_tailor. The list replaces the one
    from submit_keywords. Terms already in a scored list are dropped. Scoring is unchanged.
    """
    return _submit_responsibilities_impl(session_id, key_responsibilities)


def _responsibilities_state_error(snapshot, session_id: str) -> dict | None:
    if not snapshot.values:
        return err(
            "submit_responsibilities",
            "invalid_session",
            "session_id was not found; call load_jd and submit_keywords first",
            session_id,
        )
    if snapshot.next != (TAILOR_NODE,):
        return err(
            "submit_responsibilities",
            "invalid_state",
            "session is not between submit_keywords and submit_tailor",
            session_id,
        )
    return None


def _trim_responsibilities(keywords: dict, session_id: str) -> dict:
    """Drop responsibilities already scored; warn when they look like sentences."""
    trimmed, dropped = drop_scored_duplicates(keywords)
    base = {"tool": "submit_responsibilities", "session_id": session_id}
    if dropped:
        log("INFO", {**base, "event": "responsibilities_deduped", "dropped": dropped})
    sentences = non_atomic_responsibilities(trimmed["key_responsibilities"])
    if sentences:
        log(
            "WARNING",
            {
                **base,
                "event": "non_atomic_responsibilities",
                "terms": sentences,
                "action": "kept as sent; pass 2 should return short keywords",
            },
        )
    return trimmed


@trace_tool("submit_responsibilities", graph_name="apply")
def _submit_responsibilities_impl(session_id: str, key_responsibilities: list[str]) -> dict:
    log("INFO", {"tool": "submit_responsibilities", "session_id": session_id})
    graph, graph_error = graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_apply_config(session_id, tool_name="submit_responsibilities")
    snapshot = graph.get_state(config)
    state_error = _responsibilities_state_error(snapshot, session_id)
    if state_error is not None:
        return state_error
    try:
        terms = clean_responsibilities(key_responsibilities)
    except JDDataError as exc:
        return err("submit_responsibilities", exc.code, str(exc), session_id, retriable=True)
    keywords = {**(snapshot.values.get("keywords") or {}), "key_responsibilities": terms}
    keywords = _trim_responsibilities(keywords, session_id)
    # as_node keeps tailor as the next pending node (see _tailor_retry_update).
    graph.update_state(config, {"keywords": keywords}, as_node=SCORE_INITIAL_NODE)
    workflow = submit_keywords_workflow(
        session_id, NEXT_FETCH_WIKI_THEN_TAILOR, [], pass_2_pending=False
    )
    return ok(session_id, NEXT_FETCH_WIKI_THEN_TAILOR, {"keywords": keywords}, workflow)
