"""Profile graph: entry point for profile lifecycle operations.

The profile graph manages user profile state across three MCP tools:
- onboard_user: initializes profile data (onboard node)
- compile_profile: recompiles the profile (compile_profile node)
- create_story: creates a behavioral story for a skill (create_story node)

Graph shape: check_profile router → onboard | compile_profile → check_orphans
Cycle: create_story → compile_profile → check_orphans (until no orphans).

Interrupts after onboard and create_story to allow caller to provide input.
"""

import sqlite3
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from callback.observability import build_graph_config
from callback.profile_nodes import (
    check_orphans,
    check_profile,
    compile_profile,
    create_story,
    onboard,
)
from callback.state import ProfileState

DB_PATH = Path.home() / ".local" / "share" / "callback" / "profile-sessions.db"


def make_config(
    session_id: str,
    *,
    tool_name: str | None = None,
    resume_label: str | None = None,
) -> RunnableConfig:
    """Create a RunnableConfig for a session."""
    if tool_name is None:
        return RunnableConfig(configurable={"thread_id": session_id})
    return build_graph_config(
        session_id=session_id,
        graph_name="profile",
        tool_name=tool_name,
        resume_label=resume_label,
    )


def _route_check_profile(state: ProfileState) -> str:
    """Route to onboard if no profile, else check_orphans."""
    return "onboard" if not state.profile_exists else "check_orphans"


def _route_check_orphans(state: ProfileState) -> str:
    """Route to create_story if orphans exist, else end."""
    return "create_story" if state.orphaned_skills else "end"


def build_profile_graph(db_path: Path = DB_PATH):
    """Build the profile graph with checkpointing.

    Constructs the state graph with five nodes (check_profile, onboard,
    compile_profile, check_orphans, create_story), entry point at
    check_profile, and edges forming a cycle for orphan draining.

    Args:
        db_path: Path to the SQLite checkpointer DB.
                 Defaults to ~/.local/share/callback/profile-sessions.db

    Returns:
        Compiled LangGraph StateGraph for ProfileState with interrupts
        configured after onboard and create_story nodes.
    """
    # Initialize checkpointer with SQLite backend
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()

    # Build state graph with ProfileState schema
    builder = StateGraph(ProfileState)

    # Register nodes
    builder.add_node("check_profile", check_profile)
    builder.add_node("onboard", onboard)
    builder.add_node("compile_profile", compile_profile)
    builder.add_node("check_orphans", check_orphans)
    builder.add_node("create_story", create_story)

    # Set entry point and wire edges
    builder.set_entry_point("check_profile")
    builder.add_edge("onboard", "compile_profile")
    builder.add_edge("compile_profile", "check_orphans")
    builder.add_edge("create_story", "compile_profile")  # Cycle for orphan drainage

    # Add routers for conditional branching
    builder.add_conditional_edges(
        "check_profile",
        _route_check_profile,
        {"onboard": "onboard", "check_orphans": "check_orphans"},
    )
    builder.add_conditional_edges(
        "check_orphans",
        _route_check_orphans,
        {"create_story": "create_story", "end": END},
    )

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["onboard", "compile_profile", "create_story"],
    )
