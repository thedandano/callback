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
host group that shares a normalized member with it. The grouping guard treats
each flat expected term and each expected OR-group as an obligation. A host
group with multiple mapped members is valid only when those members share one
expected OR-group obligation; slash-parts of one flat compound are still
invalid when offered as an OR-group.

Separately, every host group - not only ones with no expected counterpart -
is checked for collapsing two or more terms the expected data lists as
independent required/preferred requirements into a single "any one will do"
group; this fails even when the same group also shares a member with a real
expected group, since that overlap doesn't excuse folding in unrelated
independent terms. That is score inflation the required_coverage/
preferred_coverage math can't see (one OR-group is one denominator entry no
matter how many members it has). A host group that avoids both problems is
allowed and only surfaces as a note in the check detail.

Responsibilities are graded separately from scored terms. A responsibility
may be satisfied by an exact gold term or alias in the pass-2 output, or by a
scored term because the merge step removes pass-2 responsibilities that were
already scored in pass 1.
"""

from __future__ import annotations

from dataclasses import dataclass

from callback.jd_data import JDDataError, parse_jd_json
from callback.scorer import normalize_for_match
from evals.checks import Check
from evals.recall import all_terms, term_present

RECALL_MIN = 0.6
RESPONSIBILITIES_RECALL_MIN = 0.7
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


def _flat_obligation_terms(term: str) -> set[str]:
    terms = {_norm(term)}
    if "/" in term:
        terms.update(_norm(part.strip()) for part in term.split("/"))
    return terms


def _expected_obligations(expected: dict) -> dict[str, set[tuple[str, int]]]:
    obligations: dict[str, set[tuple[str, int]]] = {}
    flat_terms = expected.get("required", []) + expected.get("preferred", [])
    for index, term in enumerate(flat_terms):
        for normalized in _flat_obligation_terms(term):
            obligations.setdefault(normalized, set()).add(("flat", index))
    groups = expected.get("required_any", []) + expected.get("preferred_any", [])
    for index, group in enumerate(groups):
        for member in group:
            obligations.setdefault(_norm(member), set()).add(("group", index))
    return obligations


def _is_overgrouped(
    host_group: tuple[str, ...], expected_obligations: dict[str, set[tuple[str, int]]]
) -> bool:
    """Whether distinct mapped host members lack one shared expected OR-group obligation."""
    mapped = [
        expected_obligations[member] for member in set(host_group) if member in expected_obligations
    ]
    if len(mapped) < 2:
        return False
    common = set.intersection(*mapped)
    return not any(kind == "group" for kind, _ in common)


def _groups_check(host: dict, expected: dict, jd_text: str) -> Check:
    host_groups = _group_set(host.get("required_any", [])) | _group_set(
        host.get("preferred_any", [])
    )
    expected_groups_raw = expected.get("required_any", []) + expected.get("preferred_any", [])
    present_expected = _present_expected_groups(expected_groups_raw, jd_text)
    missing = sorted(list(g) for g in present_expected if not _group_matched(g, host_groups))
    if missing:
        return Check("groups_match", False, f"unmatched expected groups: {missing}")

    # Checked against every host group, not just ones with no expected counterpart: a group
    # that shares one member with a real expected group ("AWS" from AWS/GCP) can still smuggle
    # in two unrelated independent terms ("Redis", "Terraform") alongside it.
    expected_obligations = _expected_obligations(expected)
    overgrouped = sorted(
        list(host_group)
        for host_group in host_groups
        if _is_overgrouped(host_group, expected_obligations)
    )
    if overgrouped:
        return Check(
            "groups_match",
            False,
            f"host collapsed independent required/preferred terms into an OR-group: {overgrouped}",
        )
    extras = sorted(list(hg) for hg in host_groups if not _group_matched(hg, present_expected))
    return Check("groups_match", True, f"extra host groups: {extras}" if extras else "")


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


def _responsibility_coverage(
    host: dict, gold_terms: list[str], aliases: dict[str, list[str]]
) -> tuple[list[str], list[str]]:
    host_responsibilities = {_norm(term) for term in host.get("key_responsibilities", [])}
    scored_terms = {_norm(term) for term in all_terms(host)}
    missing = []
    via_scored_terms_only = []
    for gold_term in gold_terms:
        credited_terms = {_norm(gold_term), *(_norm(alias) for alias in aliases.get(gold_term, []))}
        found_in_responsibilities = bool(credited_terms & host_responsibilities)
        found_in_scored_terms = bool(credited_terms & scored_terms)
        if not found_in_responsibilities and not found_in_scored_terms:
            missing.append(gold_term)
        elif not found_in_responsibilities:
            via_scored_terms_only.append(gold_term)
    return missing, via_scored_terms_only


def _responsibilities_check(host: dict, expected: dict, grade_responsibilities: bool) -> Check:
    if not grade_responsibilities:
        return Check("responsibilities_recall", True, "no pass 2 output", skipped=True)
    gold_terms = expected.get("key_responsibilities", [])
    if not gold_terms:
        return Check(
            "responsibilities_recall", True, "no expected key_responsibilities", skipped=True
        )

    missing, via_scored_terms_only = _responsibility_coverage(
        host, gold_terms, expected.get("key_responsibilities_aliases", {})
    )
    recall = _ratio(len(gold_terms) - len(missing), len(gold_terms))
    details = []
    if missing:
        details.append(f"missing {missing}")
    if via_scored_terms_only:
        details.append(f"via scored terms only: {via_scored_terms_only}")
    return Check(
        "responsibilities_recall",
        recall >= RESPONSIBILITIES_RECALL_MIN,
        "; ".join(details),
    )


def run_checks(
    host_json: str, expected: dict, jd_text: str, *, grade_responsibilities: bool = True
) -> list[Check]:
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
        _responsibilities_check(host, expected, grade_responsibilities),
    ]
