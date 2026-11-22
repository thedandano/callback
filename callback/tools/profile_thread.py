"""Profile-graph thread helpers shared by compile_profile and create_story."""

from callback.config.logging import log_exception
from callback.graphs.profile import api as profile_api
from callback.models.envelope import err
from callback.models.state import ProfileState


def _compile_failed_after_save_error(stage: str, session_id: str) -> dict:
    """Build the retriable compile_failed envelope for a story saved before compile raised."""
    message = (
        "profile compile failed; call compile_profile again with this session_id"
        if stage == "compile_profile"
        else "story saved; call compile_profile with this session_id to finish"
    )
    return err(stage, "compile_failed", message, session_id, retriable=True)


def _profile_failure_error(session_id: str, stage: str) -> dict:
    """Classify a failed profile run by the durable checkpoint's pending node.

    The checkpoint read is guarded: an unreadable checkpoint falls through to the
    generic unexpected_error envelope instead of escaping as a raw MCP failure.
    """
    try:
        session = profile_api.read(session_id, tool_name=stage)
    except Exception:
        log_exception({"tool": stage, "session_id": session_id, "event": "checkpoint_error"})
        session = None
    pending = session.waiting_for if session is not None else None
    intake = session.values.get("intake") if session is not None else None
    if pending == "compile_profile":
        return _compile_failed_after_save_error(stage, session_id)
    if pending == "create_story" and profile_api.story_pending(intake):
        # The node may have written the story's wiki page before the checkpoint
        # write failed. save_story ignores an identical story, so retrying is safe.
        return err(
            stage,
            "story_unconfirmed",
            "story save could not be confirmed; call create_story again with this "
            "session_id (an identical story is not saved twice)",
            session_id,
            retriable=True,
        )
    return err(
        stage=stage,
        code="unexpected_error",
        message=f"unexpected {stage} failure; inspect callback logs",
        session_id=session_id,
        retriable=False,
    )


def run_profile_thread(
    session_id: str, state: ProfileState | None, stage: str
) -> tuple[profile_api.ProfileSession | None, dict | None]:
    """Run the profile thread (see profile_api.run_thread).

    Returns (session, error_envelope_or_None). The session carries both the state
    values and the pending node, so callers never re-read the checkpoint.
    """
    try:
        session = profile_api.run_thread(session_id, state, tool_name=stage)
    except Exception:
        log_exception({"tool": stage, "session_id": session_id, "event": "unexpected_error"})
        return None, _profile_failure_error(session_id, stage)
    if (session.values.get("intake") or {}).get("status") == "no_resume":
        return None, err(
            stage, "profile_missing", "no profile; call onboard_user first", session_id
        )
    return session, None


def profile_thread_data(session: profile_api.ProfileSession) -> tuple[str | None, dict]:
    """Return (next_action, common data) for a profile thread after a run."""
    values = session.values
    paused = session.waiting_for == "create_story"
    intake = values.get("intake") or {}
    data = {
        "compiled_profile": values.get("compiled_profile") or {},
        "skill_coverage_warnings": intake.get("skill_coverage_warnings", []),
        "skills_index": intake.get("skills_index", []),
        "orphaned_skills": values.get("orphaned_skills") or [],
    }
    return ("create_story" if paused else None), data


def _validate_session(session_id: str, stage: str, waiting_for: str) -> dict | None:
    """Validate a host-supplied session before resuming it. Returns an error or None."""
    session = profile_api.read(session_id, tool_name=stage)
    if not session.values:
        return err(stage, "session_not_found", "session_id not found", session_id)
    if session.waiting_for != waiting_for:
        return err(stage, "invalid_state", f"session is not waiting for {waiting_for}", session_id)
    return None


def resume_profile_thread(
    session_id: str,
    stage: str,
    waiting_for: str,
    update: dict | None,
) -> dict | None:
    """Validate and resume a checkpointed profile thread; guard the checkpoint I/O.

    A locked/read-only/full checkpoint DB must surface as a retriable envelope,
    not a raw MCP failure. Returns an error envelope, or None on success.
    """
    try:
        error = _validate_session(session_id, stage, waiting_for)
        if error:
            return error
        if update is not None:
            profile_api.update(session_id, update, tool_name=stage)
    except Exception:
        log_exception({"tool": stage, "session_id": session_id, "event": "checkpoint_error"})
        return err(
            stage,
            "checkpoint_error",
            "could not read or update the session checkpoint; inspect callback logs",
            session_id,
            retriable=True,
        )
    return None
