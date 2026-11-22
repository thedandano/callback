"""Scoring helper shared by the score_initial and score_final nodes."""

from callback.services import scorer


def run_score(
    text: str | None,
    keywords: dict | None,
    closeable_by: str = "source_pdf",
    candidate_years: float | None = None,
) -> dict:
    if not text or not text.strip():
        raise ValueError("_run_score: text must not be empty")
    if not keywords or not any(
        keywords.get(field) for field in ("required", "required_any", "preferred", "preferred_any")
    ):
        raise ValueError("_run_score: keywords must have at least one non-empty bucket")
    r = scorer.score(
        text,
        keywords.get("required", []),
        keywords["preferred"],
        required_any=keywords.get("required_any", []),
        preferred_any=keywords.get("preferred_any", []),
        candidate_years=candidate_years,
        required_years=keywords["required_years"],
        cfg=scorer.DEFAULT_SCORING_CONFIG,
        closeable_by=closeable_by,  # type: ignore[arg-type]
    )
    required_present = bool(keywords.get("required") or keywords.get("required_any"))
    preferred_present = bool(keywords.get("preferred") or keywords.get("preferred_any"))
    return {
        "total": r.breakdown.total(),
        "keyword_match": r.breakdown.keyword_match,
        "required_coverage": round(r.keywords.req_pct * 100, 1) if required_present else None,
        "preferred_coverage": round(r.keywords.pref_pct * 100, 1) if preferred_present else None,
        "experience_fit": r.breakdown.experience_fit,
        "experience_evaluated": r.breakdown.experience_fit is not None,
        "impact_evidence": r.breakdown.impact_evidence,
        "ats_format": r.breakdown.ats_format,
        "readability": r.breakdown.readability,
        "req_matched": r.keywords.req_matched,
        "req_unmatched": r.keywords.req_unmatched,
        "req_group_unmatched": r.keywords.req_group_unmatched,
        "pref_matched": r.keywords.pref_matched,
        "pref_unmatched": r.keywords.pref_unmatched,
        "pref_group_unmatched": r.keywords.pref_group_unmatched,
        "ats_diagnostics": [
            {
                "expected": d.expected,
                "observed": d.observed,
                "matched": d.matched,
                "closeable_by": d.closeable_by,
            }
            for d in r.breakdown.ats_diagnostics
        ],
        "ats_input_suspect": r.breakdown.ats_input_suspect,
        "scoring_engine_version": scorer.SCORING_ENGINE_VERSION,
    }
