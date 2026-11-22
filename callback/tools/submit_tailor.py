"""MCP tool `submit_tailor`."""

from pathlib import Path

from callback.config import paths
from callback.config.logging import log
from callback.config.observability import (
    invoke_graph_without_native_tracing,
    record_decision,
    trace_tool,
)
from callback.graphs.apply.graph import (
    FINALIZE_NODE,
    PARSE_FINAL_NODE,
    RENDER_NODE,
    REPORT_NODE,
    SCORE_FINAL_NODE,
    SCORE_INITIAL_NODE,
    TAILOR_NODE,
    get_apply_graph,
)
from callback.graphs.apply.graph import (
    make_config as make_apply_config,
)
from callback.models.envelope import err, ok
from callback.models.section_map import SectionMap
from callback.services.section_edits import apply_edits, detect_uncovered_skills
from callback.tools.errors import graph_or_err, unexpected_error
from callback.tools.workflow import complete_workflow


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
        return None, err(
            "submit_tailor",
            "invalid_output_dir",
            f"output_dir must be an absolute path: {output_dir}",
            session_id,
            retriable=True,
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log(
            "ERROR",
            {
                "tool": "submit_tailor",
                "session_id": session_id,
                "invalid_output_dir": output_dir,
                "error": str(exc),
            },
        )
        return None, err(
            "submit_tailor",
            "invalid_output_dir",
            f"cannot write to output_dir: {exc}",
            session_id,
            retriable=True,
        )
    return str(resolved), None


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
        log(
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
        return unexpected_error("submit_tailor", session_id)
    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return err(
            "submit_tailor",
            "pipeline_error",
            final["error"],
            session_id,
            retriable=True,
            data={"score_final": None, "pdf_path": None, "ledger_path": None},
            host_action="report_and_wait",
        )
    artifacts = _submit_tailor_artifacts(final)
    return ok(
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
        workflow=complete_workflow(),
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
    log("INFO", {"tool": "submit_tailor", "session_id": session_id, "edit_count": len(edits)})

    graph, graph_error = graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_apply_config(session_id, tool_name="submit_tailor")
    snapshot = graph.get_state(config)

    if not snapshot.values:
        return err("submit_tailor", "session_not_found", "session_id not found", session_id)

    if snapshot.next != (TAILOR_NODE,):
        return err(
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
        return err(
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
    edits_applied, edits_rejected, applied_skill_values = apply_edits(section_map, edits)

    uncovered_skills = detect_uncovered_skills(section_map)

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
        return unexpected_error("submit_tailor", session_id)

    final_snapshot = graph.get_state(config)
    final = final_snapshot.values
    if final.get("error"):
        return err(
            "submit_tailor",
            "pipeline_error",
            final["error"],
            session_id,
            retriable=True,
            data={"score_final": None, "pdf_path": None, "ledger_path": None},
            host_action="report_and_wait",
        )
    artifacts = _submit_tailor_artifacts(final)
    return ok(
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
        workflow=complete_workflow(),
    )
