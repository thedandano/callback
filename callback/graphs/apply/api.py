"""Front door to the apply graph: the only place tools touch the compiled graph.

Tools call these functions and never see the graph object, its node names,
`get_state`/`update_state`/`invoke`, or the tracing-suppressed invoke.
"""

from typing import Literal, NamedTuple

from callback.config.logging import log
from callback.config.observability import invoke_graph_without_native_tracing, record_decision
from callback.graphs.apply.graph import (
    FINALIZE_NODE,
    KEYWORDS_ACCEPT_NODE,
    PARSE_FINAL_NODE,
    RENDER_NODE,
    REPORT_NODE,
    SCORE_FINAL_NODE,
    SCORE_INITIAL_NODE,
    TAILOR_NODE,
    get_apply_graph,
    make_config,
)
from callback.models.state import ApplyState

_HALTED_NODES = (RENDER_NODE, PARSE_FINAL_NODE, SCORE_FINAL_NODE, REPORT_NODE, FINALIZE_NODE)

_STALE_RETRY_KEYS = (
    "tailored",
    "tailored_sections",
    "pdf_path",
    "render_page_count",
    "render_warnings",
    "parsed_final",
    "score_final",
    "report",
    "tailor_diagnostics",
    "uncovered_skills",
    "applied_skill_values",
    "no_coverage",
)


class ApplySession(NamedTuple):
    """What a tool may know about an apply session."""

    values: dict  # {} when the session is unknown
    waiting_for: Literal["keywords", "tailor"] | None
    halted_at: str | None  # node name when a raised error parked the session mid-pipeline


def ensure_ready() -> None:
    """Build (or fetch) the cached graph; raises what the session store raises."""
    get_apply_graph()


def start(state: ApplyState, *, resume_label: str | None) -> dict:
    """Run the first leg of the graph (through jd_fetch) and return its state."""
    config = make_config(state.session_id, tool_name="load_jd", resume_label=resume_label)
    return invoke_graph_without_native_tracing(get_apply_graph(), state, config)


def read(session_id: str, *, tool_name: str) -> ApplySession:
    """Snapshot of a session; `values` is {} when the id is unknown."""
    snapshot = get_apply_graph().get_state(make_config(session_id, tool_name=tool_name))
    waiting_for: Literal["keywords", "tailor"] | None = None
    if snapshot.next == (KEYWORDS_ACCEPT_NODE,):
        waiting_for = "keywords"
    elif snapshot.next == (TAILOR_NODE,):
        waiting_for = "tailor"
    halted_at = snapshot.next[0] if snapshot.next and snapshot.next[0] in _HALTED_NODES else None
    return ApplySession(snapshot.values, waiting_for, halted_at)


def accept_keywords(session_id: str, keywords: dict) -> None:
    """Store host-extracted keywords; ValueError means the checkpoint is unusable."""
    config = make_config(session_id, tool_name="submit_keywords")
    get_apply_graph().update_state(config, {"keywords": keywords})


def add_responsibilities(session_id: str, keywords: dict) -> None:
    """Store keywords as a score_initial write so tailor stays the next pending node."""
    config = make_config(session_id, tool_name="submit_responsibilities")
    get_apply_graph().update_state(config, {"keywords": keywords}, as_node=SCORE_INITIAL_NODE)


def queue_tailor(session_id: str, values: dict) -> None:
    """Log a retry when the session previously errored, then queue tailor with `values`.

    Writes as_node=SCORE_INITIAL_NODE explicitly: its outgoing edge unconditionally
    targets tailor, so this always re-queues tailor as the next pending task. Without
    an explicit as_node, LangGraph infers the last node that wrote state; after an
    error that is tailor/render/parse_final itself, whose conditional edge would
    re-evaluate against the now-cleared error and route past tailor/render entirely.

    On a retry (the prior state carries an error), also clear stale outputs
    (_STALE_RETRY_KEYS) from an earlier attempt that got further than this one before
    failing, e.g. an edits attempt that rendered a PDF and then failed at parse_final,
    followed by a no_coverage retry that skips render. Caller-supplied values win.
    """
    graph = get_apply_graph()
    config = make_config(session_id, tool_name="submit_tailor")
    update = values
    retrying = bool(graph.get_state(config).values.get("error"))
    record_decision("tailor_attempt", "retry_after_error" if retrying else "first")
    if retrying:
        log(
            "INFO",
            {"tool": "submit_tailor", "session_id": session_id, "event": "retry_after_error"},
        )
        update = {**dict.fromkeys(_STALE_RETRY_KEYS), **values}
    graph.update_state(config, update, as_node=SCORE_INITIAL_NODE)


def resume(session_id: str, *, tool_name: str) -> dict:
    """Run the graph from its pending interrupt and return the resulting state."""
    config = make_config(session_id, tool_name=tool_name)
    return invoke_graph_without_native_tracing(get_apply_graph(), None, config)
