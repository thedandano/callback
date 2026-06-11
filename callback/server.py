"""MCP server for callback: host handoff and profile management.

Exposes eight tools:
1. load_jd — loads JD markdown and returns host extraction instructions
2. submit_keywords — accepts host-extracted JDData and returns score/tailor context
3. submit_tailor — accepts host edits and finalizes PDF/report artifacts
4. get_wiki_pages — returns profile wiki pages selected by the host
5. onboard_user — enters profile graph at onboard node
6. compile_profile — enters profile graph at compile_profile node
7. create_story — enters profile graph at create_story node
8. check_update — returns current version, latest release, and update_available flag
"""

import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

import callback.profile_nodes as profile_nodes
import callback.scorer as scorer
import callback.version_check as version_check
from callback.apply_graph import (
    KEYWORDS_ACCEPT_NODE,
    TAILOR_NODE,
    build_apply_graph,
)
from callback.apply_graph import (
    make_config as make_apply_config,
)
from callback.apply_nodes import _detect_uncovered_skills, _get_apps_dir
from callback.jd_data import EXTRACTION_PROTOCOL, JDDataError, parse_jd_json
from callback.jd_fetcher import JDFetchError
from callback.observability import invoke_graph_without_native_tracing, trace_tool
from callback.profile_graph import build_profile_graph
from callback.profile_graph import make_config as make_profile_config
from callback.repository.resumes import list_resumes
from callback.section_map import SectionMap, apply_edit
from callback.state import ApplyState, ProfileState
from callback.wiki import WikiStore

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = "%(message)s"  # messages are already JSON strings
_LOG_PATH: Path | None = None
DEFAULT_LOG_PATH = Path("~/.local/state/callback/server.log").expanduser()


def configure_logging(log_path: str | Path | None = None) -> None:
    """Configure stderr logging plus an optional server log file."""
    global _LOG_PATH
    logging.basicConfig(
        level=LOG_LEVEL,
        format=_LOG_FORMAT,
        stream=sys.stderr,
    )
    if log_path is None:
        return

    path = Path(log_path).expanduser()
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    for handler in root.handlers:
        if getattr(handler, "_callback_log_path", None) == str(path):
            _LOG_PATH = path
            return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as exc:
        _LOG_PATH = None
        root.warning(
            json.dumps(
                {
                    "event": "file_logging_disabled",
                    "path": str(path),
                    "error": str(exc),
                }
            )
        )
        return

    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(LOG_LEVEL)
    handler._callback_log_path = str(path)  # type: ignore[attr-defined]
    root.addHandler(handler)
    _LOG_PATH = path


configure_logging(os.environ.get("CALLBACK_LOG_PATH"))
logger = logging.getLogger(__name__)


def _write_log_line(line: str) -> None:
    """Write directly to the callback log file if configured."""
    global _LOG_PATH
    if _LOG_PATH is None:
        return
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        _LOG_PATH = None


def _log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    payload["level"] = level
    line = json.dumps(payload)
    _write_log_line(line)
    logger.info(line)


def _log_exception(payload: dict) -> None:
    """Log an exception payload plus traceback to stderr and the server log file."""
    payload["traceback"] = traceback.format_exc()
    line = json.dumps(payload)
    _write_log_line(line)
    logger.exception(line)


def _ensure_browsers() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
    )
    if result.returncode != 0:
        _log("WARNING", {"event": "browser_install_failed", "returncode": result.returncode})


async def _startup_version_check() -> None:
    info = await asyncio.to_thread(version_check.check_update)
    if info.get("update_available"):
        _log(
            "INFO",
            {
                "event": "update_available",
                "current": info.get("current"),
                "latest": info.get("latest"),
            },
        )


@asynccontextmanager
async def _lifespan(server: object) -> AsyncIterator[None]:
    asyncio.create_task(_startup_version_check())
    yield


_TAILOR_INSTRUCTIONS = (
    "V4 voice constraints:\n"
    "- Bullets: past-tense action verb + mechanism (HOW) + metric from wiki. "
    "Banned verbs: spearheaded, orchestrated, championed, leveraged, utilized, streamlined.\n"
    "- Summary: ≤3 sentences, ≥1 quantified anchor. "
    "Banned: passionate, driven, results-oriented, proven track record.\n"
    "- Context line per role: <Role> · <Domain/Team> · <Scale signal> · <Stack>"
    " — factual only, no adjectives.\n"
    "- Skills: every keyword added to skills MUST appear in ≥1 dated experience bullet.\n"
    "- Projects: use existing project descriptions or bullets when a missing required or "
    "preferred keyword is truthfully supported by project evidence rather than dated "
    "experience evidence. Project edits MUST be grounded in the source resume or "
    "profile wiki and MUST NOT invent project facts, metrics, scope, users, dates, "
    "employer context, or keyword-only text. Project evidence does not satisfy Skills "
    "coverage unless the keyword also appears in a dated experience bullet. When "
    "project_candidates are present, compare them against the visible resume project "
    "and prefer up to two visible projects when both projects improve JD keyword "
    "match or theme. Remove or shorten low-score, off-theme visible bullets before "
    "adding a second project. If two projects are already visible, replace the "
    "weakest visible project only when the candidate better fits the JD keywords "
    "or theme."
)

mcp = FastMCP("callback", lifespan=_lifespan)

_NEXT_EXTRACT_KEYWORDS = "extract_keywords"
_NEXT_ONBOARD_RESUME_FIRST = "onboard_resume_first"
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


_WIKI_LINK_RE = re.compile(r"\[[^\]]+\]\((experience/[^)]+\.md)\)")


def _keyword_matches_text(keyword: str, text: str) -> bool:
    normalized_keyword = scorer._normalize_for_match(keyword)
    if not normalized_keyword:
        return False
    normalized_text = scorer._normalize_for_match(text)
    return bool(scorer._compile_keyword_pattern(normalized_keyword).search(normalized_text))


def _matched_keywords(keywords: list[str], text: str) -> list[str]:
    return [keyword for keyword in keywords if _keyword_matches_text(keyword, text)]


def _project_story_name(content: str) -> str:
    first_line = next(
        (line.removeprefix("#").strip() for line in content.splitlines() if line.startswith("#")),
        "",
    )
    return re.sub(r"\s+—\s+Sbi$", "", first_line)


def _project_story_skills(content: str) -> list[str]:
    match = re.search(r"^Skills:\s*(.+)$", content, re.MULTILINE)
    if not match:
        return []
    return [skill.strip() for skill in match.group(1).split(",") if skill.strip()]


def _is_project_story(content: str) -> bool:
    return bool(re.search(r"^\*\*Job Title:\*\*\s*Project\s*$", content, re.MULTILINE))


def _evidence_preview(content: str) -> str:
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("**Job Title:**")
    ]
    return re.sub(r"\s+", " ", " ".join(lines))[:240]


def _project_score(required: list[str], preferred: list[str], text: str) -> float:
    possible = len(required) * 2 + len(preferred)
    if possible == 0:
        return 0.0
    matched = len(_matched_keywords(required, text)) * 2 + len(_matched_keywords(preferred, text))
    return round(matched / possible, 4)


def _project_page_ids(wiki_index: str) -> list[str]:
    seen: set[str] = set()
    page_ids: list[str] = []
    for match in _WIKI_LINK_RE.finditer(wiki_index):
        page_id = match.group(1)
        if page_id not in seen:
            seen.add(page_id)
            page_ids.append(page_id)
    return page_ids


def _rank_project_candidates(resume_label: str, keywords: dict, wiki_index: str) -> list[dict]:
    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    page_ids = _project_page_ids(wiki_index)
    pages = WikiStore().read_pages(resume_label, page_ids)
    candidates: list[dict] = []
    for page_id in page_ids:
        content = pages.get(page_id) or ""
        if not _is_project_story(content):
            continue
        required_matched = _matched_keywords(required, content)
        preferred_matched = _matched_keywords(preferred, content)
        score = _project_score(required, preferred, content)
        if score == 0:
            continue
        candidates.append(
            {
                "page_id": page_id,
                "name": _project_story_name(content),
                "skills": _project_story_skills(content),
                "score": score,
                "required_matched": required_matched,
                "preferred_matched": preferred_matched,
                "evidence_preview": _evidence_preview(content),
            }
        )
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate["score"],
            len(candidate["required_matched"]),
            len(candidate["preferred_matched"]),
            candidate["name"],
        ),
        reverse=True,
    )


def _project_text(project: dict) -> str:
    parts = [project.get("name") or "", project.get("description") or ""]
    parts.extend(project.get("bullets") or [])
    return "\n".join(parts)


def _project_swap_recommendation(
    candidates: list[dict], keywords: dict, sections: dict
) -> dict | None:
    projects = sections.get("projects") or []
    if not candidates or not projects:
        return None

    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    scored_projects = [
        (index, _project_score(required, preferred, _project_text(project)))
        for index, project in enumerate(projects)
    ]
    replace_index, visible_score = min(scored_projects, key=lambda item: item[1])
    candidate = candidates[0]
    if candidate["score"] <= visible_score:
        return None
    return {
        "replace_target": f"proj-{replace_index}",
        "visible_project_score": visible_score,
        "candidate": candidate,
    }


_MAX_VISIBLE_PROJECTS = 2


def _project_layout_recommendation(candidates: list[dict], keywords: dict, sections: dict) -> dict:
    recommendation: dict = {
        "strategy": "none",
        "max_visible_projects": _MAX_VISIBLE_PROJECTS,
    }
    if not candidates:
        return recommendation

    projects = sections.get("projects") or []
    if len(projects) < _MAX_VISIBLE_PROJECTS:
        return {
            **recommendation,
            "strategy": "append",
            "add_target": "proj-end",
            "candidate": candidates[0],
        }

    swap = _project_swap_recommendation(candidates, keywords, sections)
    if not swap:
        return recommendation
    return {
        **recommendation,
        "strategy": "replace",
        "replace_target": swap["replace_target"],
        "visible_project_score": swap["visible_project_score"],
        "candidate": swap["candidate"],
    }


def _bullet_trim_candidate(section: str, target: str, text: str, keywords: dict) -> dict:
    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    return {
        "target": target,
        "section": section,
        "text": text,
        "required_matched": _matched_keywords(required, text),
        "preferred_matched": _matched_keywords(preferred, text),
        "score": _project_score(required, preferred, text),
    }


def _trim_candidates(keywords: dict, sections: dict) -> list[dict]:
    candidates: list[dict] = []
    for exp_index, entry in enumerate(sections.get("experience") or []):
        for bullet_index, bullet in enumerate(entry.get("bullets") or []):
            candidates.append(
                _bullet_trim_candidate(
                    "experience",
                    f"exp-{exp_index}-b{bullet_index}",
                    str(bullet),
                    keywords,
                )
            )
    for project_index, project in enumerate(sections.get("projects") or []):
        for bullet_index, bullet in enumerate(project.get("bullets") or []):
            candidates.append(
                _bullet_trim_candidate(
                    "projects",
                    f"proj-{project_index}-b{bullet_index}",
                    str(bullet),
                    keywords,
                )
            )
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate["score"],
            len(candidate["required_matched"]),
            len(candidate["preferred_matched"]),
            candidate["target"],
        ),
    )


# ============================================================================
# Envelope helpers
# ============================================================================


def _workflow(
    phase: str,
    next_tool: str | None,
    host_task: str,
    required_input: dict,
    allowed_next_tools: list[str] | None = None,
) -> dict:
    """Build host-facing workflow guidance for the next MCP handoff."""
    workflow = {
        "phase": phase,
        "next_tool": next_tool,
        "host_task": host_task,
        "required_input": required_input,
    }
    if allowed_next_tools:
        workflow["allowed_next_tools"] = allowed_next_tools
    return workflow


def _ok(
    session_id: str,
    next_action: str | None = None,
    data: dict | None = None,
    workflow: dict | None = None,
) -> str:
    """Return a success envelope."""
    env: dict = {"session_id": session_id, "status": "ok"}
    if next_action:
        env["next_action"] = next_action
    if data:
        env["data"] = data
    if workflow:
        env["workflow"] = workflow
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


def _resolve_resume_label(
    resume_label: str | None, session_id: str
) -> tuple[str | None, str | None]:
    """Resolve resume label from registry. Returns (resolved_label, error_json_or_None)."""
    registered = list_resumes()
    if not registered:
        return None, _err(
            stage="load_jd",
            code="no_resume_registered",
            message="no resume registered; run onboard_user first",
            session_id=session_id,
            retriable=False,
        )
    if resume_label is not None:
        if resume_label not in registered:
            return None, _err(
                stage="load_jd",
                code="resume_not_found",
                message=f"resume '{resume_label}' not found; registered: {registered}",
                session_id=session_id,
                retriable=False,
            )
        return resume_label, None
    if len(registered) == 1:
        return registered[0], None
    return None, _err(
        stage="load_jd",
        code="ambiguous_resume",
        message=f"multiple resumes registered; specify resume_label: {registered}",
        session_id=session_id,
        retriable=False,
    )


@mcp.tool()
def load_jd(  # noqa: C901
    jd_url: str | None = None,
    jd_raw_text: str | None = None,
    resume_label: str | None = None,
) -> str:
    """Load a job description and return host extraction instructions.

    Takes a job description via jd_url, jd_raw_text, or both. At least one is
    required. When both are supplied, the graph attempts jd_url first and keeps
    jd_raw_text as fallback only for URL fetch failures. Empty URL content is
    reported as an error and does not fall back to pasted text.

    The resume is resolved from the internal registry. If resume_label is
    omitted and exactly one resume is registered, it is auto-selected. When
    multiple resumes are registered, resume_label is required for disambiguation.

    Args:
        jd_url: URL to a job description.
        jd_raw_text: Raw job description text.
        resume_label: Label of the registered resume to use. Optional when
            exactly one resume is registered.

    Returns:
        JSON envelope with status, session_id, jd_text, extraction_protocol, and
        workflow guidance telling the host to call submit_keywords next.
    """
    session_id = str(uuid.uuid4())
    return _load_jd_impl(
        session_id,
        jd_raw_text,
        jd_url=jd_url,
        resume_label=resume_label,
    )


@trace_tool("load_jd", graph_name="apply")
def _load_jd_impl(  # noqa: C901
    session_id: str,
    jd_raw_text: str | None,
    *,
    jd_url: str | None = None,
    resume_label: str | None = None,
) -> str:
    if not (jd_url or jd_raw_text):
        return _err(
            "load_jd",
            "missing_input",
            "neither jd_url nor jd_raw_text provided",
            session_id=session_id,
        )

    resolved_label, err = _resolve_resume_label(resume_label, session_id)
    if err:
        return err

    _log("INFO", {"tool": "load_jd", "session_id": session_id, "resume_label": resolved_label})

    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        jd_raw_text=jd_raw_text,
        resume_label=resolved_label,
    )

    try:
        graph = build_apply_graph()
        config = make_apply_config(
            session_id,
            tool_name="load_jd",
            resume_label=resolved_label,
        )
        state = invoke_graph_without_native_tracing(graph, initial_state, config)
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
    except sqlite3.OperationalError:
        _log_exception(
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "session_store_error",
            }
        )
        return _err(
            stage="load_jd",
            code="session_store_error",
            message="unable to create or update apply session store",
            session_id=session_id,
            retriable=True,
        )
    except Exception:
        _log_exception(
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "unexpected_error",
            }
        )
        return _err(
            stage="load_jd",
            code="unexpected_error",
            message="unexpected load_jd failure; inspect callback logs",
            session_id=session_id,
            retriable=False,
        )

    data = {
        "jd_text": state.get("jd_text"),
        "extraction_protocol": EXTRACTION_PROTOCOL,
    }
    workflow = _workflow(
        phase="keyword_extraction",
        next_tool="submit_keywords",
        host_task=(
            "Extract compact JDData JSON from data.jd_text using "
            "data.extraction_protocol, then call submit_keywords."
        ),
        required_input={
            "session_id": session_id,
            "jd_json": "<compact JDData JSON string>",
        },
    )
    return _ok(session_id, _NEXT_EXTRACT_KEYWORDS, data, workflow)


def _submit_keywords_next_action(wiki_index: str | None, orphaned_required: list[str]) -> str:
    if not wiki_index:
        return _NEXT_ONBOARD_RESUME_FIRST
    return _NEXT_ADD_STORY_FIRST if orphaned_required else _NEXT_FETCH_WIKI_THEN_TAILOR


def _submit_keywords_workflow(
    session_id: str,
    next_action: str,
    orphaned_required: list[str],
) -> dict:
    if next_action == _NEXT_ONBOARD_RESUME_FIRST:
        return _workflow(
            phase="onboard_resume",
            next_tool="onboard_user",
            host_task=(
                "Tailoring needs onboarded resume sections and profile wiki context. "
                "Call onboard_user, compile the profile, then restart this job flow "
                "with load_jd using the same job description."
            ),
            required_input={
                "resume_path": "<path to PDF, DOCX, TXT, or Markdown resume>",
                "skills_path": "<optional path to skills file>",
                "accomplishments_path": "<optional path to accomplishments file>",
            },
        )
    if next_action == _NEXT_ADD_STORY_FIRST:
        return _workflow(
            phase="story_evidence",
            next_tool="create_story",
            host_task=(
                "Collect or create truthful story evidence for orphaned required "
                "keywords before tailoring. After create_story and compile_profile, "
                "restart this job flow with load_jd using the same job description."
            ),
            required_input={
                "primary_skill": (
                    orphaned_required[0] if orphaned_required else "<required keyword>"
                ),
                "skills": orphaned_required or ["<required keyword>"],
                "story_type": "STAR",
                "job_title": "<role title for the evidence>",
                "situation": "<truthful situation>",
                "behavior": "<truthful actions taken>",
                "impact": "<truthful quantified or concrete outcome>",
            },
        )
    return _workflow(
        phase="tailor_evidence",
        next_tool="get_wiki_pages",
        allowed_next_tools=["get_wiki_pages", "submit_tailor"],
        host_task=(
            "Use data.sections, data.score_gap, data.wiki_index, and "
            "data.tailor_instructions to choose relevant wiki pages and prepare "
            "honest SectionMap edits. If the index already contains enough "
            "evidence, submit_tailor is also valid."
        ),
        required_input={
            "session_id": session_id,
            "page_ids": ["experience/<page-id>.md"],
        },
    )


def _complete_workflow() -> dict:
    return _workflow(
        phase="complete",
        next_tool=None,
        host_task="Return the artifact paths, score report, and outcome to the user.",
        required_input={},
    )


def _submit_tailor_artifacts(final: dict, session_id: str) -> dict:
    archive_path = str(_get_apps_dir() / f"{session_id}.json")
    return {
        "pdf_path": final.get("pdf_path"),
        "archive_path": archive_path,
    }


def _resolve_output_dir(output_dir: str | None, session_id: str) -> tuple[str | None, str | None]:
    """Validate and create an optional output_dir for the final PDF.

    Returns (resolved_abs_dir, None) on success (resolved is None when output_dir
    is falsy), or (None, error_envelope) when the path is relative or uncreatable.
    """
    if not output_dir:
        return None, None
    resolved = Path(output_dir).expanduser()
    if not resolved.is_absolute():
        return None, _err(
            "submit_tailor",
            "invalid_output_dir",
            f"output_dir must be an absolute path: {output_dir}",
            session_id,
            retriable=True,
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log(
            "ERROR",
            {
                "tool": "submit_tailor",
                "session_id": session_id,
                "invalid_output_dir": output_dir,
                "error": str(exc),
            },
        )
        return None, _err(
            "submit_tailor",
            "invalid_output_dir",
            f"cannot write to output_dir: {exc}",
            session_id,
            retriable=True,
        )
    return str(resolved), None


@mcp.tool()
def submit_keywords(session_id: str, jd_json: str) -> str:
    """Accept host-extracted JDData and return score gaps plus tailor handoff guidance.

    When profile wiki project stories exist, the response also includes ranked
    project_candidates and an optional project_swap_recommendation for the host
    to consider during tailoring.
    """
    return _submit_keywords_impl(session_id, jd_json)


@trace_tool("submit_keywords", graph_name="apply")
def _submit_keywords_impl(session_id: str, jd_json: str) -> str:
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
    config = make_apply_config(session_id, tool_name="submit_keywords")
    state_error = _submit_keywords_state_error(graph, config, session_id)
    if state_error is not None:
        return state_error

    try:
        graph.update_state(config, {"keywords": keywords})
        state = invoke_graph_without_native_tracing(graph, None, config)
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
        data["trim_candidates"] = _trim_candidates(
            state.get("keywords") or {},
            state.get("sections") or {},
        )

    orphaned_required: list[str] = []
    score = state.get("score_initial")
    if score:
        data["score_gap"] = {
            "required_missing": score.get("req_unmatched", []),
            "preferred_missing": score.get("pref_unmatched", []),
        }
        data["ats_format_gap"] = score.get("ats_diagnostics", [])
        orphaned_required = _detect_orphaned_required(
            score.get("req_unmatched", []),
            state.get("sections") or {},
            state.get("wiki_index") or "",
        )
        data["orphaned_required"] = orphaned_required

    if state.get("wiki_index"):
        data["wiki_index"] = state.get("wiki_index")
        data["tailor_instructions"] = _TAILOR_INSTRUCTIONS
        candidates = _rank_project_candidates(
            state.get("resume_label") or "",
            state.get("keywords") or {},
            state.get("wiki_index") or "",
        )
        data["project_candidates"] = candidates
        data["project_swap_recommendation"] = _project_swap_recommendation(
            candidates,
            state.get("keywords") or {},
            state.get("sections") or {},
        )
        data["project_layout_recommendation"] = _project_layout_recommendation(
            candidates,
            state.get("keywords") or {},
            state.get("sections") or {},
        )
    next_action = _submit_keywords_next_action(state.get("wiki_index"), orphaned_required)
    return _ok(
        session_id,
        next_action,
        data,
        _submit_keywords_workflow(session_id, next_action, orphaned_required),
    )


@mcp.tool()
def submit_tailor(
    session_id: str,
    edits: list[dict],
    no_coverage: bool = False,
    output_dir: str | None = None,
) -> str:
    """Apply host-submitted edits to the resume SectionMap and run the graph to finalize.

    Accepts a list of port.Edit-style dicts. Each edit must have:
      section: str (summary | skills | experience | projects)
      op: str (add | replace | remove)
      target: str (required for experience/projects; use proj-N to replace a whole project,
        proj-end to append one project, exp-N-bM/proj-N-bM to remove bullets)
      value: str | dict (required for add/replace; project add/replacement uses a ProjectEntry dict)
      category: str (optional, for categorized skills)

    output_dir (optional): an absolute directory to write the final PDF into instead of the
    default applications dir. Recommended for sandboxed hosts (Claude/Codex) whose filesystem
    cannot reach callback's default output. The PDF is written there directly (a redirect, not
    a copy); data.pdf_path points inside it. An unwritable path returns an invalid_output_dir
    error rather than silently falling back.

    When no_coverage=True, skips edit application entirely, sets no_coverage in
    graph state, and runs the graph directly to finalize.

    Applies valid edits (or skips on no_coverage), runs the graph through finalize,
    and returns real score_final and report from final graph state.

    Returns JSON envelope with edits_applied, edits_rejected, uncovered_skills,
    pdf_path, archive_path, score_final, report, outcome, and tailor_diagnostics.
    tailor_diagnostics is a per-skill-edit list of {value, applied_to_map,
    present_in_rendered_text, suggested_alternatives} entries; empty for
    non-skill edits.
    report.notes is a list of plain-text messages for ATS format issues in the
    rendered PDF that tailoring cannot fix (closeable_by != "tailor").
    """
    return _submit_tailor_impl(session_id, edits, no_coverage=no_coverage, output_dir=output_dir)


@trace_tool("submit_tailor", graph_name="apply")
def _submit_tailor_impl(
    session_id: str,
    edits: list[dict],
    *,
    no_coverage: bool = False,
    output_dir: str | None = None,
) -> str:
    _log("INFO", {"tool": "submit_tailor", "session_id": session_id, "edit_count": len(edits)})

    graph = build_apply_graph()
    config = make_apply_config(session_id, tool_name="submit_tailor")
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

    resolved_output_dir, output_dir_error = _resolve_output_dir(output_dir, session_id)
    if output_dir_error is not None:
        return output_dir_error

    if no_coverage:
        graph.update_state(config, {"no_coverage": True, "output_dir": resolved_output_dir})
        invoke_graph_without_native_tracing(graph, None, config)
        final_snapshot = graph.get_state(config)
        final = final_snapshot.values
        if final.get("error"):
            return _err("submit_tailor", "pipeline_error", final["error"], session_id)
        artifacts = _submit_tailor_artifacts(final, session_id)
        return _ok(
            session_id,
            next_action=None,
            data={
                "edits_applied": [],
                "edits_rejected": [],
                "uncovered_skills": [],
                "pdf_path": artifacts["pdf_path"],
                "archive_path": artifacts["archive_path"],
                "score_final": final.get("score_final"),
                "report": final.get("report"),
                "tailor_diagnostics": [],
                "outcome": (final.get("report") or {}).get("no_coverage")
                and {
                    "no_coverage": True,
                    "reason": "no wiki stories cover required keywords",
                }
                or {"no_coverage": False, "reason": None},
            },
            workflow=_complete_workflow(),
        )

    state_values = snapshot.values
    sections_dict = state_values.get("sections")
    if not sections_dict:
        return _err(
            "submit_tailor",
            "no_sections",
            "no sections in session; call load_jd first",
            session_id,
        )

    return _apply_tailor_edits(
        session_id, graph, config, state_values, sections_dict, edits, resolved_output_dir
    )


def _apply_tailor_edits(
    session_id, graph, config, state_values, sections_dict, edits, output_dir=None
):
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

    applied_set = set(edits_applied)
    applied_skill_values = [
        edit["value"]
        for i, edit in enumerate(edits)
        if i in applied_set
        and edit.get("section") == "skills"
        and edit.get("op") in ("add", "replace")
        and "value" in edit
    ]

    uncovered_skills = _detect_uncovered_skills(section_map)

    graph.update_state(
        config,
        {
            "tailored_sections": section_map.model_dump(),
            "uncovered_skills": uncovered_skills,
            "applied_skill_values": applied_skill_values,
            "output_dir": output_dir,
        },
    )
    invoke_graph_without_native_tracing(graph, None, config)

    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return _err("submit_tailor", "pipeline_error", final["error"], session_id)
    artifacts = _submit_tailor_artifacts(final, session_id)
    return _ok(
        session_id,
        next_action=None,
        data={
            "edits_applied": edits_applied,
            "edits_rejected": edits_rejected,
            "uncovered_skills": uncovered_skills,
            "pdf_path": artifacts["pdf_path"],
            "archive_path": artifacts["archive_path"],
            "score_final": final.get("score_final"),
            "report": final.get("report"),
            "tailor_diagnostics": final.get("tailor_diagnostics") or [],
            "outcome": (final.get("report") or {}).get("no_coverage")
            and {
                "no_coverage": True,
                "reason": "no wiki stories cover required keywords",
            }
            or {"no_coverage": False, "reason": None},
        },
        workflow=_complete_workflow(),
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
) -> str:
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
    config = make_profile_config(session_id, tool_name="onboard_user")
    invoke_graph_without_native_tracing(graph, initial_state, config)
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

    resume_label, _ = _resolve_resume_label(None, session_id)

    state = ProfileState(
        session_id=session_id,
        resume_label=resume_label,
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
    return _get_wiki_pages_impl(session_id, page_ids)


@trace_tool("get_wiki_pages", graph_name="apply")
def _get_wiki_pages_impl(session_id: str, page_ids: list[str]) -> str:
    _log("INFO", {"tool": "get_wiki_pages", "session_id": session_id, "page_count": len(page_ids)})

    graph = build_apply_graph()
    config = make_apply_config(session_id, tool_name="get_wiki_pages")
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
        return _err(
            stage="get_wiki_pages",
            code="no_resume_label",
            message="no resume_label in session; call load_jd first",
            session_id=session_id,
        )

    store = WikiStore()
    pages = store.read_pages(resume_label, page_ids)
    workflow = _workflow(
        phase="tailor_editing",
        next_tool="submit_tailor",
        host_task=(
            "Use these pages with the previously returned sections, score gaps, "
            "and tailor instructions to construct honest edits, then call submit_tailor."
        ),
        required_input={
            "session_id": session_id,
            "edits": [
                {
                    "section": "experience",
                    "op": "replace",
                    "target": "exp-0-b0",
                    "value": "<truthful revised bullet>",
                }
            ],
            "no_coverage": False,
        },
    )
    return _ok(session_id, data={"pages": pages}, workflow=workflow)


# ============================================================================
# Utility tools
# ============================================================================


@mcp.tool()
def check_update() -> str:
    """Return current version, latest GitHub release tag, and update_available flag."""
    return _ok("", data=version_check.check_update())


def run() -> None:
    """Run the FastMCP stdio server."""
    if _LOG_PATH is None:
        configure_logging(os.environ.get("CALLBACK_LOG_PATH") or DEFAULT_LOG_PATH)
    started_at = time.monotonic()
    _log(
        "INFO",
        {
            "event": "server_start",
            "transport": "stdio",
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "log_path": str(_LOG_PATH) if _LOG_PATH is not None else None,
        },
    )
    try:
        mcp.run(transport="stdio", show_banner=False)
    except Exception as exc:
        _log_exception(
            {
                "event": "server_crash",
                "transport": "stdio",
                "pid": os.getpid(),
                "uptime_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
        raise RuntimeError("callback MCP stdio server crashed") from exc
    finally:
        _log(
            "INFO",
            {
                "event": "server_stop",
                "transport": "stdio",
                "pid": os.getpid(),
                "uptime_ms": int((time.monotonic() - started_at) * 1000),
            },
        )


if __name__ == "__main__":
    run()
