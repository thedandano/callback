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
import re
import sys
import uuid

from fastmcp import FastMCP

import pi_apply.profile_nodes as profile_nodes
from pi_apply.apply_graph import (
    KEYWORDS_ACCEPT_NODE,
    TAILOR_NODE,
    build_apply_graph,
)
from pi_apply.apply_graph import (
    make_config as make_apply_config,
)
from pi_apply.apply_nodes import _detect_uncovered_skills
from pi_apply.jd_data import EXTRACTION_PROTOCOL, JDDataError, parse_jd_json
from pi_apply.jd_fetcher import JDFetchError
from pi_apply.section_map import SectionMap, apply_edit
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


_TAILOR_INSTRUCTIONS = (
    "V4 voice constraints:\n"
    "- Bullets: past-tense action verb + mechanism (HOW) + metric from wiki. "
    "Banned verbs: spearheaded, orchestrated, championed, leveraged, utilized, streamlined.\n"
    "- Summary: ≤3 sentences, ≥1 quantified anchor. "
    "Banned: passionate, driven, results-oriented, proven track record.\n"
    "- Context line per role: <Role> · <Domain/Team> · <Scale signal> · <Stack>"
    " — factual only, no adjectives.\n"
    "- Skills: every keyword added to skills MUST appear in ≥1 dated experience bullet."
)

mcp = FastMCP("pi-apply")


# ============================================================================
# Orphan detection helpers
# ============================================================================


def _all_skills(sections: dict) -> list[str]:
    """Extract all skill strings from a SectionMap skills dict (flat + categorized)."""
    skills = sections.get("skills") or {}
    flat = skills.get("flat") or []
    cats = skills.get("categorized") or {}
    result = list(flat)
    for items in cats.values():
        result.extend(items)
    return result


def _detect_orphaned_required(
    required_missing: list[str], sections: dict, wiki_index: str
) -> list[str]:
    """Return required_missing keywords that are orphans.

    An orphan is a keyword that IS in the candidate's SectionMap skills but is
    NOT yet covered by any wiki story. Skills membership uses case-insensitive
    exact match; wiki_index uses case-insensitive substring search (the index is
    unstructured markdown text).
    """
    all_skills_lower = [s.lower() for s in _all_skills(sections)]
    orphans: list[str] = []
    for kw in required_missing:
        in_skills = kw.lower() in all_skills_lower
        in_wiki = bool(re.search(rf"\b{re.escape(kw)}\b", wiki_index, re.IGNORECASE))
        if in_skills and not in_wiki:
            orphans.append(kw)
    return orphans


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


def _submit_keywords_next_action(wiki_index: str | None, orphaned_required: list[str]) -> str:
    if not wiki_index:
        return "parse_initial"
    return "add_story_first" if orphaned_required else "fetch_wiki_then_tailor"


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

    data: dict = {"keywords": state.get("keywords")}

    if state.get("sections"):
        data["sections"] = state.get("sections")

    orphaned_required: list[str] = []
    score = state.get("score_initial")
    if score:
        data["score_gap"] = {
            "required_missing": score.get("req_unmatched", []),
            "preferred_missing": score.get("pref_unmatched", []),
        }
        orphaned_required = _detect_orphaned_required(
            score.get("req_unmatched", []),
            state.get("sections") or {},
            state.get("wiki_index") or "",
        )
        data["orphaned_required"] = orphaned_required

    if state.get("wiki_index"):
        data["wiki_index"] = state.get("wiki_index")
        data["tailor_instructions"] = _TAILOR_INSTRUCTIONS
    next_action = _submit_keywords_next_action(state.get("wiki_index"), orphaned_required)
    return _ok(session_id, next_action, data)


@mcp.tool()
def submit_tailor(session_id: str, edits: list[dict], no_coverage: bool = False) -> str:
    """Apply host-submitted edits to the resume SectionMap and run the graph to finalize.

    Accepts a list of port.Edit-style dicts. Each edit must have:
      section: str (summary | skills | experience | projects)
      op: str (add | replace | remove)
      target: str (required for experience/projects)
      value: str (required for add/replace)
      category: str (optional, for categorized skills)

    When no_coverage=True, skips edit application entirely, sets no_coverage in
    graph state, and runs the graph directly to finalize.

    Applies valid edits (or skips on no_coverage), runs the graph through finalize,
    and returns real score_final and report from final graph state.

    Returns JSON envelope with edits_applied, edits_rejected, uncovered_skills,
    score_final, report, and outcome.
    """
    _log("INFO", {"tool": "submit_tailor", "session_id": session_id, "edit_count": len(edits)})

    graph = build_apply_graph()
    config = make_apply_config(session_id)
    snapshot = graph.get_state(config)

    if not snapshot.values:
        return _err("submit_tailor", "session_not_found", "session_id not found", session_id)

    if snapshot.next != (TAILOR_NODE,):
        return _err(
            "submit_tailor",
            "invalid_state",
            "session is not waiting for tailor edits",
            session_id,
        )

    if no_coverage:
        graph.update_state(config, {"no_coverage": True})
        graph.invoke(None, config)
        final_snapshot = graph.get_state(config)
        final = final_snapshot.values
        if final.get("error"):
            return _err("submit_tailor", "pipeline_error", final["error"], session_id)
        return _ok(
            session_id,
            next_action=None,
            data={
                "edits_applied": [],
                "edits_rejected": [],
                "uncovered_skills": [],
                "score_final": final.get("score_final"),
                "report": final.get("report"),
                "outcome": (final.get("report") or {}).get("no_coverage")
                and {
                    "no_coverage": True,
                    "reason": "no wiki stories cover required keywords",
                }
                or {"no_coverage": False, "reason": None},
            },
        )

    state_values = snapshot.values
    sections_dict = state_values.get("sections")
    if not sections_dict:
        return _err(
            "submit_tailor",
            "no_sections",
            "no sections in session; call load_jd with a resume_path first",
            session_id,
        )

    return _apply_tailor_edits(session_id, graph, config, state_values, sections_dict, edits)


def _apply_tailor_edits(session_id, graph, config, state_values, sections_dict, edits):
    """Apply edits to the SectionMap, run the graph to finalize, and return real scores."""
    section_map = SectionMap.model_validate(sections_dict)
    edits_applied = []
    edits_rejected = []

    for i, edit in enumerate(edits):
        result = apply_edit(section_map, edit)
        if result.applied:
            edits_applied.append(i)
        else:
            edits_rejected.append({"index": i, "reason": result.rejection_reason})

    uncovered_skills = _detect_uncovered_skills(section_map)

    graph.update_state(
        config,
        {
            "tailored_sections": section_map.model_dump(),
            "uncovered_skills": uncovered_skills,
        },
    )
    graph.invoke(None, config)

    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return _err("submit_tailor", "pipeline_error", final["error"], session_id)
    return _ok(
        session_id,
        next_action=None,
        data={
            "edits_applied": edits_applied,
            "edits_rejected": edits_rejected,
            "uncovered_skills": uncovered_skills,
            "score_final": final.get("score_final"),
            "report": final.get("report"),
            "outcome": (final.get("report") or {}).get("no_coverage")
            and {
                "no_coverage": True,
                "reason": "no wiki stories cover required keywords",
            }
            or {"no_coverage": False, "reason": None},
        },
    )


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
