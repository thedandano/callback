"""Tests for scoring engine: _run_score, score_initial, score_final, parse_final, report."""

import pytest

from callback.apply_nodes import _run_score, parse_final, report, score_final, score_initial
from callback.state import ApplyState

RESUME_WITH_KEYWORDS = (
    "Experience\n"
    "Acme Corp | Software Engineer | Jan 2020 - Present\n"
    "- Built Python microservices deployed on AWS, achieving 40% latency reduction\n"
    "- Designed REST APIs consumed by 500+ clients\n"
    "Skills\n"
    "Python, AWS, Docker\n"
    "Education\n"
    "B.S. Computer Science"
)


def _expected_ats_diagnostics(
    closeable_by: str = "source_pdf",
    matched: bool = True,
) -> list[dict]:
    observed = {
        "Experience": "Experience" if matched else None,
        "Education": "Education" if matched else None,
        "Skills": "Skills" if matched else None,
    }
    return [
        {
            "expected": expected,
            "observed": observed[expected],
            "matched": matched,
            "closeable_by": closeable_by,
        }
        for expected in ("Experience", "Education", "Skills")
    ]


class TestRunScore:
    def test_returns_full_breakdown(self):
        result = _run_score(
            RESUME_WITH_KEYWORDS,
            {"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
        )
        expected = {
            "total": 79.0 * (100.0 / 85.0),
            "keyword_match": 55.0,
            "experience_fit": None,
            "experience_evaluated": False,
            "impact_evidence": 4.0,
            "ats_format": 10.0,
            "readability": 10.0,
            "req_matched": ["Python"],
            "req_unmatched": [],
            "pref_matched": ["AWS"],
            "pref_unmatched": [],
            "ats_diagnostics": _expected_ats_diagnostics(),
            "scoring_engine_version": "v2",
        }
        assert result == expected

    def test_keyword_classification(self):
        kws = {"required": ["Python", "Go"], "preferred": ["AWS"], "required_years": 0.0}
        result = _run_score(RESUME_WITH_KEYWORDS, kws)
        expected = {
            "total": result["total"],
            "keyword_match": result["keyword_match"],
            "experience_fit": None,
            "experience_evaluated": False,
            "impact_evidence": 4.0,
            "ats_format": 10.0,
            "readability": 10.0,
            "req_matched": ["Python"],
            "req_unmatched": ["Go"],
            "pref_matched": ["AWS"],
            "pref_unmatched": [],
            "ats_diagnostics": _expected_ats_diagnostics(),
            "scoring_engine_version": "v2",
        }
        assert result == expected

    def test_experience_evaluated_with_candidate_years(self):
        kws = {"required": ["ZZZNONEXISTENT"], "preferred": [], "required_years": 10.0}
        result = _run_score("some resume text", kws, candidate_years=5.0)
        expected = {
            "total": 10.0 + 7.5,  # readability 10.0 + exp 0.5 × 15.0
            "keyword_match": 0.0,
            "experience_fit": 7.5,
            "experience_evaluated": True,
            "impact_evidence": 0.0,
            "ats_format": 0.0,
            "readability": 10.0,
            "req_matched": [],
            "req_unmatched": ["ZZZNONEXISTENT"],
            "pref_matched": [],
            "pref_unmatched": [],
            "scoring_engine_version": "v2",
            "ats_diagnostics": _expected_ats_diagnostics(matched=False),
        }
        assert result == expected

    def test_experience_not_evaluated_without_candidate_years(self):
        kws = {"required": ["ZZZNONEXISTENT"], "preferred": [], "required_years": 10.0}
        result = _run_score("some resume text", kws)
        assert result["experience_fit"] is None
        assert result["experience_evaluated"] is False
        assert result["total"] == 10.0 * (100.0 / 85.0)  # readability only, renormalized

    def test_raises_on_empty_text(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _run_score("", {"required": ["Python"]})

    def test_raises_on_whitespace_text(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _run_score("   \n  ", {"required": ["Python"]})

    def test_raises_on_empty_keywords(self):
        with pytest.raises(ValueError, match="must be non-empty"):
            _run_score("some text", {})

    def test_raises_on_none_required(self):
        with pytest.raises(ValueError, match="must be non-empty"):
            _run_score("some text", {"required": None})


class TestScoreInitial:
    def test_scores_real_text(self):
        state = ApplyState(
            session_id="s1",
            parsed_initial=RESUME_WITH_KEYWORDS,
            keywords={"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
        )
        expected = {
            "score_initial": {
                "total": 79.0 * (100.0 / 85.0),
                "keyword_match": 55.0,
                "experience_fit": None,
                "experience_evaluated": False,
                "impact_evidence": 4.0,
                "ats_format": 10.0,
                "readability": 10.0,
                "req_matched": ["Python"],
                "req_unmatched": [],
                "pref_matched": ["AWS"],
                "pref_unmatched": [],
                "ats_diagnostics": _expected_ats_diagnostics(),
                "scoring_engine_version": "v2",
            }
        }
        assert score_initial(state) == expected

    def test_raises_on_none_parsed_initial(self):
        state = ApplyState(session_id="s1", parsed_initial=None, keywords=None)
        with pytest.raises(ValueError, match="text must not be empty"):
            score_initial(state)

    def test_raises_on_none_keywords(self):
        state = ApplyState(session_id="s1", parsed_initial=RESUME_WITH_KEYWORDS, keywords=None)
        with pytest.raises(ValueError, match="keywords"):
            score_initial(state)


class TestScoreFinal:
    def test_scores_real_text(self):
        state = ApplyState(
            session_id="s1",
            parsed_final=RESUME_WITH_KEYWORDS,
            keywords={"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
        )
        expected = {
            "score_final": {
                "total": 79.0 * (100.0 / 85.0),
                "keyword_match": 55.0,
                "experience_fit": None,
                "experience_evaluated": False,
                "impact_evidence": 4.0,
                "ats_format": 10.0,
                "readability": 10.0,
                "req_matched": ["Python"],
                "req_unmatched": [],
                "pref_matched": ["AWS"],
                "pref_unmatched": [],
                "ats_diagnostics": _expected_ats_diagnostics(closeable_by="render"),
                "scoring_engine_version": "v2",
            }
        }
        assert score_final(state) == expected

    def test_raises_on_none_parsed_final(self):
        state = ApplyState(session_id="s1", parsed_final=None, keywords=None)
        with pytest.raises(ValueError, match="text must not be empty"):
            score_final(state)

    def test_raises_on_none_keywords(self):
        state = ApplyState(session_id="s1", parsed_final=RESUME_WITH_KEYWORDS, keywords=None)
        with pytest.raises(ValueError, match="keywords"):
            score_final(state)


class TestParseFinal:
    def test_halts_for_no_pdf_path(self):
        state = ApplyState(session_id="x", pdf_path=None)
        result = parse_final(state)
        assert "error" in result
        assert "parsed_final" not in result

    def test_halts_for_empty_pdf(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"")
        state = ApplyState(session_id="x", pdf_path=str(p))
        result = parse_final(state)
        assert "error" in result
        assert "parsed_final" not in result

    def test_halts_for_missing_file(self, tmp_path):
        state = ApplyState(session_id="x", pdf_path=str(tmp_path / "nonexistent.pdf"))
        result = parse_final(state)
        assert "error" in result
        assert "parsed_final" not in result

    def test_extracts_txt_file(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("Python developer with AWS experience", encoding="utf-8")
        state = ApplyState(session_id="x", pdf_path=str(txt))
        assert parse_final(state) == {"parsed_final": "Python developer with AWS experience"}


class TestReport:
    def test_computes_delta_total(self):
        state = ApplyState(
            session_id="s1",
            score_initial={"total": 45.0},
            score_final={"total": 72.0},
        )
        _none_dims = {
            "keyword_match": None,
            "experience_fit": None,
            "impact_evidence": None,
            "ats_format": None,
            "readability": None,
        }
        assert report(state) == {
            "report": {
                "before": {"total": 45.0, **_none_dims},
                "after": {"total": 72.0, **_none_dims},
                "delta": {"total": 27.0, **_none_dims},
                "format_gap_chars": 0,
                "no_coverage": False,
                "uncovered_skills": [],
                "experience_evaluated": None,
                "notes": [],
                "warnings": [],
            },
            "tailor_diagnostics": [],
        }

    def test_handles_none_scores(self):
        state = ApplyState(session_id="s1", score_initial=None, score_final=None)
        _dims = (
            "total",
            "keyword_match",
            "experience_fit",
            "impact_evidence",
            "ats_format",
            "readability",
        )
        _all_none = {d: None for d in _dims}
        assert report(state) == {
            "report": {
                "before": _all_none,
                "after": _all_none,
                "delta": _all_none,
                "format_gap_chars": 0,
                "no_coverage": False,
                "uncovered_skills": [],
                "experience_evaluated": None,
                "notes": [],
                "warnings": [],
            },
            "tailor_diagnostics": [],
        }


def test_run_score_stamps_engine_version():
    result = _run_score(
        RESUME_WITH_KEYWORDS,
        {"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
    )
    assert result["scoring_engine_version"] == "v2"


def test_report_notes_engine_version_mismatch():
    state = ApplyState(
        session_id="s1",
        score_initial={"total": 50.0},  # no version key — pre-upgrade checkpoint
        score_final={"total": 60.0, "scoring_engine_version": "v2"},
    )
    result = report(state)
    assert any("engine version" in note for note in result["report"]["notes"])


def test_report_delta_skips_unevaluated_experience():
    score = {
        "total": 40.0,
        "keyword_match": 30.0,
        "experience_fit": None,
        "experience_evaluated": False,
        "impact_evidence": 0.0,
        "ats_format": 0.0,
        "readability": 10.0,
        "scoring_engine_version": "v2",
        "ats_diagnostics": [],
    }
    state = ApplyState(
        session_id="s1",
        score_initial=score,
        score_final={**score, "total": 50.0, "keyword_match": 40.0},
    )
    result = report(state)
    assert result["report"]["delta"]["experience_fit"] is None
    assert result["report"]["delta"]["keyword_match"] == 10.0
    assert result["report"]["experience_evaluated"] is False
    assert any("not evaluated" in note for note in result["report"]["notes"])


def _score_stub(**overrides) -> dict:
    base = {
        "total": 50.0,
        "keyword_match": 40.0,
        "experience_fit": 7.5,
        "experience_evaluated": True,
        "impact_evidence": 0.0,
        "ats_format": 0.0,
        "readability": 10.0,
        "scoring_engine_version": "v2",
        "ats_diagnostics": [],
    }
    return {**base, **overrides}


class TestKnockoutWarnings:
    def _report(self, candidate_years, required_years):
        state = ApplyState(
            session_id="s1",
            candidate_years=candidate_years,
            keywords={"required": ["Python"], "preferred": [], "required_years": required_years},
            score_initial=_score_stub(),
            score_final=_score_stub(),
        )
        return report(state)["report"]["warnings"]

    def test_any_shortfall_warns_likely(self):
        warnings = self._report(candidate_years=7.0, required_years=8.0)
        assert len(warnings) == 1
        assert warnings[0].startswith("LIKELY KNOCKOUT")

    def test_double_gap_warns_strong(self):
        warnings = self._report(candidate_years=4.0, required_years=8.0)
        assert len(warnings) == 1
        assert warnings[0].startswith("STRONG KNOCKOUT RISK")

    def test_meeting_years_no_warning(self):
        assert self._report(candidate_years=9.0, required_years=8.0) == []

    def test_unknown_years_no_warning(self):
        assert self._report(candidate_years=None, required_years=8.0) == []
