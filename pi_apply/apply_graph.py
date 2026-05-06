"""Apply graph: application pipeline with host keyword handoff interrupts.

The apply graph currently advances through the host keyword handoff:
jd_fetch → keywords_accept → parse_initial → score_initial → tailor → render
→ parse_final → score_final → report → finalize

Entry point: jd_fetch
Finish point: finalize
Interrupts after jd_fetch and keywords_accept so the host can extract and
submit JDData before later milestones parse and score resumes.

State is persisted in SQLite checkpointer at ~/.local/share/pi-apply/apply-sessions.db.
"""

import sqlite3
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from pi_apply.apply_nodes import (
    finalize,
    jd_fetch,
    keywords_accept,
    parse_final,
    parse_initial,
    render,
    report,
    score_final,
    score_initial,
    tailor,
)
from pi_apply.state import ApplyState

DB_PATH = Path.home() / ".local" / "share" / "pi-apply" / "apply-sessions.db"


def _route_or_halt(next_node: str):
    def _router(state: ApplyState) -> str:
        return END if state.error else next_node

    return _router


def _tailor_route(state: ApplyState) -> str:
    if state.error:
        return END
    if state.no_coverage:
        return REPORT_NODE
    return RENDER_NODE


JD_FETCH_NODE = "jd_fetch"
KEYWORDS_ACCEPT_NODE = "keywords_accept"
PARSE_INITIAL_NODE = "parse_initial"
SCORE_INITIAL_NODE = "score_initial"
TAILOR_NODE = "tailor"
RENDER_NODE = "render"
PARSE_FINAL_NODE = "parse_final"
SCORE_FINAL_NODE = "score_final"
REPORT_NODE = "report"
FINALIZE_NODE = "finalize"


def make_config(session_id: str) -> RunnableConfig:
    """Create a RunnableConfig for a session."""
    return RunnableConfig(configurable={"thread_id": session_id})


def build_apply_graph(db_path: Path = DB_PATH):
    """Build the apply graph with checkpointing and host handoff interrupts.

    Constructs a linear state graph: jd_fetch → keywords_accept →
    parse_initial → score_initial → tailor → render → parse_final →
    score_final → report → finalize.

    Args:
        db_path: Path to the SQLite checkpointer DB.
                 Defaults to ~/.local/share/pi-apply/apply-sessions.db

    Returns:
        Compiled LangGraph StateGraph for ApplyState. The graph interrupts after
        jd_fetch and keywords_accept for host-owned keyword extraction.
    """
    # Initialize checkpointer with SQLite backend
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()

    # Build state graph with ApplyState schema
    builder = StateGraph(ApplyState)

    # Register all 10 nodes
    builder.add_node(JD_FETCH_NODE, jd_fetch)
    builder.add_node(KEYWORDS_ACCEPT_NODE, keywords_accept)
    builder.add_node(PARSE_INITIAL_NODE, parse_initial)
    builder.add_node(SCORE_INITIAL_NODE, score_initial)
    builder.add_node(TAILOR_NODE, tailor)
    builder.add_node(RENDER_NODE, render)
    builder.add_node(PARSE_FINAL_NODE, parse_final)
    builder.add_node(SCORE_FINAL_NODE, score_final)
    builder.add_node(REPORT_NODE, report)
    builder.add_node(FINALIZE_NODE, finalize)

    # Set entry point
    builder.set_entry_point(JD_FETCH_NODE)

    # Wire linear edges
    builder.add_edge(JD_FETCH_NODE, KEYWORDS_ACCEPT_NODE)
    builder.add_edge(KEYWORDS_ACCEPT_NODE, PARSE_INITIAL_NODE)
    builder.add_edge(PARSE_INITIAL_NODE, SCORE_INITIAL_NODE)
    builder.add_edge(SCORE_INITIAL_NODE, TAILOR_NODE)
    builder.add_conditional_edges(TAILOR_NODE, _tailor_route)
    builder.add_conditional_edges(RENDER_NODE, _route_or_halt(PARSE_FINAL_NODE))
    builder.add_conditional_edges(PARSE_FINAL_NODE, _route_or_halt(SCORE_FINAL_NODE))
    builder.add_edge(SCORE_FINAL_NODE, REPORT_NODE)
    builder.add_edge(REPORT_NODE, FINALIZE_NODE)
    builder.add_edge(FINALIZE_NODE, END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=[JD_FETCH_NODE],
        interrupt_before=[TAILOR_NODE],
    )
