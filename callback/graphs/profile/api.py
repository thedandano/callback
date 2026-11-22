"""Front door to the profile graph: the only place tools touch the compiled graph.

Tools call these functions and never see the graph object, its node names,
`get_state`/`update_state`/`invoke`, or the tracing-suppressed invoke.
"""

from typing import Literal, NamedTuple

from callback.config.observability import invoke_graph_without_native_tracing
from callback.graphs.profile.graph import get_profile_graph, make_config, story_pending
from callback.models.state import ProfileState

__all__ = [
    "ProfileSession",
    "ensure_ready",
    "read",
    "run_thread",
    "start",
    "story_pending",
    "update",
]

_COMPILE_NODE = "compile_profile"
_CREATE_STORY_NODE = "create_story"


class ProfileSession(NamedTuple):
    """What a tool may know about a profile thread."""

    values: dict  # {} when the session is unknown
    waiting_for: Literal["compile_profile", "create_story"] | None


def ensure_ready() -> None:
    """Build (or fetch) the cached graph; raises what the session store raises."""
    get_profile_graph()


def read(session_id: str, *, tool_name: str) -> ProfileSession:
    """Snapshot of a thread; `values` is {} when the id is unknown."""
    snapshot = get_profile_graph().get_state(make_config(session_id, tool_name=tool_name))
    waiting_for: Literal["compile_profile", "create_story"] | None = None
    if snapshot.next == (_COMPILE_NODE,):
        waiting_for = "compile_profile"
    elif snapshot.next == (_CREATE_STORY_NODE,):
        waiting_for = "create_story"
    return ProfileSession(snapshot.values, waiting_for)


def update(session_id: str, values: dict, *, tool_name: str) -> None:
    """Write `values` into a paused thread's checkpoint."""
    get_profile_graph().update_state(make_config(session_id, tool_name=tool_name), values)


def start(state: ProfileState) -> dict:
    """Run the first leg for onboard_user (through its interrupt) and return the state values."""
    config = make_config(state.session_id, tool_name="onboard_user")
    graph = get_profile_graph()
    invoke_graph_without_native_tracing(graph, state, config)
    return graph.get_state(config).values


def run_thread(session_id: str, state: ProfileState | None, *, tool_name: str) -> ProfileSession:
    """Run a thread (new with `state`, resumed with None); raises on failure.

    If it pauses before create_story with a story pending, continue once so the
    story is saved in the same call.
    """
    config = make_config(session_id, tool_name=tool_name)
    graph = get_profile_graph()
    invoke_graph_without_native_tracing(graph, state, config)
    session = read(session_id, tool_name=tool_name)
    if session.waiting_for == "create_story" and story_pending(session.values.get("intake")):
        invoke_graph_without_native_tracing(graph, None, config)
        session = read(session_id, tool_name=tool_name)
    return session
