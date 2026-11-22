"""MCP tool `submit_keywords`."""

from callback.config.logging import log
from callback.config.observability import (
    trace_tool,
)
from callback.graphs.apply import api as apply_api
from callback.models.envelope import err, ok
from callback.models.jd_data import JDDataError
from callback.services.host_protocols import (
    RESPONSIBILITIES_PROTOCOL,
    TAILOR_INSTRUCTIONS,
)
from callback.services.jd_parsing import (
    parse_jd_json,
)
from callback.services.keyword_coverage import detect_orphaned_required
from callback.services.project_ranking import (
    project_layout_recommendation,
    project_swap_recommendation,
    rank_project_candidates,
    trim_candidates,
)
from callback.tools.errors import graph_or_err, unexpected_error
from callback.tools.workflow import (
    NEXT_ADD_STORY_FIRST,
    NEXT_FETCH_WIKI_THEN_TAILOR,
    NEXT_ONBOARD_RESUME_FIRST,
    submit_keywords_workflow,
)


def _submit_keywords_state_error(session_id: str) -> dict | None:
    """Return an error envelope if submit_keywords cannot resume safely."""
    session = apply_api.read(session_id, tool_name="submit_keywords")
    if not session.values:
        return err(
            stage="submit_keywords",
            code="invalid_session",
            message="session_id was not found; call load_jd before submit_keywords",
            session_id=session_id,
            retriable=False,
        )

    if session.waiting_for != "keywords":
        return err(
            stage="submit_keywords",
            code="invalid_state",
            message="session is not waiting for keyword submission",
            session_id=session_id,
            retriable=False,
        )

    return None


def _submit_keywords_next_action(wiki_index: str | None, orphaned_required: list[str]) -> str:
    if not wiki_index:
        return NEXT_ONBOARD_RESUME_FIRST
    return NEXT_ADD_STORY_FIRST if orphaned_required else NEXT_FETCH_WIKI_THEN_TAILOR


def submit_keywords(session_id: str, jd_json: str) -> dict:
    """Accept host-extracted JDData and return score gaps plus tailor handoff guidance.

    When profile wiki project stories exist, the response also includes ranked
    project_candidates and an optional project_swap_recommendation for the host
    to consider during tailoring.
    """
    return _submit_keywords_impl(session_id, jd_json)


def _submit_keywords_invoke(
    keywords: dict, session_id: str
) -> tuple[dict, None] | tuple[None, dict]:
    """Store keywords and resume the graph, mapping raised errors to envelopes."""
    try:
        apply_api.accept_keywords(session_id, keywords)
    except ValueError as exc:
        return None, err(
            stage="submit_keywords",
            code="invalid_session",
            message=str(exc),
            session_id=session_id,
            retriable=False,
        )
    try:
        return apply_api.resume(session_id, tool_name="submit_keywords"), None
    except Exception:
        return None, unexpected_error("submit_keywords", session_id)


def _submit_keywords_session_error(session_id: str) -> dict | None:
    """Open the apply graph and check the session can take keywords; else return the error."""
    _, graph_error = graph_or_err(apply_api.ensure_ready, session_id)
    if graph_error is not None:
        return graph_error
    return _submit_keywords_state_error(session_id)


@trace_tool("submit_keywords", graph_name="apply")
def _submit_keywords_impl(session_id: str, jd_json: str) -> dict:
    log("INFO", {"tool": "submit_keywords", "session_id": session_id})

    try:
        keywords = parse_jd_json(jd_json)
    except JDDataError as exc:
        return err(
            stage="submit_keywords",
            code=exc.code,
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )

    session_error = _submit_keywords_session_error(session_id)
    if session_error is not None:
        return session_error

    state, invoke_error = _submit_keywords_invoke(keywords, session_id)
    if invoke_error is not None:
        return invoke_error
    assert state is not None

    data: dict = {"keywords": state.get("keywords")}

    if state.get("sections"):
        data["sections"] = state.get("sections")
        data["trim_candidates"] = trim_candidates(
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
        orphaned_required = detect_orphaned_required(
            score.get("req_unmatched", []),
            state.get("sections") or {},
            state.get("wiki_index") or "",
        )
        data["orphaned_required"] = orphaned_required

    if state.get("wiki_index"):
        data["wiki_index"] = state.get("wiki_index")
        data["tailor_instructions"] = TAILOR_INSTRUCTIONS
        candidates = rank_project_candidates(
            state.get("resume_label") or "",
            state.get("keywords") or {},
            state.get("wiki_index") or "",
        )
        data["project_candidates"] = candidates
        data["project_swap_recommendation"] = project_swap_recommendation(
            candidates,
            state.get("keywords") or {},
            state.get("sections") or {},
        )
        data["project_layout_recommendation"] = project_layout_recommendation(
            candidates,
            state.get("keywords") or {},
            state.get("sections") or {},
        )
    return _submit_keywords_reply(session_id, data, state.get("wiki_index"), orphaned_required)


def _submit_keywords_reply(
    session_id: str, data: dict, wiki_index: str | None, orphaned_required: list[str]
) -> dict:
    """Pick the next step; only the tailor route asks for pass 2 (the others restart)."""
    next_action = _submit_keywords_next_action(wiki_index, orphaned_required)
    if next_action == NEXT_FETCH_WIKI_THEN_TAILOR:
        data["responsibilities_protocol"] = RESPONSIBILITIES_PROTOCOL
    return ok(
        session_id,
        next_action,
        data,
        submit_keywords_workflow(session_id, next_action, orphaned_required),
    )
