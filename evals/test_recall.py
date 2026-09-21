"""Unit tests for evals.recall: boundary-aware term matching and title coverage."""

from __future__ import annotations

from evals.recall import recall


def test_recall_c_does_not_match_inside_code():
    expected_jd = {"required": ["C"]}

    actual = recall("we write clean code every day", expected_jd)

    expected = {"found": 0, "total": 1, "missing": ["C"], "title_found": None}
    assert actual == expected


def test_recall_sql_does_not_match_inside_postgresql():
    expected_jd = {"required": ["SQL"]}

    actual = recall("we run PostgreSQL in production", expected_jd)

    expected = {"found": 0, "total": 1, "missing": ["SQL"], "title_found": None}
    assert actual == expected


def test_recall_matches_c_plus_plus_and_c_sharp_as_themselves():
    expected_jd = {"required": ["C++", "C#"]}

    actual = recall("we use C++ on the backend and C# on the client", expected_jd)

    expected = {"found": 2, "total": 2, "missing": [], "title_found": None}
    assert actual == expected


def test_recall_title_found_true_when_present():
    expected_jd = {"title": "Senior Engineer", "required": ["Python"]}

    actual = recall("Senior Engineer role. We use Python daily.", expected_jd)

    expected = {"found": 1, "total": 1, "missing": [], "title_found": True}
    assert actual == expected


def test_recall_title_found_false_when_absent():
    expected_jd = {"title": "Senior Engineer", "required": ["Python"]}

    actual = recall("Staff Developer role. We use Python daily.", expected_jd)

    expected = {"found": 1, "total": 1, "missing": [], "title_found": False}
    assert actual == expected


def test_recall_folds_curly_apostrophe_in_term_against_straight_quote_jd():
    expected_jd = {"required": ["Bachelor’s degree"]}

    actual = recall("Requires a Bachelor's degree in CS.", expected_jd)

    expected = {"found": 1, "total": 1, "missing": [], "title_found": None}
    assert actual == expected
