"""MCP tool `onboard_user`."""

import uuid
from pathlib import Path

from callback.config.logging import log
from callback.config.observability import trace_tool
from callback.graphs.profile import api as profile_api
from callback.models.envelope import err, ok
from callback.models.state import ProfileState
from callback.tools.errors import graph_or_err, unexpected_error


def _read_file_content(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else None


def _build_onboard_warnings(
    skills_path: str | None, accomplishments_path: str | None
) -> list[dict]:
    if skills_path or accomplishments_path:
        return []
    return [
        {
            "warning": "no_skills_path",
            "message": "No skills file provided. Skills will be extracted from resume only.",
        }
    ]


def _build_onboard_data(state_values: dict, warnings: list[dict]) -> dict:
    data: dict = {
        "intake": state_values.get("intake") or {},
        "resume_label": state_values.get("resume_label"),
        "sections": state_values.get("sections") or {},
    }
    if warnings:
        data["warnings"] = warnings
    return data


def onboard_user(
    resume_path: str | None = None,
    skills_path: str | None = None,
    accomplishments_path: str | None = None,
) -> dict:
    """Onboard a new user: register resume, skills, and accomplishments.

    Args:
        resume_path: Path to the resume file (PDF, DOCX, or TXT).
        skills_path: Optional path to a plain-text skills file.
        accomplishments_path: Optional path to a plain-text accomplishments file.

    Returns:
        Envelope dict (structured content) with status ok, next_action=compile_profile, and data
        containing intake, resume_label, sections, and optional warnings.
    """
    session_id = str(uuid.uuid4())
    return _onboard_user_impl(
        session_id,
        resume_path,
        skills_path=skills_path,
        accomplishments_path=accomplishments_path,
    )


@trace_tool("onboard_user", graph_name="profile")
def _onboard_user_impl(
    session_id: str,
    resume_path: str | None,
    *,
    skills_path: str | None = None,
    accomplishments_path: str | None = None,
) -> dict:
    log(
        "INFO",
        {
            "tool": "onboard_user",
            "session_id": session_id,
            "has_resume": resume_path is not None,
            "has_skills": skills_path is not None,
            "has_accomplishments": accomplishments_path is not None,
        },
    )

    if not resume_path:
        return err(
            stage="onboard_user",
            code="missing_resume_path",
            message="resume_path is required",
            session_id=session_id,
            retriable=False,
        )

    warnings = _build_onboard_warnings(skills_path, accomplishments_path)
    onboard_text = _read_file_content(accomplishments_path)
    intake: dict = {}
    if onboard_text:
        intake["onboard_text"] = onboard_text

    initial_state = ProfileState(
        session_id=session_id,
        resume_path=resume_path,
        intake=intake if intake else None,
    )
    _, graph_error = graph_or_err(profile_api.ensure_ready, session_id)
    if graph_error is not None:
        return graph_error
    state_values, invoke_error = _onboard_user_invoke(initial_state, session_id)
    if invoke_error is not None:
        return invoke_error
    assert state_values is not None

    return ok(session_id, "compile_profile", _build_onboard_data(state_values, warnings))


def _onboard_user_invoke(
    initial_state: ProfileState, session_id: str
) -> tuple[dict, None] | tuple[None, dict]:
    """Invoke the profile graph and fetch its state, mapping raised errors to envelopes."""
    try:
        return profile_api.start(initial_state), None
    except Exception:
        return None, unexpected_error("onboard_user", session_id)
