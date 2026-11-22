"""MCP tool `compile_profile`."""

import json
import uuid

from callback.config.logging import log
from callback.config.observability import (
    trace_tool,
)
from callback.graphs.profile import api as profile_api
from callback.models.envelope import err, ok
from callback.models.state import ProfileState
from callback.tools.errors import graph_or_err
from callback.tools.profile_thread import (
    profile_thread_data,
    resume_profile_thread,
    run_profile_thread,
)
from callback.tools.resume_label import resolve_new_thread_resume_label


def _parse_story_tags(story_tags: str | None) -> list[str] | None:
    if not story_tags:
        return []
    try:
        parsed = json.loads(story_tags)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return list(parsed.keys())
    if isinstance(parsed, list):
        return [str(t) for t in parsed]
    return None


def compile_profile(story_tags: str | None = None, session_id: str | None = None) -> dict:
    """Recompile the user profile from all stored stories.

    Args:
        story_tags: Optional JSON string. Accepts a dict (keys become host_tags)
            or a list of skill strings.
        session_id: Optional profile session to resume (from onboard_user). Omit to
            start a new profile session.

    Returns:
        Envelope dict (structured content) with compiled_profile,
        skill_coverage_warnings, skills_index, and orphaned_skills.
        next_action is "create_story" when orphans remain.
    """
    resumed = session_id is not None
    session_id = session_id or str(uuid.uuid4())
    log(
        "INFO",
        {
            "tool": "compile_profile",
            "session_id": session_id,
            "resumed": resumed,
            "has_story_tags": story_tags is not None,
        },
    )
    host_tags = _parse_story_tags(story_tags)
    if host_tags is None:
        return err(
            stage="compile_profile",
            code="invalid_story_tags",
            message="story_tags must be a JSON dict or list",
            session_id=session_id,
            retriable=True,
        )
    explicit = story_tags is not None
    return _compile_profile_impl(session_id, host_tags, resumed=resumed, explicit_tags=explicit)


@trace_tool("compile_profile", graph_name="profile")
def _compile_profile_impl(
    session_id: str, host_tags: list[str], *, resumed: bool, explicit_tags: bool
) -> dict:
    _, graph_error = graph_or_err(profile_api.ensure_ready, session_id)
    if graph_error is not None:
        return graph_error
    if resumed:
        update = {"host_tags": host_tags} if explicit_tags else None
        error = resume_profile_thread(session_id, "compile_profile", "compile_profile", update)
        if error:
            return error
        graph_input = None
    else:
        resume_label = resolve_new_thread_resume_label("compile_profile", session_id)
        graph_input = ProfileState(
            session_id=session_id, resume_label=resume_label, host_tags=host_tags or None
        )
    session, error = run_profile_thread(session_id, graph_input, "compile_profile")
    if error:
        return error
    assert session is not None
    next_action, data = profile_thread_data(session)
    return ok(session_id, next_action, data)
