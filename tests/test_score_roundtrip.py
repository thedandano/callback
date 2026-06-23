"""Tests for score delta computation and finalize archive (M3)."""

import json
import re

from callback.apply_nodes import _sections_to_text, finalize, report
from callback.scorer import ATS_SECTION_PATTERNS
from callback.section_map import EducationEntry, ExperienceEntry, SectionMap, SkillsSection
from callback.state import ApplyState, TailoredResume

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

_BEFORE = {
    "total": 35.0,
    "keyword_match": 0.0,
    "experience_fit": 25.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 10.0,
}

_AFTER = {
    "total": 52.5,
    "keyword_match": 17.5,
    "experience_fit": 25.0,
    "impact_evidence": 0.0,
    "ats_format": 0.0,
    "readability": 10.0,
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
            "before": _BEFORE,
            "after": _AFTER,
            "delta": _DELTA,
            "format_gap_chars": -150,
            "no_coverage": False,
            "uncovered_skills": [],
            "experience_evaluated": None,
            "notes": [],
            "warnings": [],
        },
        "tailor_diagnostics": [],
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
            "before": _BEFORE,
            "after": _AFTER,
            "delta": _DELTA,
            "format_gap_chars": -150,
            "no_coverage": False,
            "uncovered_skills": [],
            "experience_evaluated": None,
            "notes": [],
            "warnings": [],
        },
        "tailor_diagnostics": [],
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
            "before": _BEFORE,
            "after": _AFTER,
            "delta": _DELTA,
            "format_gap_chars": 200,
            "no_coverage": False,
            "uncovered_skills": [],
            "experience_evaluated": None,
            "notes": [],
            "warnings": [],
        },
        "tailor_diagnostics": [],
    }


def test_report_includes_render_warnings_as_notes():
    warning = {
        "code": "under_five_years_over_one_page",
        "message": (
            "Resume rendered to 2 pages; candidates with under 5 years of experience "
            "should stay within 1 page."
        ),
        "page_count": 2,
        "max_pages": 1,
        "candidate_experience_years": 3.8,
    }
    state = ApplyState(
        session_id="r-warning",
        score_initial=_SCORE_INITIAL,
        score_final=_SCORE_FINAL,
        render_page_count=2,
        render_warnings=[warning],
    )
    result = report(state)
    assert result["report"]["notes"] == [warning["message"]]


def test_finalize_archive_includes_scores_delta(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
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
    assert result == {"finalized": True, "finalized_at": result["finalized_at"]}

    archive = json.loads((tmp_path / "r4.json").read_text())
    assert archive["scores"] == {
        "initial": _SCORE_INITIAL,
        "final": _SCORE_FINAL,
        "delta": _DELTA,
        "scoring_engine_version": "v2",
    }
    assert archive["outcome"] == {"no_coverage": False, "reason": None}


def test_finalize_archive_scoring_engine_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
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
        "scoring_engine_version": "v2",
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
            "before": _BEFORE,
            "after": _BEFORE,
            "delta": _ZERO_DELTA,
            "format_gap_chars": -100,
            "no_coverage": True,
            "uncovered_skills": [],
            "experience_evaluated": None,
            "notes": [],
            "warnings": [],
        },
        "tailor_diagnostics": [],
    }


def test_finalize_archive_outcome_field(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
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
            "scoring_engine_version": "v2",
        },
    }


def test_sections_to_text_all_headers_injected():
    """_sections_to_text with non-empty core sections matches all ATS headers."""
    section_map = SectionMap(
        skills=SkillsSection(flat=["Python"], categorized={}),
        experience=[ExperienceEntry(company="ACME", role="Engineer", bullets=["Built services"])],
        education=[EducationEntry(institution="State University")],
    )
    text = _sections_to_text(section_map)
    assert (
        sum(1 for pat in ATS_SECTION_PATTERNS if any(pat.match(line) for line in text.splitlines()))
        == 3
    )


def test_sections_to_text_empty_education_no_education_header():
    """_sections_to_text with empty education list → no standalone Education header in output."""
    section_map = SectionMap(
        skills=SkillsSection(flat=["Python"], categorized={}),
        experience=[ExperienceEntry(company="ACME", role="Engineer", bullets=["Built services"])],
        education=[],
    )
    text = _sections_to_text(section_map)
    assert not any(
        re.compile(r"(?i)^\s*(?:academic\s+)?education\s*:?\s*$").match(line)
        for line in text.splitlines()
    )
