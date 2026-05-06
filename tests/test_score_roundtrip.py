"""Tests for score delta computation and finalize archive (M3)."""

import json

from pi_apply.apply_nodes import finalize, report
from pi_apply.state import ApplyState, TailoredResume

_SCORE_INITIAL = {
    "total": 35.0,
    "keyword_match": 0.0,
    "experience_fit": 25.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 10.0,
    "req_matched": [],
    "req_unmatched": ["Python"],
    "pref_matched": [],
    "pref_unmatched": [],
}

_SCORE_FINAL = {
    "total": 52.5,
    "keyword_match": 17.5,
    "experience_fit": 25.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 10.0,
    "req_matched": ["Python"],
    "req_unmatched": [],
    "pref_matched": [],
    "pref_unmatched": [],
}

_DELTA = {
    "total": 17.5,
    "keyword_match": 17.5,
    "experience_fit": 0.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 0.0,
}


def test_report_delta_all_six_dimensions():
    state = ApplyState(
        session_id="r1",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        parsed_initial="a" * 4000,
        parsed_final="b" * 3850,
    )
    result = report(state)
    assert result == {
        "report": {
            "delta": _DELTA,
            "format_gap_chars": -150,
            "no_coverage": False,
            "uncovered_skills": [],
        }
    }


def test_report_format_gap_chars_negative_on_content_loss():
    state = ApplyState(
        session_id="r2",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        parsed_initial="x" * 4000,
        parsed_final="y" * 3850,
    )
    assert report(state) == {
        "report": {
            "delta": _DELTA,
            "format_gap_chars": -150,
            "no_coverage": False,
            "uncovered_skills": [],
        }
    }


def test_report_format_gap_chars_positive_on_content_gain():
    state = ApplyState(
        session_id="r3",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        parsed_initial="x" * 100,
        parsed_final="y" * 300,
    )
    assert report(state) == {
        "report": {
            "delta": _DELTA,
            "format_gap_chars": 200,
            "no_coverage": False,
            "uncovered_skills": [],
        }
    }


def test_finalize_archive_includes_scores_delta(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    report_data = {
        "delta": _DELTA,
        "format_gap_chars": -150,
        "uncovered_skills": [],
    }
    state = ApplyState(
        session_id="r4",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        report=report_data,
        tailored=TailoredResume(name="Jane Doe"),
        parsed_initial="original resume text",
        parsed_final="tailored pdf text",
    )
    result = finalize(state)
    assert result == {"finalized": True}

    archive = json.loads((tmp_path / "r4.json").read_text())
    assert archive["scores"] == {
        "initial": _SCORE_INITIAL,
        "final": _SCORE_FINAL,
        "delta": _DELTA,
        "scoring_engine_version": "v1",
    }
    assert archive["outcome"] == {"no_coverage": False, "reason": None}


def test_finalize_archive_scoring_engine_version(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="r5",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        report={"delta": _DELTA, "format_gap_chars": 0, "uncovered_skills": []},
        tailored=TailoredResume(name="Jane Doe"),
        parsed_initial="text",
        parsed_final="text",
    )
    finalize(state)
    archive = json.loads((tmp_path / "r5.json").read_text())
    assert archive["scores"] == {
        "initial": _SCORE_INITIAL,
        "final": _SCORE_FINAL,
        "delta": _DELTA,
        "scoring_engine_version": "v1",
    }


_ZERO_DELTA = {
    "total": 0.0,
    "keyword_match": 0.0,
    "experience_fit": 0.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 0.0,
}


def test_report_no_coverage_path():
    state = ApplyState(
        session_id="r6",
        score_initial=_SCORE_INITIAL,
        no_coverage=True,
        parsed_initial="a" * 100,
        parsed_final=None,
    )
    assert report(state) == {
        "report": {
            "delta": _ZERO_DELTA,
            "format_gap_chars": -100,
            "no_coverage": True,
            "uncovered_skills": [],
        }
    }


def test_finalize_archive_outcome_field(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="r7",
        score_initial=_SCORE_INITIAL,
        no_coverage=True,
        report={"delta": {}, "format_gap_chars": 0, "uncovered_skills": []},
        tailored=TailoredResume(name="Jane Doe"),
        parsed_initial="text",
    )
    finalize(state)
    archive = json.loads((tmp_path / "r7.json").read_text())
    assert {k: archive[k] for k in ("outcome", "scores")} == {
        "outcome": {
            "no_coverage": True,
            "reason": "no wiki stories cover required keywords",
        },
        "scores": {
            "initial": _SCORE_INITIAL,
            "final": _SCORE_INITIAL,
            "delta": {},
            "scoring_engine_version": "v1",
        },
    }
