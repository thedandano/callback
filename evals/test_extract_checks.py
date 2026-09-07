"""E1 checks: precision/recall against the golden, substring discipline, exact scalars."""

from __future__ import annotations

import json

from evals.checks import Check, first_failure
from evals.extract_checks import PrecisionRecall, precision_recall, run_checks

JD = (
    "Senior Backend Engineer at Northwind. Requirements: Python, FastAPI, PostgreSQL, "
    "and 4+ years building services on AWS or GCP. Nice to have: Redis, Terraform."
)
GOLDEN = {
    "title": "Senior Backend Engineer",
    "company": "Northwind",
    "required": ["Python", "FastAPI", "PostgreSQL"],
    "preferred": ["Redis", "Terraform"],
    "required_any": [["AWS", "GCP"]],
    "preferred_any": [],
    "required_years": 4.0,
}


def _host(**overrides) -> str:
    return json.dumps({**GOLDEN, **overrides})


def _names(checks: list[Check]) -> dict[str, bool]:
    return {c.name: c.passed for c in checks}


def test_golden_as_host_output_passes_every_check():
    actual = _names(run_checks(_host(), GOLDEN, JD))

    expected = {
        "valid_jd_data": True,
        "required_recall": True,
        "required_precision": True,
        "preferred_recall": True,
        "preferred_precision": True,
        "groups_match": True,
        "terms_are_jd_substrings": True,
        "required_years_exact": True,
        "title_exact": True,
    }
    assert actual == expected


def test_invalid_json_is_the_only_check():
    checks = run_checks("not json", GOLDEN, JD)

    actual = [(c.name, c.passed) for c in checks]

    expected = [("valid_jd_data", False)]
    assert actual == expected


def test_precision_recall_ignores_golden_terms_absent_from_jd():
    golden_terms = ["Python", "Kubernetes"]  # Kubernetes drifted off the page

    actual = precision_recall(["Python"], golden_terms, JD)

    expected = PrecisionRecall(precision=1.0, recall=1.0, missing=[], extra=[])
    assert actual == expected


def test_precision_recall_reports_missing_and_extra():
    actual = precision_recall(["python", "Docker"], ["Python", "FastAPI"], JD)

    expected = PrecisionRecall(precision=0.5, recall=0.5, missing=["FastAPI"], extra=["Docker"])
    assert actual == expected


def test_paraphrased_term_fails_substring_check():
    checks = run_checks(_host(required=["Python", "FastAPI", "Postgres"]), GOLDEN, JD)

    actual = first_failure(checks)

    expected = "required_recall: missing ['PostgreSQL']"
    assert actual == expected


def test_paraphrase_alone_is_caught_by_substring_check():
    golden = {**GOLDEN, "required": ["Python", "FastAPI"]}
    checks = run_checks(_host(required=["Python", "FastAPI", "Postgres"]), golden, JD)

    actual = [c for c in checks if not c.passed]

    expected = [
        Check("required_precision", False, "0.67 < 0.75; extra ['Postgres']"),
        Check("terms_are_jd_substrings", False, "not in JD: ['Postgres']"),
    ]
    assert actual == expected


def test_groups_compare_as_sets_regardless_of_order():
    checks = run_checks(_host(required_any=[["GCP", "AWS"]]), GOLDEN, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", True, "")]
    assert actual == expected


def test_missing_group_fails_groups_match():
    checks = run_checks(_host(required_any=[]), GOLDEN, JD)

    actual = [c for c in checks if c.name == "groups_match"]

    expected = [Check("groups_match", False, "missing [['aws', 'gcp']]; extra []")]
    assert actual == expected


def test_wrong_years_and_title_fail_exact_checks():
    checks = run_checks(_host(required_years=5, title="Backend Engineer"), GOLDEN, JD)

    actual = [c for c in checks if c.name in ("required_years_exact", "title_exact")]

    expected = [
        Check("required_years_exact", False, "host 5.0 != golden 4.0"),
        Check("title_exact", False, "host 'Backend Engineer' != golden 'Senior Backend Engineer'"),
    ]
    assert actual == expected


def test_empty_preferred_on_both_sides_is_a_pass():
    golden = {**GOLDEN, "preferred": []}
    checks = run_checks(_host(preferred=[]), golden, JD)

    actual = [c for c in checks if c.name.startswith("preferred")]

    expected = [Check("preferred_recall", True, ""), Check("preferred_precision", True, "")]
    assert actual == expected
