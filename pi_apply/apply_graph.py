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
JD_FETCH_NODE = "jd_fetch"
KEYWORDS_ACCEPT_NODE = "keywords_accept"
TAILOR_NODE = "tailor"


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
    builder.add_node("parse_initial", parse_initial)
    builder.add_node("score_initial", score_initial)
    builder.add_node("tailor", tailor)
    builder.add_node("render", render)
    builder.add_node("parse_final", parse_final)
    builder.add_node("score_final", score_final)
    builder.add_node("report", report)
    builder.add_node("finalize", finalize)

    # Set entry point
    builder.set_entry_point(JD_FETCH_NODE)

    # Wire linear edges
    builder.add_edge(JD_FETCH_NODE, KEYWORDS_ACCEPT_NODE)
    builder.add_edge(KEYWORDS_ACCEPT_NODE, "parse_initial")
    builder.add_edge("parse_initial", "score_initial")
    builder.add_edge("score_initial", "tailor")
    builder.add_edge("tailor", "render")
    builder.add_edge("render", "parse_final")
    builder.add_edge("parse_final", "score_final")
    builder.add_edge("score_final", "report")
    builder.add_edge("report", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=[JD_FETCH_NODE, KEYWORDS_ACCEPT_NODE, TAILOR_NODE],
    )
