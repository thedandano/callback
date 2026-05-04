"""MCP server for pi-apply: host handoff and profile management.

Exposes five tools:
1. load_jd — loads JD markdown and returns host extraction instructions
2. submit_keywords — accepts host-extracted JDData and resumes keyword handoff
3. onboard_user — enters profile graph at onboard node
4. compile_profile — enters profile graph at compile_profile node
5. create_story — enters profile graph at create_story node
"""

import datetime
import json
import logging
import os
import sys
import uuid

from fastmcp import FastMCP

import pi_apply.profile_nodes as profile_nodes
from pi_apply.apply_graph import (
    KEYWORDS_ACCEPT_NODE,
    build_apply_graph,
)
from pi_apply.apply_graph import (
    make_config as make_apply_config,
)
from pi_apply.jd_data import EXTRACTION_PROTOCOL, JDDataError, parse_jd_json
from pi_apply.jd_fetcher import JDFetchError
from pi_apply.state import ApplyState, ProfileState
from pi_apply.wiki import WikiStore

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(message)s",  # messages are already JSON strings
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    payload["level"] = level
    logger.info(json.dumps(payload))


mcp = FastMCP("pi-apply")


# ============================================================================
# Envelope helpers
# ============================================================================


def _ok(session_id: str, next_action: str | None = None, data: dict | None = None) -> str:
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
    session_id: str | None = None,
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
    if session_id is not None:
        env["session_id"] = session_id
    return json.dumps(env)


def _submit_keywords_state_error(graph, config, session_id: str) -> str | None:
    """Return an error envelope if submit_keywords cannot resume safely."""
    snapshot = graph.get_state(config)
    if not snapshot.values:
        return _err(
            stage="submit_keywords",
            code="invalid_session",
            message="session_id was not found; call load_jd before submit_keywords",
            session_id=session_id,
            retriable=False,
        )

    expected_next = (KEYWORDS_ACCEPT_NODE,)
    if snapshot.next != expected_next:
        return _err(
            stage="submit_keywords",
            code="invalid_state",
            message="session is not waiting for keyword submission",
            session_id=session_id,
            retriable=False,
        )

    return None


# ============================================================================
# Apply workflow tools
# ============================================================================


@mcp.tool()
def load_jd(
    jd_url: str | None = None, jd_raw_text: str | None = None, resume_path: str = ""
) -> str:
    """Load a job description and return host extraction instructions.

    Takes a job description via jd_url, jd_raw_text, or both. At least one is
    required. When both are supplied, the graph attempts jd_url first and keeps
    jd_raw_text as fallback only for URL fetch failures. Empty URL content is
    reported as an error and does not fall back to pasted text.

    Args:
        jd_url: URL to a job description.
        jd_raw_text: Raw job description text.
        resume_path: Path to the source resume file.

    Returns:
        JSON envelope with status, session_id, jd_text, extraction_protocol, and
        next_action="extract_keywords".
    """
    session_id = str(uuid.uuid4())
    if not (jd_url or jd_raw_text):
        return _err(
            "load_jd",
            "missing_input",
            "neither jd_url nor jd_raw_text provided",
            session_id=session_id,
        )

    _log("INFO", {"tool": "load_jd", "session_id": session_id, "has_resume": bool(resume_path)})

    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        jd_raw_text=jd_raw_text,
        resume_path=resume_path,
    )

    graph = build_apply_graph()
    config = make_apply_config(session_id)
    try:
        state = graph.invoke(initial_state, config)
    except JDFetchError as exc:
        reason = getattr(exc, "reason", None)
        if reason == "fetch_failed":
            return _err(
                stage="jd_fetch",
                code="fetch_failed",
                message=(
                    "URL fetch failed. Resubmit with jd_raw_text to use pasted "
                    "job description text."
                ),
                session_id=session_id,
                retriable=True,
            )
        if reason == "empty_result":
            return _err(
                stage="jd_fetch",
                code="empty_result",
                message="URL returned no usable content.",
                session_id=session_id,
                retriable=False,
            )
        raise RuntimeError(f"unknown jd_fetch error reason: {reason}") from exc

    data = {
        "jd_text": state.get("jd_text"),
        "extraction_protocol": EXTRACTION_PROTOCOL,
    }
    return _ok(session_id, "extract_keywords", data)


@mcp.tool()
def submit_keywords(session_id: str, jd_json: str) -> str:
    """Accept host-extracted JDData and stop before resume parsing/scoring."""
    _log("INFO", {"tool": "submit_keywords", "session_id": session_id})

    try:
        keywords = parse_jd_json(jd_json)
    except JDDataError as exc:
        return _err(
            stage="submit_keywords",
            code=exc.code,
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )

    graph = build_apply_graph()
    config = make_apply_config(session_id)
    state_error = _submit_keywords_state_error(graph, config, session_id)
    if state_error is not None:
        return state_error

    try:
        graph.update_state(config, {"keywords": keywords})
        state = graph.invoke(None, config)
    except ValueError as exc:
        return _err(
            stage="submit_keywords",
            code="invalid_session",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )

    return _ok(session_id, "parse_initial", {"keywords": state.get("keywords")})


# ============================================================================
# Profile workflow tools
# ============================================================================


@mcp.tool()
def onboard_user(
    resume_content: str | None = None,
    resume_label: str | None = None,
    skills: str | None = None,
    accomplishments: str | None = None,
    sections: str | None = None,
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
    skills: str | None = None,
    remove_skills: str | None = None,
    stories: str | None = None,
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
    is_new_job: bool | None = None,
    job_start_date: str | None = None,
    job_end_date: str | None = None,
    jd_context: str | None = None,
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


@mcp.tool()
def get_wiki_pages(session_id: str, page_ids: list[str]) -> str:
    """Batch-fetch wiki pages for a session's resume.

    This tool exists because the wiki lives on the server's local filesystem and
    the host LLM has no direct file access in an MCP context — it can only reach
    files through tools the server exposes. The host reads the index returned by
    submit_keywords, picks the relevant page paths, and fetches their content here.

    Args:
        session_id: Apply session ID (used to resolve the resume_label).
        page_ids: Page paths relative to wiki root (e.g., ['experience/acme.md']).

    Returns:
        JSON envelope with pages dict {page_id: content}.
        Missing pages return empty string.
    """
    _log("INFO", {"tool": "get_wiki_pages", "session_id": session_id, "page_count": len(page_ids)})

    graph = build_apply_graph()
    config = make_apply_config(session_id)
    snapshot = graph.get_state(config)

    if not snapshot.values:
        return _err(
            stage="get_wiki_pages",
            code="invalid_session",
            message="session_id not found",
            session_id=session_id,
        )

    state_values = snapshot.values
    resume_label = state_values.get("resume_label")
    if not resume_label:
        resume_path = state_values.get("resume_path")
        if resume_path:
            from pathlib import Path as _Path

            resume_label = _Path(resume_path).stem
    if not resume_label:
        return _err(
            stage="get_wiki_pages",
            code="no_resume_label",
            message="no resume_label in session; call load_jd with resume_path first",
            session_id=session_id,
        )

    store = WikiStore()
    pages = store.read_pages(resume_label, page_ids)
    return _ok(session_id, data={"pages": pages})


def run() -> None:
    """Run the FastMCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    run()
