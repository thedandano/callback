"""MCP server for pi-apply: apply and profile management.

Exposes four tools:
1. apply — runs the apply graph end-to-end for a single JD application
2. onboard_user — enters profile graph at onboard node
3. compile_profile — enters profile graph at compile_profile node
4. create_story — enters profile graph at create_story node
"""

import datetime
import json
import logging
import os
import sys
import uuid
from typing import Optional

from fastmcp import FastMCP

# Import graphs and nodes
from pi_apply.apply_graph import build_apply_graph, make_config as make_apply_config
from pi_apply.state import ApplyState, ProfileState
import pi_apply.profile_nodes as profile_nodes

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",  # messages are already JSON strings
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload["level"] = level
    logger.info(json.dumps(payload))


mcp = FastMCP("pi-apply")


# ============================================================================
# Envelope helpers
# ============================================================================


def _ok(session_id: str, next_action: Optional[str] = None, data: Optional[dict] = None) -> str:
    """Return a success envelope."""
    env: dict = {"session_id": session_id, "status": "ok"}
    if next_action:
        env["next_action"] = next_action
    if data:
        env["data"] = data
    return json.dumps(env)


def _err(
    stage: str,
    code: str,
    message: str,
    session_id: Optional[str] = None,
    retriable: bool = False,
) -> str:
    """Return an error envelope."""
    env: dict = {
        "status": "error",
        "error": {
            "stage": stage,
            "code": code,
            "message": message,
            "retriable": retriable,
        },
    }
    if session_id:
        env["session_id"] = session_id
    return json.dumps(env)


# ============================================================================
# Apply workflow tool
# ============================================================================


@mcp.tool()
def apply(jd_url: Optional[str] = None, jd_raw_text: Optional[str] = None, resume_path: str = "") -> str:
    """Run a complete job application workflow end-to-end.

    Takes a job description (via jd_url or jd_raw_text, one required) and a
    resume_path. Runs the apply graph from jd_fetch to finalize in a single
    call, returning the complete result (PDF path, scores, report, archive).

    Args:
        jd_url: URL to a job description (not yet supported in skeleton).
        jd_raw_text: Raw job description text.
        resume_path: Path to the source resume file.

    Returns:
        JSON envelope with status, session_id, and data (pdf_path, report, scores, etc.).
    """
    # Validate input: exactly one of jd_url or jd_raw_text
    if not (jd_url or jd_raw_text):
        return _err("apply", "missing_input", "neither jd_url nor jd_raw_text provided")

    if jd_url and jd_raw_text:
        return _err("apply", "invalid_input", "only one of jd_url or jd_raw_text allowed")

    session_id = str(uuid.uuid4())
    _log("INFO", {"tool": "apply", "session_id": session_id, "has_resume": bool(resume_path)})

    # Initialize state with provided inputs
    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        jd_raw_text=jd_raw_text,
        resume_path=resume_path,
    )

    # Build and invoke apply graph end-to-end
    graph = build_apply_graph()
    config = make_apply_config(session_id)
    result_state = graph.invoke(initial_state, config)

    # Extract results from final state
    data = {
        "pdf_path": result_state.get("pdf_path"),
        "report": result_state.get("report"),
        "score_initial": result_state.get("score_initial"),
        "score_final": result_state.get("score_final"),
        "uncovered_skills": result_state.get("uncovered_skills", []),
    }

    return _ok(session_id, None, data)


# ============================================================================
# Profile workflow tools
# ============================================================================


@mcp.tool()
def onboard_user(
    resume_content: Optional[str] = None,
    resume_label: Optional[str] = None,
    skills: Optional[str] = None,
    accomplishments: Optional[str] = None,
    sections: Optional[str] = None,
) -> str:
    """Onboard a new user: collect resume, skills, and accomplishments.

    Skeleton: directly invokes the onboard node. Real impl will use graph
    state injection to re-enter at onboard.

    Returns:
        JSON envelope with status ok and session_id.
    """
    session_id = str(uuid.uuid4())
    _log(
        "INFO",
        {
            "tool": "onboard_user",
            "session_id": session_id,
            "has_resume": resume_content is not None,
            "has_skills": skills is not None,
            "has_accomplishments": accomplishments is not None,
        },
    )

    # Skeleton: directly call the onboard node (bypasses check_profile router)
    state = ProfileState(session_id=session_id)
    delta = profile_nodes.onboard(state)

    return _ok(session_id, "compile_profile", delta)


@mcp.tool()
def compile_profile(
    skills: Optional[str] = None,
    remove_skills: Optional[str] = None,
    stories: Optional[str] = None,
) -> str:
    """Recompile the user's profile from skills and stories.

    Skeleton: directly invokes the compile_profile node. Real impl will use
    graph state injection to re-enter at compile_profile.

    Returns:
        JSON envelope with status ok and session_id.
    """
    session_id = str(uuid.uuid4())
    _log(
        "INFO",
        {
            "tool": "compile_profile",
            "session_id": session_id,
            "has_skills": skills is not None,
            "has_remove_skills": remove_skills is not None,
            "has_stories": stories is not None,
        },
    )

    # Skeleton: directly call the compile_profile node (bypasses check_profile router)
    state = ProfileState(session_id=session_id)
    delta = profile_nodes.compile_profile(state)

    return _ok(session_id, "check_orphans", delta)


@mcp.tool()
def create_story(
    skill: str,
    story_type: str,
    job_title: str,
    situation: str,
    behavior: str,
    impact: str,
    is_new_job: Optional[bool] = None,
    job_start_date: Optional[str] = None,
    job_end_date: Optional[str] = None,
    jd_context: Optional[str] = None,
) -> str:
    """Create a behavioral story for a skill.

    Skeleton: directly invokes the create_story node. Real impl will use graph
    state injection to re-enter at create_story.

    Returns:
        JSON envelope with status ok and session_id.
    """
    session_id = str(uuid.uuid4())
    _log(
        "INFO",
        {
            "tool": "create_story",
            "session_id": session_id,
            "skill": skill,
            "story_type": story_type,
            "job_title": job_title,
        },
    )

    # Skeleton: directly call the create_story node (bypasses check_profile router)
    state = ProfileState(session_id=session_id)
    delta = profile_nodes.create_story(state)

    return _ok(session_id, "compile_profile", delta)


if __name__ == "__main__":
    mcp.run()
