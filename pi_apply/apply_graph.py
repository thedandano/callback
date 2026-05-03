"""Apply graph: end-to-end application pipeline with no interrupts.

The apply graph runs a single job application end-to-end in one .invoke() call:
jd_fetch → keywords_extract → parse_initial → score_initial → tailor → render
→ parse_final → score_final → report → finalize

Entry point: jd_fetch
Finish point: finalize
No interrupts; runs to completion in a single invoke() call.

State is persisted in SQLite checkpointer at ~/.local/share/pi-apply/apply-sessions.db.
"""

import sqlite3
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, END

from pi_apply.apply_nodes import (
    jd_fetch,
    keywords_extract,
    parse_initial,
    score_initial,
    tailor,
    render,
    parse_final,
    score_final,
    report,
    finalize,
)
from pi_apply.state import ApplyState

DB_PATH = Path.home() / ".local" / "share" / "pi-apply" / "apply-sessions.db"


def make_config(session_id: str) -> RunnableConfig:
    """Create a RunnableConfig for a session."""
    return RunnableConfig(configurable={"thread_id": session_id})


def build_apply_graph(db_path: Path = DB_PATH):
    """Build the apply graph with checkpointing.

    Constructs a linear state graph: jd_fetch → keywords_extract →
    parse_initial → score_initial → tailor → render → parse_final →
    score_final → report → finalize, with no interrupts.

    Args:
        db_path: Path to the SQLite checkpointer DB.
                 Defaults to ~/.local/share/pi-apply/apply-sessions.db

    Returns:
        Compiled LangGraph StateGraph for ApplyState with no interrupts.
        Runs end-to-end from jd_fetch to finalize in a single invoke() call.
    """
    # Initialize checkpointer with SQLite backend
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()

    # Build state graph with ApplyState schema
    builder = StateGraph(ApplyState)

    # Register all 10 nodes
    builder.add_node("jd_fetch", jd_fetch)
    builder.add_node("keywords_extract", keywords_extract)
    builder.add_node("parse_initial", parse_initial)
    builder.add_node("score_initial", score_initial)
    builder.add_node("tailor", tailor)
    builder.add_node("render", render)
    builder.add_node("parse_final", parse_final)
    builder.add_node("score_final", score_final)
    builder.add_node("report", report)
    builder.add_node("finalize", finalize)

    # Set entry point
    builder.set_entry_point("jd_fetch")

    # Wire linear edges
    builder.add_edge("jd_fetch", "keywords_extract")
    builder.add_edge("keywords_extract", "parse_initial")
    builder.add_edge("parse_initial", "score_initial")
    builder.add_edge("score_initial", "tailor")
    builder.add_edge("tailor", "render")
    builder.add_edge("render", "parse_final")
    builder.add_edge("parse_final", "score_final")
    builder.add_edge("score_final", "report")
    builder.add_edge("report", "finalize")
    builder.add_edge("finalize", END)

    # Compile without interrupts — graph runs end-to-end in single invoke()
    return builder.compile(checkpointer=checkpointer)
