"""E1 deterministic checks: host-extracted JDData against the expected JDData.

Recall and precision are computed over the union of every term the JDData
carries: required, preferred, and every member of required_any and
preferred_any. Bucket placement only changes scoring weight in the real
scorer; a term the host drops or invents is the same extraction loss no
matter which bucket it lives in, so one pair of checks covers all of them.
Recall counts only expected terms that are still present in the JD text, so a
posting that was reworded after the expected data was written (content drift)
does not read as extraction loss. When too few expected terms survived the
drift to judge extraction quality at all, the term checks are skipped (pass
with a note) rather than trusted.

OR-groups are checked for coverage, not set equality: every expected group
with at least one member still present in the JD text must be matched by some
host group that shares a normalized member with it. A host group with no
expected counterpart is allowed and only surfaces as a note in the check
detail - unless it collapses two or more terms the expected data lists as
separate required/preferred requirements into a single "any one will do"
group, which fails: that is score inflation the required_coverage/
preferred_coverage math can't see (one OR-group is one denominator entry no
matter how many members it has).
"""

from __future__ import annotations

from dataclasses import dataclass

from callback.jd_data import JDDataError, parse_jd_json
from callback.scorer import normalize_for_match
from evals.checks import Check
from evals.recall import all_terms, term_present

RECALL_MIN = 0.6
PRECISION_MIN = 0.6
MIN_LIVE_RATIO = 0.6


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


def _dedupe_by_norm(terms: list[str]) -> list[str]:
    """First occurrence wins for each normalized form, so an expected list with both
    "Python" and "python" doesn't double-count a single real term and drive recall
    negative."""
    seen: set[str] = set()
    deduped = []
    for term in terms:
        norm = _norm(term)
        if norm not in seen:
            seen.add(norm)
            deduped.append(term)
    return deduped


def precision_recall(
    host_terms: list[str], expected_terms_list: list[str], jd_text: str
) -> PrecisionRecall:
    haystack = jd_text.lower()
    present = [t for t in expected_terms_list if term_present(t.lower(), haystack)]
    expected_in_jd = _dedupe_by_norm(present)
    expected_norm = {_norm(t) for t in expected_in_jd}
    host_norm = {_norm(t) for t in host_terms}
    missing = [t for t in expected_in_jd if _norm(t) not in host_norm]
    extra = [t for t in host_terms if _norm(t) not in expected_norm]
    recall = _ratio(len(expected_norm) - len(missing), len(expected_norm))
    precision = _ratio(len(host_terms) - len(extra), len(host_terms))
    return PrecisionRecall(precision=precision, recall=recall, missing=missing, extra=extra)


def _group_set(groups: list[list[str]]) -> set[tuple[str, ...]]:
    return {tuple(sorted(_norm(t) for t in group)) for group in groups}


def _group_matched(group: tuple[str, ...], others: set[tuple[str, ...]]) -> bool:
    return any(set(group) & set(other) for other in others)


def _present_expected_groups(
    expected_groups_raw: list[list[str]], jd_text: str
) -> set[tuple[str, ...]]:
    """Presence is tested on the raw, un-normalized members: a normalized member like
    "arm cortex m" (dash flattened to a space) would never match the JD's literal
    "ARM Cortex-M" and would wrongly read as content drift."""
    haystack = jd_text.lower()
    present = set()
    for group in expected_groups_raw:
        if any(term_present(m.lower(), haystack) for m in group):
            present.add(tuple(sorted(_norm(t) for t in group)))
    return present


def _flat_expected_terms_norm(expected: dict) -> set[str]:
    return {_norm(t) for t in expected.get("required", []) + expected.get("preferred", [])}


def _is_overgrouped(host_group: tuple[str, ...], flat_expected_norm: set[str]) -> bool:
    """True when the host folded 2+ terms the expected data lists as independent
    required/preferred requirements into one OR-group - claiming only one is needed
    when the posting actually asked for both."""
    return sum(1 for member in host_group if member in flat_expected_norm) >= 2


def _groups_check(host: dict, expected: dict, jd_text: str) -> Check:
    host_groups = _group_set(host.get("required_any", [])) | _group_set(
        host.get("preferred_any", [])
    )
    expected_groups_raw = expected.get("required_any", []) + expected.get("preferred_any", [])
    present_expected = _present_expected_groups(expected_groups_raw, jd_text)
    missing = sorted(list(g) for g in present_expected if not _group_matched(g, host_groups))
    if missing:
        return Check("groups_match", False, f"unmatched expected groups: {missing}")

    flat_expected_norm = _flat_expected_terms_norm(expected)
    extras = [hg for hg in host_groups if not _group_matched(hg, present_expected)]
    overgrouped = sorted(list(hg) for hg in extras if _is_overgrouped(hg, flat_expected_norm))
    if overgrouped:
        return Check(
            "groups_match",
            False,
            f"host collapsed independent required/preferred terms into an OR-group: {overgrouped}",
        )
    unknown = sorted(list(hg) for hg in extras if not _is_overgrouped(hg, flat_expected_norm))
    return Check("groups_match", True, f"extra host groups: {unknown}" if unknown else "")


def _substring_check(host: dict, jd_text: str) -> Check:
    haystack = jd_text.lower()
    absent = [t for t in all_terms(host) if not term_present(t.lower(), haystack)]
    return Check(
        "terms_are_jd_substrings",
        not absent,
        "" if not absent else f"not in JD: {absent}",
    )


def _live_expected_terms(expected_list: list[str], jd_text: str) -> tuple[int, int]:
    """(live, total): how many expected terms are still present in the JD text."""
    haystack = jd_text.lower()
    total = len(expected_list)
    live = sum(1 for t in expected_list if term_present(t.lower(), haystack))
    return live, total


def _term_checks(host: dict, expected: dict, jd_text: str) -> list[Check]:
    expected_list = all_terms(expected)
    live, total = _live_expected_terms(expected_list, jd_text)
    if total == 0 or (live / total) < MIN_LIVE_RATIO:
        detail = (
            f"not evaluated: only {live} of {total} expected terms are still in the JD "
            "(content drift)"
        )
        return [
            Check("term_recall", True, detail, skipped=True),
            Check("term_precision", True, detail, skipped=True),
        ]
    pr = precision_recall(all_terms(host), expected_list, jd_text)
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


def _scalar_checks(host: dict, expected: dict) -> list[Check]:
    host_years = float(host.get("required_years", 0.0))
    expected_years = float(expected.get("required_years", 0.0))
    host_title = (host.get("title") or "").strip()
    expected_title = (expected.get("title") or "").strip()
    years_ok = host_years == expected_years
    title_ok = host_title == expected_title
    return [
        Check(
            "required_years_exact",
            years_ok,
            "" if years_ok else f"host {host_years} != expected {expected_years}",
        ),
        Check(
            "title_exact",
            title_ok,
            "" if title_ok else f"host {host_title!r} != expected {expected_title!r}",
        ),
    ]


def run_checks(host_json: str, expected: dict, jd_text: str) -> list[Check]:
    """Every E1 check in table order. An unparseable host output yields one failed check."""
    try:
        host = parse_jd_json(host_json)
    except JDDataError as exc:
        return [Check("valid_jd_data", False, str(exc))]
    return [
        Check("valid_jd_data", True),
        *_term_checks(host, expected, jd_text),
        _groups_check(host, expected, jd_text),
        _substring_check(host, jd_text),
        *_scalar_checks(host, expected),
    ]
