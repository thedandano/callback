"""MCP tool `create_story`."""

import uuid

from callback.config.logging import log
from callback.config.observability import (
    trace_tool,
)
from callback.graphs.profile.graph import get_profile_graph
from callback.graphs.profile.graph import make_config as make_profile_config
from callback.models.profile import CreatedStory
from callback.models.state import ProfileState
from callback.repositories.story_pages import label_line_field
from callback.tools.envelope import err, ok
from callback.tools.errors import graph_or_err
from callback.tools.profile_thread import (
    profile_thread_data,
    resume_profile_thread,
    run_profile_thread,
)
from callback.tools.resume_label import resolve_new_thread_resume_label


def create_story(
    primary_skill: str,
    skills: list[str],
    story_type: str,
    job_title: str,
    situation: str,
    behavior: str,
    impact: str,
    session_id: str | None = None,
) -> dict:
    """Create and persist a behavioral story for a skill, then recompile the profile.

    Args:
        primary_skill: The main skill this story demonstrates.
        skills: All skills this story demonstrates (must include primary_skill).
        story_type: Story format (e.g., STAR, CAR, PAR).
        job_title: Role title for this story.
        situation: Context / problem statement.
        behavior: Actions taken.
        impact: Quantified outcome.
        session_id: Optional profile session paused before create_story (from
            compile_profile or a previous create_story). Omit to start a new session.

    Returns:
        Envelope dict (structured content) with story_id, primary_skill,
        needs_compile (always false: the profile is recompiled in the same
        call), and orphaned_skills. next_action is "create_story" when orphans
        remain.
    """
    resumed = session_id is not None
    session_id = session_id or str(uuid.uuid4())
    log(
        "INFO",
        {
            "tool": "create_story",
            "session_id": session_id,
            "resumed": resumed,
            "primary_skill": primary_skill,
            "story_type": story_type,
            "job_title": job_title,
        },
    )
    if not primary_skill.strip():
        return err(
            "create_story",
            "invalid_story",
            "primary_skill is required",
            session_id,
            retriable=False,
        )
    intake = {
        "primary_skill": primary_skill,
        "skills": skills,
        "story_type": story_type,
        "job_title": job_title,
        "situation": situation,
        "behavior": behavior,
        "impact": impact,
    }
    field = label_line_field(CreatedStory(id="", **intake))
    if field is not None:
        return err(
            "create_story",
            "invalid_story",
            f"{field} contains a line starting with **Situation:**, **Behavior:**, or "
            "**Impact:**; those mark paragraph boundaries in the story page, rephrase it",
            session_id,
            retriable=False,
        )
    return _create_story_impl(session_id, intake, resumed=resumed)


@trace_tool("create_story", graph_name="profile")
def _create_story_impl(session_id: str, intake: dict, *, resumed: bool) -> dict:
    graph, graph_error = graph_or_err(get_profile_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_profile_config(session_id, tool_name="create_story")
    if resumed:
        error = resume_profile_thread(
            graph, config, session_id, "create_story", "create_story", {"intake": intake}
        )
        if error:
            return error
        graph_input = None
    else:
        resume_label = resolve_new_thread_resume_label("create_story", session_id)
        graph_input = ProfileState(session_id=session_id, resume_label=resume_label, intake=intake)
    snapshot, error = run_profile_thread(graph, config, graph_input, session_id, "create_story")
    if error:
        return error
    assert snapshot is not None
    values = snapshot.values
    if not (values.get("intake") or {}).get("story_id"):
        log(
            "ERROR",
            {"tool": "create_story", "session_id": session_id, "event": "story_not_saved"},
        )
        return err(
            "create_story",
            "story_not_saved",
            "graph run completed without saving the story",
            session_id,
            retriable=False,
        )
    next_action, data = profile_thread_data(snapshot)
    data = {
        "story_id": (values.get("intake") or {}).get("story_id"),
        "primary_skill": intake["primary_skill"],
        "needs_compile": False,
        **data,
    }
    return ok(session_id, next_action, data)
