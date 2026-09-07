"""E1 deterministic checks: host-extracted JDData against the golden JDData.

Recall and precision are computed over the union of every term the JDData
carries: required, preferred, and every member of required_any and
preferred_any. Bucket placement only changes scoring weight in the real
scorer; a term the host drops or invents is the same extraction loss no
matter which bucket it lives in, so one pair of checks covers all of them.
Recall counts only golden terms that are still present in the JD text, so a
posting that was reworded after the golden was written (content drift) does
not read as extraction loss. When too few golden terms survived the drift to
judge extraction quality at all, the term checks are skipped (pass with a
note) rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass

from callback.jd_data import JDDataError, parse_jd_json
from callback.scorer import normalize_for_match
from evals.checks import Check
from evals.recall import term_present

RECALL_MIN = 0.6
PRECISION_MIN = 0.6
MIN_GOLDEN_TERMS = 5


@dataclass(frozen=True)
class PrecisionRecall:
    precision: float
    recall: float
    missing: list[str]
    extra: list[str]


def _norm(term: str) -> str:
    return normalize_for_match(term).lower()


def _ratio(hits: int, total: int) -> float:
    return 1.0 if total == 0 else round(hits / total, 2)


def precision_recall(
    host_terms: list[str], golden_terms: list[str], jd_text: str
) -> PrecisionRecall:
    haystack = jd_text.lower()
    golden_in_jd = [t for t in golden_terms if term_present(t.lower(), haystack)]
    golden_norm = {_norm(t) for t in golden_in_jd}
    host_norm = {_norm(t) for t in host_terms}
    missing = [t for t in golden_in_jd if _norm(t) not in host_norm]
    extra = [t for t in host_terms if _norm(t) not in golden_norm]
    recall = _ratio(len(golden_norm) - len(missing), len(golden_norm))
    precision = _ratio(len(host_terms) - len(extra), len(host_terms))
    return PrecisionRecall(precision=precision, recall=recall, missing=missing, extra=extra)


def _group_set(groups: list[list[str]]) -> set[tuple[str, ...]]:
    return {tuple(sorted(_norm(t) for t in group)) for group in groups}


def _groups_check(host: dict, golden: dict) -> Check:
    host_groups = _group_set(host.get("required_any", [])) | _group_set(
        host.get("preferred_any", [])
    )
    golden_groups = _group_set(golden.get("required_any", [])) | _group_set(
        golden.get("preferred_any", [])
    )
    missing = sorted(list(g) for g in golden_groups - host_groups)
    extra = sorted(list(g) for g in host_groups - golden_groups)
    ok = not missing and not extra
    return Check("groups_match", ok, "" if ok else f"missing {missing}; extra {extra}")


def _all_terms(data: dict) -> list[str]:
    terms = list(data.get("required", [])) + list(data.get("preferred", []))
    for group in data.get("required_any", []) + data.get("preferred_any", []):
        terms.extend(group)
    return terms


def _substring_check(host: dict, jd_text: str) -> Check:
    haystack = jd_text.lower()
    absent = [t for t in _all_terms(host) if not term_present(t.lower(), haystack)]
    return Check(
        "terms_are_jd_substrings",
        not absent,
        "" if not absent else f"not in JD: {absent}",
    )


def _golden_terms_present(golden: dict, jd_text: str) -> int:
    haystack = jd_text.lower()
    return sum(1 for t in _all_terms(golden) if term_present(t.lower(), haystack))


def _term_checks(host: dict, golden: dict, jd_text: str) -> list[Check]:
    present = _golden_terms_present(golden, jd_text)
    if present < MIN_GOLDEN_TERMS:
        detail = f"not evaluated: only {present} golden terms are still in the JD (content drift)"
        return [Check("term_recall", True, detail), Check("term_precision", True, detail)]
    pr = precision_recall(_all_terms(host), _all_terms(golden), jd_text)
    recall_ok = pr.recall >= RECALL_MIN
    precision_ok = pr.precision >= PRECISION_MIN
    return [
        Check("term_recall", recall_ok, "" if recall_ok else f"missing {pr.missing}"),
        Check(
            "term_precision",
            precision_ok,
            "" if precision_ok else f"{pr.precision} < {PRECISION_MIN}; extra {pr.extra}",
        ),
    ]


def _scalar_checks(host: dict, golden: dict) -> list[Check]:
    host_years = float(host.get("required_years", 0.0))
    golden_years = float(golden.get("required_years", 0.0))
    host_title = (host.get("title") or "").strip()
    golden_title = (golden.get("title") or "").strip()
    years_ok = host_years == golden_years
    title_ok = host_title == golden_title
    return [
        Check(
            "required_years_exact",
            years_ok,
            "" if years_ok else f"host {host_years} != golden {golden_years}",
        ),
        Check(
            "title_exact",
            title_ok,
            "" if title_ok else f"host {host_title!r} != golden {golden_title!r}",
        ),
    ]


def run_checks(host_json: str, golden: dict, jd_text: str) -> list[Check]:
    """Every E1 check in table order. An unparseable host output yields one failed check."""
    try:
        host = parse_jd_json(host_json)
    except JDDataError as exc:
        return [Check("valid_jd_data", False, str(exc))]
    return [
        Check("valid_jd_data", True),
        *_term_checks(host, golden, jd_text),
        _groups_check(host, golden),
        _substring_check(host, jd_text),
        *_scalar_checks(host, golden),
    ]
