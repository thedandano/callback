"""MCP server for callback: host handoff and profile management.

Exposes thirteen tools:
1. load_jd — loads JD markdown and returns host extraction instructions
2. submit_keywords — accepts host-extracted JDData and returns score/tailor context
3. submit_tailor — accepts host edits and finalizes PDF/report artifacts
4. get_wiki_pages — returns profile wiki pages selected by the host
5. onboard_user — enters profile graph at onboard node
6. compile_profile — enters profile graph at compile_profile node
7. create_story — enters profile graph at create_story node
8. check_update — returns current version, latest release, and update_available flag
9. get_search_preferences, 10. set_search_preferences — job-search preferences
11. find_job, 12. record_status, 13. export_ledger — the application ledger
"""

import asyncio
import csv
import datetime
import io
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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import ValidationError

import callback.scorer as scorer
import callback.version_check as version_check
from callback import ledger, paths, settings
from callback.apply_graph import (
    FINALIZE_NODE,
    KEYWORDS_ACCEPT_NODE,
    PARSE_FINAL_NODE,
    RENDER_NODE,
    REPORT_NODE,
    SCORE_FINAL_NODE,
    SCORE_INITIAL_NODE,
    TAILOR_NODE,
    get_apply_graph,
)
from callback.apply_graph import (
    make_config as make_apply_config,
)
from callback.apply_nodes import _detect_uncovered_skills
from callback.jd_data import EXTRACTION_PROTOCOL, JDDataError, parse_jd_json
from callback.jd_fetcher import JDFetchError
from callback.observability import invoke_graph_without_native_tracing, record_decision, trace_tool
from callback.preferences import SearchPreferences
from callback.profile_graph import get_profile_graph, story_pending
from callback.profile_graph import make_config as make_profile_config
from callback.repository.preferences import PreferencesStore
from callback.repository.resumes import list_resumes
from callback.repository.stories import label_line_field, tags_from_meta
from callback.section_map import SectionMap, SkillsSection, apply_edit
from callback.state import ApplyState, CreatedStory, ProfileState
from callback.wiki import WikiPageError, WikiPageIdError, WikiStore, split_frontmatter

# Must run before any module-level os.environ read below (e.g. LOG_LEVEL): callback
# owns its own settings file (~/.config/callback/env.json) independent of any MCP
# host config, and env vars set only there would otherwise be invisible here.
# A damaged env.json must not crash the import itself (both `callback serve` and
# `python -m callback.server` import this module directly), so it's reported and
# skipped here rather than raised, same as the CLI's own root-callback recovery.
try:
    settings.apply_env_file()
except ValueError as exc:
    print(
        f"warning: {exc}; continuing without settings-file overrides. "
        "Run `callback config status` to inspect it, or fix/remove it by hand.",
        file=sys.stderr,
    )

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = "%(message)s"  # messages are already JSON strings
_LOG_ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB; one previous log is kept as server.log.1
_LOG_PATH: Path | None = None


def _rotate_if_large(path: Path) -> None:
    """Move an oversized log aside before opening it.

    ponytail: rotates only at startup, not mid-run, because several `callback serve`
    processes can share one log and RotatingFileHandler breaks when they do. A process
    that runs for weeks can still grow its log; switch to a per-process log if that happens.
    A second server started after the log passes 10 MB renames the file while the first still
    writes to it, so the first server's lines go to server.log.1 until it restarts. The
    upgrade path is per-process log files.
    """
    if path.exists() and path.stat().st_size > _LOG_ROTATE_BYTES:
        path.replace(path.with_name(f"{path.name}.1"))


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
        _rotate_if_large(path)
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


def _log(level: str, payload: dict) -> None:
    """Log a structured JSON message."""
    payload["timestamp"] = datetime.datetime.now(datetime.UTC).isoformat()
    payload["level"] = level
    logger.log(getattr(logging, level, logging.INFO), json.dumps(payload))


def _log_exception(payload: dict) -> None:
    """Log an exception payload plus traceback to stderr and the server log file."""
    payload["traceback"] = traceback.format_exc()
    logger.exception(json.dumps(payload))


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


async def _startup_ensure_browsers() -> None:
    _log("INFO", {"event": "browser_ensure_start"})
    await asyncio.to_thread(_ensure_browsers)


@asynccontextmanager
async def _lifespan(server: object) -> AsyncIterator[None]:
    asyncio.create_task(_startup_version_check())
    asyncio.create_task(_startup_ensure_browsers())
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


def _detect_orphaned_required(
    required_missing: list[str], sections: dict, wiki_index: str
) -> list[str]:
    """Return required_missing keywords that are orphans.

    An orphan is a keyword that IS in the candidate's SectionMap skills but is
    NOT yet covered by any wiki story. Skills membership uses case-insensitive
    exact match; wiki_index uses case-insensitive substring search (the index is
    unstructured markdown text).
    """
    skills = sections.get("skills") or {}
    all_skills = SkillsSection(
        flat=skills.get("flat") or [], categorized=skills.get("categorized") or {}
    ).all_skills()
    all_skills_lower = [s.lower() for s in all_skills]
    orphans: list[str] = []
    for kw in required_missing:
        in_skills = kw.lower() in all_skills_lower
        in_wiki = bool(re.search(rf"\b{re.escape(kw)}\b", wiki_index, re.IGNORECASE))
        if in_skills and not in_wiki:
            orphans.append(kw)
    return orphans


_WIKI_LINK_RE = re.compile(r"\[[^\]]+\]\((experience/[^)]+\.md)\)")


def _keyword_matches_text(keyword: str, text: str) -> bool:
    normalized_keyword = scorer.normalize_for_match(keyword)
    if not normalized_keyword:
        return False
    normalized_text = scorer.normalize_for_match(text)
    return bool(scorer._compile_keyword_pattern(normalized_keyword).search(normalized_text))


def _matched_keywords(keywords: list[str], text: str) -> list[str]:
    return [keyword for keyword in keywords if _keyword_matches_text(keyword, text)]


def _read_project_page(resume_label: str, page_id: str) -> str | None:
    """One page's text, or None (logged) when the file cannot be read or decoded."""
    try:
        return WikiStore().read_pages(resume_label, [page_id])[page_id]
    except (UnicodeDecodeError, OSError) as exc:
        _log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": f"{type(exc).__name__}: {exc}",
            },
        )
        return None


def _project_page_meta(page_id: str, content: str) -> dict | None:
    """Frontmatter of a project page; None (logged) for non-projects and unreadable pages."""
    try:
        meta, _ = split_frontmatter(content)
    except WikiPageError as exc:
        _log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": str(exc),
            },
        )
        return None
    if not meta:
        _log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_without_frontmatter",
                "page_id": page_id,
            },
        )
        return None
    if meta.get("type") != "project":
        return None
    try:
        meta["tags"] = tags_from_meta(meta)
    except WikiPageError as exc:
        _log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": str(exc),
            },
        )
        return None
    return meta


def _evidence_preview(content: str) -> str:
    lines = [
        line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")
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


def _valid_project_page_ids(resume_label: str, page_ids: list[str]) -> list[str]:
    """Return page_ids that resolve under the wiki root, logging any that don't."""
    store = WikiStore()
    valid_ids: list[str] = []
    for page_id in page_ids:
        if store.is_valid_page_id(resume_label, page_id):
            valid_ids.append(page_id)
        else:
            _log(
                "WARNING",
                {
                    "tool": "submit_keywords",
                    "event": "invalid_wiki_link_skipped",
                    "page_id": page_id,
                },
            )
    return valid_ids


def _candidate(
    page_id: str,
    meta: dict,
    body: str,
    required: list[str],
    preferred: list[str],
) -> dict:
    skills = [str(tag) for tag in (meta.get("tags") or [])]
    title = str(meta.get("title") or "")
    # Headings are dropped: the frontmatter title is the authoritative name, and a
    # stale H1 left behind by a hand edit must not keep matching the old skill.
    paragraphs = "\n".join(line for line in body.splitlines() if not line.startswith("#"))
    match_text = f"{title}\n{paragraphs}\n{', '.join(skills)}"
    return {
        "page_id": page_id,
        "name": str(meta.get("title") or ""),
        "skills": skills,
        "score": _project_score(required, preferred, match_text),
        "required_matched": _matched_keywords(required, match_text),
        "preferred_matched": _matched_keywords(preferred, match_text),
        "evidence_preview": _evidence_preview(body),
    }


def _rank_project_candidates(resume_label: str, keywords: dict, wiki_index: str) -> list[dict]:
    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    page_ids = _valid_project_page_ids(resume_label, _project_page_ids(wiki_index))
    candidates: list[dict] = []
    for page_id in page_ids:
        content = _read_project_page(resume_label, page_id)
        if content is None:
            continue
        meta = _project_page_meta(page_id, content)
        if meta is None:
            continue
        _, body = split_frontmatter(content)
        candidate = _candidate(page_id, meta, body, required, preferred)
        if candidate["score"] == 0:
            continue
        candidates.append(candidate)
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
) -> dict:
    """Return a success envelope."""
    env: dict = {"session_id": session_id, "status": "ok"}
    if next_action:
        env["next_action"] = next_action
    if data:
        env["data"] = data
    if workflow:
        env["workflow"] = workflow
    return env


def _err(
    stage: str,
    code: str,
    message: str,
    session_id: str | None = None,
    retriable: bool = False,
    data: dict | None = None,
    host_action: str | None = None,
) -> dict:
    """Return an error envelope.

    `data` carries explicit nulls for artifacts that were not produced, so the
    host cannot mistake an absent field for a partial success. `host_action` is
    a machine-readable directive telling the host what to do instead of
    synthesizing the missing output itself.
    """
    error: dict = {
        "stage": stage,
        "code": code,
        "message": message,
        "retriable": retriable,
    }
    if host_action is not None:
        error["host_action"] = host_action
    env: dict = {
        "status": "error",
        "error": error,
    }
    if data is not None:
        env["data"] = data
    if session_id is not None:
        env["session_id"] = session_id
    return env


def _graph_or_err(factory: Callable[[], Any], session_id: str | None) -> tuple[Any, dict | None]:
    """Build a graph, or return an error envelope when the session store cannot be opened."""
    try:
        return factory(), None
    except PermissionError as exc:
        _log_exception({"event": "unsafe_session_dir", "session_id": session_id})
        return None, _err(
            stage="session_store",
            code="unsafe_session_dir",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
    except (sqlite3.Error, OSError) as exc:
        # Locked, corrupt, read-only, or full session store: report it, don't leak a raw error.
        _log_exception({"event": "session_store_error", "session_id": session_id})
        return None, _err(
            stage="session_store",
            code="session_store_error",
            message=f"unable to open session store: {exc}",
            session_id=session_id,
            retriable=True,
        )


def _unexpected_error(stage: str, session_id: str) -> dict:
    """Log the active exception with traceback and return an unexpected_error envelope."""
    _log_exception({"tool": stage, "session_id": session_id, "event": "unexpected_error"})
    return _err(
        stage=stage,
        code="unexpected_error",
        message=f"unexpected {stage} failure; inspect callback logs",
        session_id=session_id,
        retriable=False,
    )


def _submit_keywords_state_error(graph, config, session_id: str) -> dict | None:
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


def _resolve_resume_label(session_id: str) -> tuple[str | None, dict | None]:
    """Return (label, None) for the registered resume, or (None, error envelope)."""
    registered = list_resumes()
    if not registered:
        return None, _err(
            stage="load_jd",
            code="no_resume_registered",
            message="no resume registered; run onboard_user first",
            session_id=session_id,
            retriable=False,
        )
    if len(registered) > 1:
        _log(
            "WARNING",
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "multiple resumes registered; using first",
                "registered": registered,
            },
        )
    record_decision("resume_pick", "first_of_many" if len(registered) > 1 else "only_one")
    return registered[0], None


@mcp.tool()
def load_jd(
    jd_url: str | None = None,
    jd_raw_text: str | None = None,
) -> dict:
    """Load a job description and return host extraction instructions.

    Takes a job description via jd_url, jd_raw_text, or both. At least one is
    required. When both are supplied, the graph attempts jd_url first and keeps
    jd_raw_text as fallback only for URL fetch failures. Empty URL content is
    reported as an error and does not fall back to pasted text.

    The resume is resolved from the internal registry: the first registered
    resume is used. If more than one is registered, a warning is logged and
    the first one wins.

    Args:
        jd_url: URL to a job description.
        jd_raw_text: Raw job description text.

    Returns:
        Envelope dict (structured content) with status, session_id, jd_text,
        extraction_protocol, and workflow guidance telling the host to call
        submit_keywords next.
    """
    session_id = str(uuid.uuid4())
    return _load_jd_impl(
        session_id,
        jd_raw_text,
        jd_url=jd_url,
    )


@trace_tool("load_jd", graph_name="apply")
def _load_jd_impl(  # noqa: C901
    session_id: str,
    jd_raw_text: str | None,
    *,
    jd_url: str | None = None,
) -> dict:
    if not (jd_url or jd_raw_text):
        return _err(
            "load_jd",
            "missing_input",
            "neither jd_url nor jd_raw_text provided",
            session_id=session_id,
        )

    resolved_label, err = _resolve_resume_label(session_id)
    if err:
        return err

    _log("INFO", {"tool": "load_jd", "session_id": session_id, "resume_label": resolved_label})

    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        jd_raw_text=jd_raw_text,
        resume_label=resolved_label,
    )

    graph, graph_error = _graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    try:
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


def _submit_tailor_artifacts(final: dict) -> dict:
    """This run's PDF and the ledger it was recorded in (one row keyed by session_id)."""
    return {"pdf_path": final.get("pdf_path"), "ledger_path": str(paths.ledger_path())}


def _resolve_output_dir(output_dir: str | None, session_id: str) -> tuple[str | None, dict | None]:
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
def submit_keywords(session_id: str, jd_json: str) -> dict:
    """Accept host-extracted JDData and return score gaps plus tailor handoff guidance.

    When profile wiki project stories exist, the response also includes ranked
    project_candidates and an optional project_swap_recommendation for the host
    to consider during tailoring.
    """
    return _submit_keywords_impl(session_id, jd_json)


def _submit_keywords_invoke(
    graph, config, keywords: dict, session_id: str
) -> tuple[dict, None] | tuple[None, dict]:
    """Update graph state with keywords and invoke the graph, mapping raised errors to envelopes."""
    try:
        graph.update_state(config, {"keywords": keywords})
    except ValueError as exc:
        return None, _err(
            stage="submit_keywords",
            code="invalid_session",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
    try:
        return invoke_graph_without_native_tracing(graph, None, config), None
    except Exception:
        return None, _unexpected_error("submit_keywords", session_id)


def _submit_keywords_session(session_id: str) -> tuple[Any, Any, dict | None]:
    """Open the apply graph and check the session can take keywords; else return the error."""
    graph, graph_error = _graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return None, None, graph_error
    config = make_apply_config(session_id, tool_name="submit_keywords")
    return graph, config, _submit_keywords_state_error(graph, config, session_id)


@trace_tool("submit_keywords", graph_name="apply")
def _submit_keywords_impl(session_id: str, jd_json: str) -> dict:
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

    graph, config, session_error = _submit_keywords_session(session_id)
    if session_error is not None:
        return session_error

    state, invoke_error = _submit_keywords_invoke(graph, config, keywords, session_id)
    if invoke_error is not None:
        return invoke_error
    assert state is not None

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
            "required_missing_any": score.get("req_group_unmatched", []),
            "preferred_missing": score.get("pref_unmatched", []),
            "preferred_missing_any": score.get("pref_group_unmatched", []),
            "required_coverage": score.get("required_coverage"),
            "preferred_coverage": score.get("preferred_coverage"),
            "ats_input_suspect": score.get("ats_input_suspect", False),
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
) -> dict:
    """Apply host-submitted edits to the resume SectionMap and run the graph to finalize.

    Accepts a list of port.Edit-style dicts. Each edit must have:
      section: str (summary | skills | experience | projects)
      op: str (add | replace | remove)
      target: str (required for experience/projects; use proj-N to replace a whole project,
        proj-end to append one project, exp-N-bM/proj-N-bM to remove bullets)
      value: str | dict (required for add/replace; project add/replacement uses a ProjectEntry dict)
      category: str (optional, for categorized skills)

    output_dir (optional): an absolute directory to write the final PDF into
    instead of callback's default dated folder. Recommended for sandboxed hosts (Claude/Codex)
    whose filesystem cannot reach callback's default output. The PDF is written there
    directly (a redirect, not a copy); data.pdf_path points inside it; the run is recorded in
    callback's ledger regardless. An
    unwritable path returns an invalid_output_dir error rather than silently falling back.

    When no_coverage=True, skips edit application entirely, sets no_coverage in
    graph state, and runs the graph directly to finalize.

    Applies valid edits (or skips on no_coverage), runs the graph through finalize,
    and returns real score_final and report from final graph state.

    Returns envelope dict (structured content) with edits_applied, edits_rejected, uncovered_skills,
    pdf_path, ledger_path, score_final, report, outcome, and tailor_diagnostics.
    tailor_diagnostics is a per-skill-edit list of {value, applied_to_map,
    present_in_rendered_text, suggested_alternatives} entries; empty for
    non-skill edits.
    report.notes is a list of plain-text messages for ATS format issues in the
    rendered PDF that tailoring cannot fix (closeable_by != "tailor").
    """
    return _submit_tailor_impl(session_id, edits, no_coverage=no_coverage, output_dir=output_dir)


_STALE_RETRY_KEYS = (
    "tailored",
    "tailored_sections",
    "pdf_path",
    "render_page_count",
    "render_warnings",
    "parsed_final",
    "score_final",
    "report",
    "tailor_diagnostics",
    "uncovered_skills",
    "applied_skill_values",
    "no_coverage",
)


def _tailor_retry_update(graph, config, values: dict, session_id: str) -> None:
    """Log a retry when the session previously errored, then apply the state update.

    Writes as_node=SCORE_INITIAL_NODE explicitly: SCORE_INITIAL_NODE's outgoing
    edge unconditionally targets TAILOR_NODE, so this always re-queues tailor
    as the next pending task. Without an explicit as_node, LangGraph infers the
    last node that wrote state — after an error that is tailor/render/parse_final
    itself, whose outgoing (conditional) edge would re-evaluate against the
    now-cleared error and route past tailor/render entirely instead of retrying
    them.

    On a retry (the session's prior state carries an error), also clear stale
    outputs (_STALE_RETRY_KEYS) from an earlier attempt that got further than
    this one before failing — e.g. an edits attempt that rendered a PDF and
    then failed at parse_final, followed by a no_coverage retry that skips
    render entirely. Without this, the stale pdf_path/tailored content would
    survive into finalize alongside outcome.no_coverage: true. Caller-supplied
    values always win over the stale-clearing defaults.
    """
    snapshot = graph.get_state(config)
    update = values
    retrying = bool(snapshot.values.get("error"))
    record_decision("tailor_attempt", "retry_after_error" if retrying else "first")
    if retrying:
        _log(
            "INFO",
            {"tool": "submit_tailor", "session_id": session_id, "event": "retry_after_error"},
        )
        stale = dict.fromkeys(_STALE_RETRY_KEYS)
        update = {**stale, **values}
    graph.update_state(config, update, as_node=SCORE_INITIAL_NODE)


def _outcome(final: dict) -> dict:
    if (final.get("report") or {}).get("no_coverage"):
        return {"no_coverage": True, "reason": "no wiki stories cover required keywords"}
    return {"no_coverage": False, "reason": None}


def _submit_tailor_no_coverage(session_id: str, graph, config, resolved_output_dir) -> dict:
    """Run the graph for the no_coverage path and build its success/error envelope."""
    _tailor_retry_update(
        graph,
        config,
        {"no_coverage": True, "output_dir": resolved_output_dir, "error": None},
        session_id,
    )
    try:
        invoke_graph_without_native_tracing(graph, None, config)
    except Exception:
        return _unexpected_error("submit_tailor", session_id)
    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return _err(
            "submit_tailor",
            "pipeline_error",
            final["error"],
            session_id,
            retriable=True,
            data={"score_final": None, "pdf_path": None, "ledger_path": None},
            host_action="report_and_wait",
        )
    artifacts = _submit_tailor_artifacts(final)
    return _ok(
        session_id,
        next_action=None,
        data={
            "edits_applied": [],
            "edits_rejected": [],
            "uncovered_skills": [],
            "pdf_path": artifacts["pdf_path"],
            "ledger_path": artifacts["ledger_path"],
            "score_final": final.get("score_final"),
            "report": final.get("report"),
            "tailor_diagnostics": [],
            "outcome": _outcome(final),
        },
        workflow=_complete_workflow(),
    )


_HALTED_APPLY_NODES = (RENDER_NODE, PARSE_FINAL_NODE, SCORE_FINAL_NODE, REPORT_NODE, FINALIZE_NODE)


def _tailor_invalid_state_message(next_nodes: tuple[str, ...]) -> str:
    """Message for a submit_tailor call when the session isn't at the tailor interrupt.

    A session halted mid-pipeline by a raised (uncaught) node exception parks at
    that node rather than at tailor, and is otherwise unreachable through the MCP
    surface — name the node and point the host back to load_jd. Every other
    non-tailor state (never started, or still at keywords_accept) keeps the
    original message.
    """
    if next_nodes and next_nodes[0] in _HALTED_APPLY_NODES:
        return f"session halted at {next_nodes[0]}; start a new session with load_jd"
    return "session is not waiting for tailor edits"


@trace_tool("submit_tailor", graph_name="apply")
def _submit_tailor_impl(
    session_id: str,
    edits: list[dict],
    *,
    no_coverage: bool = False,
    output_dir: str | None = None,
) -> dict:
    _log("INFO", {"tool": "submit_tailor", "session_id": session_id, "edit_count": len(edits)})

    graph, graph_error = _graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_apply_config(session_id, tool_name="submit_tailor")
    snapshot = graph.get_state(config)

    if not snapshot.values:
        return _err("submit_tailor", "session_not_found", "session_id not found", session_id)

    if snapshot.next != (TAILOR_NODE,):
        return _err(
            "submit_tailor",
            "invalid_state",
            _tailor_invalid_state_message(snapshot.next),
            session_id,
        )

    resolved_output_dir, output_dir_error = _resolve_output_dir(output_dir, session_id)
    if output_dir_error is not None:
        return output_dir_error

    if no_coverage:
        return _submit_tailor_no_coverage(session_id, graph, config, resolved_output_dir)

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

    _tailor_retry_update(
        graph,
        config,
        {
            "tailored_sections": section_map.model_dump(),
            "uncovered_skills": uncovered_skills,
            "applied_skill_values": applied_skill_values,
            "output_dir": output_dir,
            "error": None,
        },
        session_id,
    )
    try:
        invoke_graph_without_native_tracing(graph, None, config)
    except Exception:
        return _unexpected_error("submit_tailor", session_id)

    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return _err(
            "submit_tailor",
            "pipeline_error",
            final["error"],
            session_id,
            retriable=True,
            data={"score_final": None, "pdf_path": None, "ledger_path": None},
            host_action="report_and_wait",
        )
    artifacts = _submit_tailor_artifacts(final)
    return _ok(
        session_id,
        next_action=None,
        data={
            "edits_applied": edits_applied,
            "edits_rejected": edits_rejected,
            "uncovered_skills": uncovered_skills,
            "pdf_path": artifacts["pdf_path"],
            "ledger_path": artifacts["ledger_path"],
            "score_final": final.get("score_final"),
            "report": final.get("report"),
            "tailor_diagnostics": final.get("tailor_diagnostics") or [],
            "outcome": _outcome(final),
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
    graph, graph_error = _graph_or_err(get_profile_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_profile_config(session_id, tool_name="onboard_user")
    state_values, invoke_error = _onboard_user_invoke(graph, initial_state, config, session_id)
    if invoke_error is not None:
        return invoke_error
    assert state_values is not None

    return _ok(session_id, "compile_profile", _build_onboard_data(state_values, warnings))


def _onboard_user_invoke(
    graph, initial_state: ProfileState, config, session_id: str
) -> tuple[dict, None] | tuple[None, dict]:
    """Invoke the profile graph and fetch its state, mapping raised errors to envelopes."""
    try:
        invoke_graph_without_native_tracing(graph, initial_state, config)
        return graph.get_state(config).values, None
    except Exception:
        return None, _unexpected_error("onboard_user", session_id)


def _compile_failed_after_save_error(stage: str, session_id: str) -> dict:
    """Build the retriable compile_failed envelope for a story saved before compile raised."""
    message = (
        "profile compile failed; call compile_profile again with this session_id"
        if stage == "compile_profile"
        else "story saved; call compile_profile with this session_id to finish"
    )
    return _err(stage, "compile_failed", message, session_id, retriable=True)


def _profile_failure_error(graph, config, session_id: str, stage: str) -> dict:
    """Classify a failed profile run by the durable checkpoint's pending node.

    The checkpoint read is guarded: an unreadable checkpoint falls through to the
    generic unexpected_error envelope instead of escaping as a raw MCP failure.
    """
    try:
        snapshot = graph.get_state(config)
    except Exception:
        _log_exception({"tool": stage, "session_id": session_id, "event": "checkpoint_error"})
        snapshot = None
    pending = snapshot.next if snapshot is not None else ()
    intake = snapshot.values.get("intake") if snapshot is not None else None
    if pending == ("compile_profile",):
        return _compile_failed_after_save_error(stage, session_id)
    if pending == ("create_story",) and story_pending(intake):
        # The node may have written the story's wiki page before the checkpoint
        # write failed. save_story ignores an identical story, so retrying is safe.
        return _err(
            stage,
            "story_unconfirmed",
            "story save could not be confirmed; call create_story again with this "
            "session_id (an identical story is not saved twice)",
            session_id,
            retriable=True,
        )
    return _err(
        stage=stage,
        code="unexpected_error",
        message=f"unexpected {stage} failure; inspect callback logs",
        session_id=session_id,
        retriable=False,
    )


def _run_profile_thread(graph, config, graph_input, session_id: str, stage: str):
    """Invoke the profile graph; if it paused before create_story with a story pending,
    continue once.

    Returns (final_snapshot, error_envelope_or_None). The snapshot carries both the
    state values and the pending node, so callers never re-read the checkpoint.
    """
    try:
        invoke_graph_without_native_tracing(graph, graph_input, config)
        snapshot = graph.get_state(config)
        if snapshot.next == ("create_story",) and story_pending(snapshot.values.get("intake")):
            invoke_graph_without_native_tracing(graph, None, config)
            snapshot = graph.get_state(config)
    except Exception:
        _log_exception({"tool": stage, "session_id": session_id, "event": "unexpected_error"})
        return None, _profile_failure_error(graph, config, session_id, stage)
    if (snapshot.values.get("intake") or {}).get("status") == "no_resume":
        return None, _err(
            stage, "profile_missing", "no profile; call onboard_user first", session_id
        )
    return snapshot, None


def _profile_thread_data(snapshot) -> tuple[str | None, dict]:
    """Return (next_action, common data) for a profile thread after a run."""
    values = snapshot.values
    paused = snapshot.next == ("create_story",)
    intake = values.get("intake") or {}
    data = {
        "compiled_profile": values.get("compiled_profile") or {},
        "skill_coverage_warnings": intake.get("skill_coverage_warnings", []),
        "skills_index": intake.get("skills_index", []),
        "orphaned_skills": values.get("orphaned_skills") or [],
    }
    return ("create_story" if paused else None), data


def _profile_snapshot_or_error(graph, config, session_id: str, stage: str, waiting_for: str):
    """Validate a host-supplied session before resuming it. Returns (snapshot, error_or_None)."""
    snapshot = graph.get_state(config)
    if not snapshot.values:
        return None, _err(stage, "session_not_found", "session_id not found", session_id)
    if snapshot.next != (waiting_for,):
        return None, _err(
            stage, "invalid_state", f"session is not waiting for {waiting_for}", session_id
        )
    return snapshot, None


def _resume_profile_thread(
    graph,
    config,
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
        _, error = _profile_snapshot_or_error(graph, config, session_id, stage, waiting_for)
        if error:
            return error
        if update is not None:
            graph.update_state(config, update)
    except Exception:
        _log_exception({"tool": stage, "session_id": session_id, "event": "checkpoint_error"})
        return _err(
            stage,
            "checkpoint_error",
            "could not read or update the session checkpoint; inspect callback logs",
            session_id,
            retriable=True,
        )
    return None


@mcp.tool()
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
    _log(
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
        return _err(
            stage="compile_profile",
            code="invalid_story_tags",
            message="story_tags must be a JSON dict or list",
            session_id=session_id,
            retriable=True,
        )
    explicit = story_tags is not None
    return _compile_profile_impl(session_id, host_tags, resumed=resumed, explicit_tags=explicit)


def _resolve_new_thread_resume_label(stage: str, session_id: str) -> str | None:
    """Resolve resume_label for a new profile thread, logging when unresolved.

    A missing resume registry does not stop the profile graph — it just means
    the wiki write falls back to _registered_label's own default — but the
    tool logs the miss so it's visible in callback logs.
    """
    resume_label, label_error = _resolve_resume_label(session_id)
    if label_error is not None:
        _log(
            "INFO",
            {"tool": stage, "session_id": session_id, "event": "resume_label_unresolved"},
        )
    return resume_label


@trace_tool("compile_profile", graph_name="profile")
def _compile_profile_impl(
    session_id: str, host_tags: list[str], *, resumed: bool, explicit_tags: bool
) -> dict:
    graph, graph_error = _graph_or_err(get_profile_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_profile_config(session_id, tool_name="compile_profile")
    if resumed:
        update = {"host_tags": host_tags} if explicit_tags else None
        error = _resume_profile_thread(
            graph, config, session_id, "compile_profile", "compile_profile", update
        )
        if error:
            return error
        graph_input = None
    else:
        resume_label = _resolve_new_thread_resume_label("compile_profile", session_id)
        graph_input = ProfileState(
            session_id=session_id, resume_label=resume_label, host_tags=host_tags or None
        )
    snapshot, error = _run_profile_thread(graph, config, graph_input, session_id, "compile_profile")
    if error:
        return error
    assert snapshot is not None
    next_action, data = _profile_thread_data(snapshot)
    return _ok(session_id, next_action, data)


@mcp.tool()
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
    _log(
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
        return _err(
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
        return _err(
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
    graph, graph_error = _graph_or_err(get_profile_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_profile_config(session_id, tool_name="create_story")
    if resumed:
        error = _resume_profile_thread(
            graph, config, session_id, "create_story", "create_story", {"intake": intake}
        )
        if error:
            return error
        graph_input = None
    else:
        resume_label = _resolve_new_thread_resume_label("create_story", session_id)
        graph_input = ProfileState(session_id=session_id, resume_label=resume_label, intake=intake)
    snapshot, error = _run_profile_thread(graph, config, graph_input, session_id, "create_story")
    if error:
        return error
    assert snapshot is not None
    values = snapshot.values
    if not (values.get("intake") or {}).get("story_id"):
        _log(
            "ERROR",
            {"tool": "create_story", "session_id": session_id, "event": "story_not_saved"},
        )
        return _err(
            "create_story",
            "story_not_saved",
            "graph run completed without saving the story",
            session_id,
            retriable=False,
        )
    next_action, data = _profile_thread_data(snapshot)
    data = {
        "story_id": (values.get("intake") or {}).get("story_id"),
        "primary_skill": intake["primary_skill"],
        "needs_compile": False,
        **data,
    }
    return _ok(session_id, next_action, data)


@mcp.tool()
def set_search_preferences(preferences: dict) -> dict:
    """Persist the user's job-search preferences.

    This call fully replaces any stored preferences — omitted optional fields
    revert to their defaults.

    Args:
        preferences: SearchPreferences fields. home_location and work_types are
            required; updated_at is stamped server-side.

    Returns:
        Envelope dict (structured content) echoing the stored preferences under data.preferences.
    """
    session_id = str(uuid.uuid4())
    _log("INFO", {"tool": "set_search_preferences", "session_id": session_id})

    stamped = {**preferences, "updated_at": datetime.datetime.now(datetime.UTC).isoformat()}
    try:
        prefs = SearchPreferences.model_validate(stamped)
    except ValidationError as exc:
        return _err(
            stage="set_search_preferences",
            code="invalid_preferences",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )

    PreferencesStore().save(prefs)
    return _ok(session_id, None, {"preferences": prefs.model_dump()})


@mcp.tool()
def get_search_preferences() -> dict:
    """Return the user's job-search preferences (slim slice; no profile data).

    Returns:
        Envelope dict (structured content) with data.preferences, or
        next_action=set_search_preferences when none are stored.
    """
    session_id = str(uuid.uuid4())
    _log("INFO", {"tool": "get_search_preferences", "session_id": session_id})

    prefs = PreferencesStore().load()
    if prefs is None:
        return _ok(session_id, "set_search_preferences", None)
    return _ok(session_id, None, {"preferences": prefs.model_dump()})


@mcp.tool()
def get_wiki_pages(session_id: str, page_ids: list[str]) -> dict:
    """Batch-fetch wiki pages for a session's resume.

    This tool exists because the wiki lives on the server's local filesystem and
    the host LLM has no direct file access in an MCP context — it can only reach
    files through tools the server exposes. The host reads the index returned by
    submit_keywords, picks the relevant page paths, and fetches their content here.

    Args:
        session_id: Apply session ID (used to resolve the resume_label).
        page_ids: Page paths relative to wiki root (e.g., ['experience/acme.md']).

    Returns:
        Envelope dict (structured content) with pages dict {page_id: content}.
        Missing pages return empty string.
    """
    return _get_wiki_pages_impl(session_id, page_ids)


@trace_tool("get_wiki_pages", graph_name="apply")
def _get_wiki_pages_impl(session_id: str, page_ids: list[str]) -> dict:
    _log("INFO", {"tool": "get_wiki_pages", "session_id": session_id, "page_count": len(page_ids)})

    graph, graph_error = _graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
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

    try:
        pages = WikiStore().read_pages(resume_label, page_ids)
    except WikiPageIdError as exc:
        _log(
            "WARNING",
            {"tool": "get_wiki_pages", "session_id": session_id, "event": "invalid_page_id"},
        )
        return _err(
            stage="get_wiki_pages",
            code="invalid_page_id",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )
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
def check_update() -> dict:
    """Return current version, latest GitHub release tag, and update_available flag."""
    return _ok("", data=version_check.check_update())


# ============================================================================
# Ledger tools
# ============================================================================


def _today_iso() -> str:
    return datetime.date.today().isoformat()  # local date, like the skills' folders


def _is_iso_date(value: str) -> bool:
    """True only for a real YYYY-MM-DD; text comparison of dates breaks on other shapes."""
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _date_error(name: str, value: str | None) -> dict | None:
    if value is None or _is_iso_date(value):
        return None
    return _err("ledger", "invalid_date", f"{name} must be YYYY-MM-DD, got: {value!r}")


def _identity_error(url: str | None, company: str | None, title: str | None) -> dict | None:
    if (url or "").strip() or ((company or "").strip() and (title or "").strip()):
        return None
    return _err(
        "ledger", "missing_job_identity", "Give a URL, or a company and title.", retriable=False
    )


def _contact_note(url: str | None, note: str | None) -> str | None:
    """A non-URL `url` (e.g. a recruiter thread) is kept in the note as `Contact: <value>`."""
    contact = (url or "").strip()
    if not contact or ledger.url_or_none(contact):
        return note
    method, rest = _split_contact_method(note)
    return " | ".join(part for part in (method, f"Contact: {contact}", rest) if part)


def _split_contact_method(note: str | None) -> tuple[str | None, str | None]:
    """('Contact method: X', rest) when the note leads with it, so the EDD filter still sees it."""
    text = (note or "").strip()
    if not text.casefold().startswith("contact method:"):
        return None, note
    method, _, rest = text.partition(" | ")
    return method, rest or None


def _ledger_error(exc: Exception) -> dict:
    """Envelope for a ledger that cannot be opened, read, or written. Call from an except."""
    _log_exception({"tool": "ledger", "event": "ledger_error", "error": str(exc)})
    return _err(
        "ledger", "ledger_error", f"could not read or write the ledger: {exc}", retriable=True
    )


@mcp.tool()
def find_job(url: str | None = None, company: str | None = None, title: str | None = None) -> dict:
    """Check whether a job is already in callback's ledger (for dedupe before scoring or applying).

    Pass the posting URL, or company and title for a pasted job description with no URL. A
    url without http:// or https:// (e.g. a recruiter thread) is ignored for the lookup. A job
    seen under a different URL is still found when company and title match, but that is a
    weaker match (the same title can be two real postings): check matched_by ('key',
    'key_title_mismatch' when the URL matches but the stored title differs or is missing,
    'company_title', or
    null) and confirm anything but 'key' before skipping. Returns found, job_key, company,
    title, stored URL, latest status with its date, and ever_applied (whether any status proves
    submission). To record a status on the job found by company+title, pass its job_key to
    record_status. When not found or the match is weak,
    and a company is given, company_jobs lists that company's other jobs (up to 20, newest
    first; each with job_key, url, title, status, status_date, ever_applied) so you can spot a
    similar title or a requisition id in a job_key URL.
    Error codes: missing_job_identity, ledger_error.
    """
    url = ledger.url_or_none(url)
    if error := _identity_error(url, company, title):
        return error
    try:
        with closing(ledger.connect()) as conn:
            return _ok("", data=ledger.find_job(conn, url=url, company=company, title=title))
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return _ledger_error(exc)


def _record_status_error(
    status: str,
    url: str | None,
    company: str | None,
    title: str | None,
    date: str | None,
    job_key: str | None,
) -> dict | None:
    if not job_key and (error := _identity_error(url, company, title)):
        return error
    if not status.strip():
        return _err("ledger", "invalid_status", "status must not be empty.")
    return _date_error("date", date)


@mcp.tool()
def record_status(
    status: str,
    url: str | None = None,
    company: str | None = None,
    title: str | None = None,
    salary_range: str | None = None,
    note: str | None = None,
    date: str | None = None,
    job_key: str | None = None,
) -> dict:
    """Add a status event (e.g. 'Applied', 'Rejected', 'Skipped - not fit') to a job in the ledger.

    Give a URL, or a company and title. Creates the job if it is new. A url without http://
    or https:// (e.g. a recruiter thread) is not a URL: it goes into the note as
    'Contact: <value>' and the job is keyed by company and title (or job_key). To record on a
    job that find_job found by company+title, pass its job_key instead (URL, company, title
    are then not needed); an unknown job_key is an error. With job_key, salary_range only
    fills empty fields. History is never overwritten; only an exact repeat (same job, status,
    date, source, and note) is ignored (recorded: false). date is YYYY-MM-DD and defaults to
    today.
    Error codes: missing_job_identity, invalid_status, invalid_date, unknown_job, ledger_error.
    """
    web_url = ledger.url_or_none(url)
    if error := _record_status_error(status, web_url, company, title, date, job_key):
        return error
    update = ledger.StatusUpdate(
        status=status.strip(),
        recorded_at=date or _today_iso(),
        note=_contact_note(url, note),
        source="mcp",
        job_key=job_key,
        url=web_url,
        company=company,
        title=title,
        salary_range=salary_range,
    )
    try:
        with closing(ledger.connect()) as conn:
            if job_key and not ledger.job_exists(conn, job_key):
                return _err("ledger", "unknown_job", f"no job with job_key: {job_key!r}")
            added = ledger.record_status(conn, update)
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return _ledger_error(exc)
    return _ok("", data={"recorded": added})


_EXPORT_MODES = {
    "jobs": (ledger.export_rows, ledger.EXPORT_COLUMNS),
    "events": (ledger.export_events, ledger.EVENT_COLUMNS),
    "contacts": (ledger.export_contacts, ledger.EVENT_COLUMNS),
}


def _csv_text(rows: list[dict], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(ledger.spreadsheet_safe(row) for row in rows)
    return buffer.getvalue()


def _output_path_error(target: Path) -> dict | None:
    if "\0" in str(target):
        return _err("ledger", "invalid_output_path", "output_path must not contain a null byte")
    try:
        str(target).encode("utf-8")
    except UnicodeEncodeError:
        return _err("ledger", "invalid_output_path", "output_path must be valid UTF-8 text")
    if not target.is_absolute():
        return _err("ledger", "invalid_output_path", f"output_path must be absolute: {target}")
    if target.suffix.lower() != ".csv":
        return _err("ledger", "invalid_output_path", f"output_path must end in .csv: {target}")
    if target.exists() and not target.is_file():
        return _err("ledger", "invalid_output_path", f"output_path is not a regular file: {target}")
    return None


def _invalid_output_path_error(exc: OSError | RuntimeError) -> dict:
    """Log output-path handling failures and return the stable tool error."""
    _log("WARNING", {"event": "invalid_output_path", "error": str(exc)})
    return _err("ledger", "invalid_output_path", f"cannot use output_path: {exc}")


@mcp.tool()
def export_ledger(
    output_path: str, status: str | None = None, since: str | None = None, mode: str = "jobs"
) -> dict:
    """Write the ledger as CSV to output_path.

    mode "jobs" (default): one row per job with its latest status and latest scores; status
    and since keep jobs with ANY matching event. mode "events": one row per status event
    (Date, Company, Title, URL, Status, Notes, Source), newest first; status and since filter
    the event itself, so each application keeps its own date. mode "contacts": same columns,
    only EDD-reportable events: notes starting "Contact method:" and statuses starting
    "Applied" or "Already applied". Use "contacts" for an EDD work-search log.

    output_path must be absolute and end in .csv. status matches the start of the status
    text (empty means no filter); since is YYYY-MM-DD (on or after). Text that a spreadsheet
    would run as a formula is prefixed with '.
    Error codes: invalid_mode, invalid_output_path, invalid_date, ledger_error.
    """
    if mode not in _EXPORT_MODES:
        allowed = ", ".join(sorted(_EXPORT_MODES))
        return _err("ledger", "invalid_mode", f"mode must be one of {allowed}, got: {mode!r}")
    try:
        target = Path(output_path).expanduser()
        if error := _output_path_error(target):
            return error
    except (OSError, RuntimeError) as exc:
        return _invalid_output_path_error(exc)
    if error := _date_error("since", since):
        return error
    query, columns = _EXPORT_MODES[mode]
    try:
        with closing(ledger.connect()) as conn:
            rows = query(conn, status_prefix=status, since=since)
    except (sqlite3.Error, OSError, RuntimeError, UnicodeError) as exc:
        return _ledger_error(exc)
    try:
        paths.write_text_atomic(target, _csv_text(rows, columns))
    except OSError as exc:
        return _invalid_output_path_error(exc)
    return _ok("", data={"path": str(target), "rows": len(rows)})


def run() -> None:
    """Run the FastMCP stdio server."""
    if _LOG_PATH is None:
        configure_logging(os.environ.get("CALLBACK_LOG_PATH") or paths.log_path())
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
