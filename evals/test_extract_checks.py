"""E1 checks: precision/recall against the expected, substring discipline, exact scalars."""

from __future__ import annotations

import json

from evals.checks import Check
from evals.extract_checks import PrecisionRecall, precision_recall, run_checks

JD = (
    "Senior Backend Engineer at Northwind. Requirements: Python, FastAPI, PostgreSQL, "
    "and 4+ years building services on AWS or GCP. Nice to have: Redis, Terraform."
)
EXPECTED = {
    "title": "Senior Backend Engineer",
    "company": "Northwind",
    "required": ["Python", "FastAPI", "PostgreSQL"],
    "preferred": ["Redis", "Terraform"],
    "required_any": [["AWS", "GCP"]],
    "preferred_any": [],
    "required_years": 4.0,
}


def _host(**overrides) -> str:
    return json.dumps({**EXPECTED, **overrides})


def _names(checks: list[Check]) -> dict[str, bool]:
    return {c.name: c.passed for c in checks}


def test_expected_as_host_output_passes_every_check():
    actual = _names(run_checks(_host(), EXPECTED, JD))

    expected = {
        "valid_jd_data": True,
        "term_recall": True,
        "term_precision": True,
        "groups_match": True,
        "terms_are_jd_substrings": True,
        "required_years_exact": True,
        "title_exact": True,
    }
    assert actual == expected


def test_invalid_json_is_the_only_check():
    checks = run_checks("not json", EXPECTED, JD)

    actual = [(c.name, c.passed) for c in checks]

    expected = [("valid_jd_data", False)]
    assert actual == expected


def test_precision_recall_ignores_expected_terms_absent_from_jd():
    expected_terms = ["Python", "Kubernetes"]  # Kubernetes drifted off the page

    actual = precision_recall(["Python"], expected_terms, JD)

    expected = PrecisionRecall(precision=1.0, recall=1.0, missing=[], extra=[])
    assert actual == expected


def test_precision_recall_reports_missing_and_extra():
    actual = precision_recall(["python", "Docker"], ["Python", "FastAPI"], JD)

    expected = PrecisionRecall(precision=0.5, recall=0.5, missing=["FastAPI"], extra=["Docker"])
    assert actual == expected


def test_duplicate_expected_terms_do_not_break_recall():
    actual = precision_recall([], ["Python", "python"], "we use python")

    expected = PrecisionRecall(precision=1.0, recall=0.0, missing=["Python"], extra=[])
    assert actual == expected


def test_paraphrase_alone_is_caught_by_substring_check():
    """A rewritten term ("Postgres" for "PostgreSQL") no longer sinks recall/precision on its
    own (EXPECTED has 7 terms present, well past the thin-expected guard) - only the substring
    check, which demands the host's own term literally be in the JD, catches it."""
    checks = run_checks(_host(required=["Python", "FastAPI", "Postgres"]), EXPECTED, JD)

    actual = [c for c in checks if not c.passed]

    expected = [Check("terms_are_jd_substrings", False, "not in JD: ['Postgres']")]
    assert actual == expected


def test_groups_compare_as_sets_regardless_of_order():
    checks = run_checks(_host(required_any=[["GCP", "AWS"]]), EXPECTED, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "")]
    assert actual == expected


def test_unmatched_expected_group_fails_groups_match():
    checks = run_checks(_host(required_any=[]), EXPECTED, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", False, "unmatched expected groups: [['aws', 'gcp']]")]
    assert actual == expected


def test_partial_member_overlap_matches_group():
    case = {**EXPECTED, "required_any": [["AWS", "GCP", "Azure"]]}
    jd = JD + " Azure experience is a bonus."
    host_json = _host(required_any=[["AWS", "GCP"]])

    checks = run_checks(host_json, case, jd)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "")]
    assert actual == expected


def test_extra_host_group_is_a_note():
    case = {**EXPECTED, "required_any": []}
    jd = JD + " Kafka and Kinesis experience preferred."
    host_json = _host(required_any=[["Kafka", "Kinesis"]])

    checks = run_checks(host_json, case, jd)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "extra host groups: [['kafka', 'kinesis']]")]
    assert actual == expected


def test_hyphenated_expected_group_is_not_treated_as_drift():
    """A dash-flattened expected group ("arm cortex m") must not be tested for presence against
    the JD text - only the raw member ("ARM Cortex-M") appears there, so a naive presence
    check on the normalized form would wrongly read this as content drift and skip it."""
    case = {**EXPECTED, "required_any": [["ARM Cortex-M", "RTOS"]]}
    jd = JD + " Experience with ARM Cortex-M and RTOS required."
    host_json = _host(required_any=[])

    checks = run_checks(host_json, case, jd)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [
        Check("groups_match", False, "unmatched expected groups: [['arm cortex m', 'rtos']]")
    ]
    assert actual == expected


def test_host_group_collapsing_two_independent_required_terms_fails():
    """The host claimed "Redis or Terraform" (only one needed) when EXPECTED lists both as
    separate, independent preferred requirements - that inflates preferred_coverage the same
    way an invented OR-group would, and the union-based term checks alone can't catch it."""
    checks = run_checks(_host(preferred_any=[["Redis", "Terraform"]], preferred=[]), EXPECTED, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [
        Check(
            "groups_match",
            False,
            "host collapsed independent required/preferred terms into an OR-group: "
            "[['redis', 'terraform']]",
        )
    ]
    assert actual == expected


def test_host_group_with_only_one_known_member_is_still_a_note():
    """Only one of the group's members ("Redis") is a term EXPECTED lists separately - that is
    not evidence of collapsing two known-independent requirements, so it stays a permitted
    extra group, same as one built entirely from unknown terms."""
    case = {**EXPECTED, "required_any": []}
    host_json = _host(required_any=[], preferred_any=[["Redis", "Kinesis"]], preferred=["Redis"])

    checks = run_checks(host_json, case, JD + " Kinesis experience preferred.")

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "extra host groups: [['kinesis', 'redis']]")]
    assert actual == expected


def test_host_group_sharing_a_real_group_member_still_fails_on_collapsed_terms():
    """The host's group shares "AWS" with the real required_any=[["AWS","GCP"]] group, so it
    is not an unmatched-expected-group failure - but it also smuggles in Redis and Terraform,
    two independent preferred requirements, riding along on that legitimate overlap. Only
    checking groups with no expected counterpart would let this through."""
    host_json = _host(required_any=[["AWS", "Redis", "Terraform"]], preferred=[])
    checks = run_checks(host_json, EXPECTED, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [
        Check(
            "groups_match",
            False,
            "host collapsed independent required/preferred terms into an OR-group: "
            "[['aws', 'redis', 'terraform']]",
        )
    ]
    assert actual == expected


def test_repeated_group_member_does_not_double_count_as_overgrouped():
    """A host group with a repeated member ("Redis" twice) only names ONE distinct known term -
    a naive per-member sum would count it as two and wrongly fail this as collapsed-terms."""
    case = {**EXPECTED, "required_any": []}
    host_json = _host(required_any=[], preferred_any=[["Redis", "Redis"]], preferred=["Redis"])

    checks = run_checks(host_json, case, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "extra host groups: [['redis', 'redis']]")]
    assert actual == expected


def test_drifted_expected_group_is_skipped():
    case = {**EXPECTED, "required_any": [["Kubernetes", "Docker Swarm"]]}
    host_json = _host(required_any=[])

    checks = run_checks(host_json, case, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "")]
    assert actual == expected


def test_wrong_years_and_title_fail_exact_checks():
    checks = run_checks(_host(required_years=5, title="Backend Engineer"), EXPECTED, JD)

    actual = [c for c in checks if c.name in ("required_years_exact", "title_exact")]

    expected = [
        Check("required_years_exact", False, "host 5.0 != expected 4.0"),
        Check(
            "title_exact",
            False,
            "host 'Backend Engineer' != expected 'Senior Backend Engineer'",
        ),
    ]
    assert actual == expected


THIN_EXPECTED = {
    "title": "Senior Backend Engineer",
    "company": "Northwind",
    "required": ["Python", "FastAPI", "Kubernetes"],
    "preferred": ["Redis", "Terraform"],
    "required_any": [],
    "preferred_any": [],
    "required_years": 4.0,
}


def test_thin_expected_is_not_evaluated():
    # 5 expected terms total; only Python and FastAPI are still in the JD (2/5 = 0.4 < 0.6)
    jd = "Senior Backend Engineer at Northwind. Requirements: Python, FastAPI."
    host_json = json.dumps({**THIN_EXPECTED, "required": ["Python"], "preferred": []})

    checks = run_checks(host_json, THIN_EXPECTED, jd)

    actual = [c for c in checks if c.name in ("term_recall", "term_precision")]

    detail = "not evaluated: only 2 of 5 expected terms are still in the JD (content drift)"
    expected = [
        Check("term_recall", True, detail, skipped=True),
        Check("term_precision", True, detail, skipped=True),
    ]
    assert actual == expected


def test_expected_with_most_terms_live_is_evaluated_normally():
    # 5 expected terms total; 4 are still in the JD (4/5 = 0.8 >= 0.6), so the guard does not trip
    jd = "Senior Backend Engineer at Northwind. Requirements: Python, FastAPI, Redis, Terraform."
    host_json = json.dumps(
        {**THIN_EXPECTED, "required": ["Python", "FastAPI"], "preferred": ["Redis", "Terraform"]}
    )

    checks = run_checks(host_json, THIN_EXPECTED, jd)

    actual = [c for c in checks if c.name in ("term_recall", "term_precision")]

    expected = [Check("term_recall", True, ""), Check("term_precision", True, "")]
    assert actual == expected


def test_union_counts_group_members_and_preferred():
    # 2 required + 2 preferred + 2 group members = 6
    case = {**EXPECTED, "required": ["Python", "FastAPI"]}
    # host misses one preferred (Terraform) and one group member (GCP), but the group is still
    # covered - one shared member (AWS) is enough under the coverage rule
    host_json = _host(required=["Python", "FastAPI"], preferred=["Redis"], required_any=[["AWS"]])

    checks = run_checks(host_json, case, JD)

    actual = [c for c in checks if c.name in ("term_recall", "term_precision", "groups_match")]

    expected = [
        Check("term_recall", True, ""),
        Check("term_precision", True, ""),
        Check("groups_match", True, ""),
    ]
    assert actual == expected
