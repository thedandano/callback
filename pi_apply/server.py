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
from pathlib import Path

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
from pi_apply.profile_graph import build_profile_graph
from pi_apply.profile_graph import make_config as make_profile_config
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

_NEXT_EXTRACT_KEYWORDS = "extract_keywords"
_NEXT_PARSE_INITIAL = "parse_initial"
_NEXT_FETCH_WIKI_THEN_TAILOR = "fetch_wiki_then_tailor"
_NEXT_ADD_STORY_FIRST = "add_story_first"


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
    return _ok(session_id, _NEXT_EXTRACT_KEYWORDS, data)


def _submit_keywords_next_action(wiki_index: str | None, orphaned_required: list[str]) -> str:
    if not wiki_index:
        return _NEXT_PARSE_INITIAL
    return _NEXT_ADD_STORY_FIRST if orphaned_required else _NEXT_FETCH_WIKI_THEN_TAILOR


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


@mcp.tool()
def onboard_user(
    resume_path: str | None = None,
    skills_path: str | None = None,
    accomplishments_path: str | None = None,
) -> str:
    """Onboard a new user: register resume, skills, and accomplishments.

    Args:
        resume_path: Path to the resume file (PDF, DOCX, or TXT).
        skills_path: Optional path to a plain-text skills file.
        accomplishments_path: Optional path to a plain-text accomplishments file.

    Returns:
        JSON envelope with status ok, next_action=compile_profile, and data
        containing intake, resume_label, sections, and optional warnings.
    """
    session_id = str(uuid.uuid4())
    _log(
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
        return _err(
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
    graph = build_profile_graph()
    config = make_profile_config(session_id)
    graph.invoke(initial_state, config)
    state_values = graph.get_state(config).values

    return _ok(session_id, "compile_profile", _build_onboard_data(state_values, warnings))


@mcp.tool()
def compile_profile(story_tags: str | None = None) -> str:
    """Recompile the user profile from all stored stories.

    Args:
        story_tags: Optional JSON string. Accepts a dict (keys become host_tags)
            or a list of skill strings.

    Returns:
        JSON envelope with compiled_profile, skill_coverage_warnings, and skills_index.
    """
    session_id = str(uuid.uuid4())
    _log(
        "INFO",
        {
            "tool": "compile_profile",
            "session_id": session_id,
            "has_story_tags": story_tags is not None,
        },
    )

    host_tags = _parse_story_tags(story_tags)
    if host_tags is None:
        return _err(
            stage="compile_profile",
            code="invalid_story_tags",
            message="story_tags must be a JSON dict or list",
            session_id=session_id,
            retriable=True,
        )

    state = ProfileState(
        session_id=session_id,
        compiled_profile={"host_tags": host_tags} if host_tags else None,
    )
    delta = profile_nodes.compile_profile(state)
    intake = delta.get("intake") or {}
    data = {
        "compiled_profile": delta.get("compiled_profile") or {},
        "skill_coverage_warnings": intake.get("skill_coverage_warnings", []),
        "skills_index": intake.get("skills_index", []),
    }
    return _ok(session_id, None, data)


@mcp.tool()
def create_story(
    primary_skill: str,
    skills: list[str],
    story_type: str,
    job_title: str,
    situation: str,
    behavior: str,
    impact: str,
) -> str:
    """Create and persist a behavioral story for a skill.

    Args:
        primary_skill: The main skill this story demonstrates.
        skills: All skills this story demonstrates (must include primary_skill).
        story_type: Story format (e.g., STAR, CAR, PAR).
        job_title: Role title for this story.
        situation: Context / problem statement.
        behavior: Actions taken.
        impact: Quantified outcome.

    Returns:
        JSON envelope with story_id, primary_skill, and needs_compile=true.
    """
    session_id = str(uuid.uuid4())
    _log(
        "INFO",
        {
            "tool": "create_story",
            "session_id": session_id,
            "primary_skill": primary_skill,
            "story_type": story_type,
            "job_title": job_title,
        },
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
    state = ProfileState(session_id=session_id, intake=intake)
    delta = profile_nodes.create_story(state)
    saved_intake = delta.get("intake") or {}
    data = {
        "story_id": saved_intake.get("story_id"),
        "primary_skill": primary_skill,
        "needs_compile": True,
    }
    return _ok(session_id, "compile_profile", data)


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
            resume_label = Path(resume_path).stem
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
