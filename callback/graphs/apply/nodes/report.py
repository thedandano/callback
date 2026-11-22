"""Apply node: build the before/after score report."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState
from callback.services.scorer import normalize_for_match

logger = logging.getLogger("callback.apply_nodes")


_SCORE_DIMS = (
    "total",
    "keyword_match",
    "required_coverage",
    "preferred_coverage",
    "experience_fit",
    "impact_evidence",
    "ats_format",
    "readability",
)


def _compute_tailor_diagnostics(
    applied_skill_values: list[str] | None, parsed_final: str | None
) -> list[dict]:
    if not applied_skill_values:
        return []
    rendered = parsed_final or ""
    rendered_lower = rendered.lower()
    result = []
    for value in applied_skill_values:
        present = value.lower() in rendered_lower
        result.append(
            {
                "value": value,
                "applied_to_map": True,
                "present_in_rendered_text": present,
                "suggested_alternatives": [] if present else [normalize_for_match(value)],
            }
        )
    return result


def _dim_delta(si: dict, sf: dict, dim: str) -> float | None:
    before, after = si.get(dim), sf.get(dim)
    if before is None or after is None:
        return None
    return round(after - before, 2)


def _build_score_notes(si: dict, sf: dict, render_warnings: list[dict] | None) -> list[str]:
    """Advisory notes about score reliability and unfixable ATS gaps."""
    notes: list[str] = []
    si_version, sf_version = si.get("scoring_engine_version"), sf.get("scoring_engine_version")
    if si_version != sf_version:
        notes.append(
            f"Scoring engine version changed mid-session ({si_version} -> {sf_version}); "
            "delta may be unreliable."
        )
    if sf.get("experience_evaluated") is False:
        notes.append(
            "Experience fit not evaluated (JD states no years requirement or resume "
            "dates are unavailable); total is renormalized over the remaining dimensions."
        )
    for d in sf.get("ats_diagnostics") or []:
        if not d.get("matched") and d.get("closeable_by") != "tailor":
            notes.append(
                f"ATS format: '{d['expected']}' header not found in rendered PDF "
                f"(closeable_by={d['closeable_by']}). Tailoring cannot fix this."
            )
    for warning in render_warnings or []:
        if message := warning.get("message"):
            notes.append(str(message))
    return notes


def _build_knockout_warnings(keywords: dict | None, candidate_years: float | None) -> list[str]:
    """Years-shortfall knockout warnings, modeling binary ATS screener questions."""
    required_years = float((keywords or {}).get("required_years") or 0.0)
    if required_years <= 0 or candidate_years is None or candidate_years >= required_years:
        return []
    strong = required_years >= 2 * candidate_years
    label = "STRONG KNOCKOUT RISK" if strong else "LIKELY KNOCKOUT"
    message = (
        f"{label}: JD requires {required_years:g}+ years; resume shows "
        f"{candidate_years:g}. Years screener questions are typically binary pass/fail."
    )
    if strong:
        message += " Consider whether to apply."
    return [message]


@trace_node("apply", "report")
def report(state: ApplyState) -> dict:
    """Compute per-dimension score delta and format gap between initial and final pass.

    When no_coverage=True, use score_initial as both si and sf so delta is all-zero.
    """
    log_enter(logger, "report", state)
    si = state.score_initial or {}
    sf = si if state.no_coverage else (state.score_final or {})
    return {
        "report": {
            "before": {dim: si.get(dim) for dim in _SCORE_DIMS},
            "after": {dim: sf.get(dim) for dim in _SCORE_DIMS},
            "delta": {dim: _dim_delta(si, sf, dim) for dim in _SCORE_DIMS},
            "format_gap_chars": len(state.parsed_final or "") - len(state.parsed_initial or ""),
            "no_coverage": bool(state.no_coverage),
            "uncovered_skills": state.uncovered_skills or [],
            "experience_evaluated": sf.get("experience_evaluated"),
            "notes": _build_score_notes(si, sf, state.render_warnings),
            "warnings": _build_knockout_warnings(state.keywords, state.candidate_years),
        },
        "tailor_diagnostics": _compute_tailor_diagnostics(
            state.applied_skill_values, state.parsed_final
        ),
    }
