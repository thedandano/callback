"""Tests for scoring engine: _run_score, score_initial, score_final, parse_final, report."""

import pytest

from pi_apply.apply_nodes import _run_score, parse_final, report, score_final, score_initial
from pi_apply.state import ApplyState

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


class TestRunScore:
    def test_returns_full_breakdown(self):
        result = _run_score(
            RESUME_WITH_KEYWORDS,
            {"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
        )
        expected = {
            "total": 94.0,
            "keyword_match": 45.0,
            "experience_fit": 25.0,
            "impact_evidence": 4.0,
            "ats_format": 10.0,
            "readability": 10.0,
            "req_matched": ["Python"],
            "req_unmatched": [],
            "pref_matched": ["AWS"],
            "pref_unmatched": [],
        }
        assert result == expected

    def test_keyword_classification(self):
        kws = {"required": ["Python", "Go"], "preferred": ["AWS"], "required_years": 0.0}
        result = _run_score(RESUME_WITH_KEYWORDS, kws)
        expected = {
            "total": result["total"],
            "keyword_match": result["keyword_match"],
            "experience_fit": 25.0,
            "impact_evidence": 4.0,
            "ats_format": 10.0,
            "readability": 10.0,
            "req_matched": ["Python"],
            "req_unmatched": ["Go"],
            "pref_matched": ["AWS"],
            "pref_unmatched": [],
        }
        assert result == expected

    def test_required_years_reduces_experience_fit(self):
        kws_base = {"required": ["ZZZNONEXISTENT"], "preferred": []}
        no_years = _run_score("some resume text", {**kws_base, "required_years": 0})
        high_years = _run_score("some resume text", {**kws_base, "required_years": 100})
        expected_no_years = {
            "total": 35.0,
            "keyword_match": 0.0,
            "experience_fit": 25.0,
            "impact_evidence": 0.0,
            "ats_format": 0.0,
            "readability": 10.0,
            "req_matched": [],
            "req_unmatched": ["ZZZNONEXISTENT"],
            "pref_matched": [],
            "pref_unmatched": [],
        }
        expected_high_years = {**expected_no_years, "total": 25.0, "experience_fit": 15.0}
        assert no_years == expected_no_years
        assert high_years == expected_high_years

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
                "total": 94.0,
                "keyword_match": 45.0,
                "experience_fit": 25.0,
                "impact_evidence": 4.0,
                "ats_format": 10.0,
                "readability": 10.0,
                "req_matched": ["Python"],
                "req_unmatched": [],
                "pref_matched": ["AWS"],
                "pref_unmatched": [],
            }
        }
        assert score_initial(state) == expected

    def test_stubs_on_none_parsed_initial(self):
        state = ApplyState(session_id="s1", parsed_initial=None, keywords=None)
        assert score_initial(state) == {
            "score_initial": {"total": 0, "stub": True, "parsed_chars": 0}
        }

    def test_stubs_on_noop_sentinel(self):
        state = ApplyState(session_id="s1", parsed_initial="<noop:parse:no-source>", keywords=None)
        assert score_initial(state) == {
            "score_initial": {"total": 0, "stub": True, "parsed_chars": 0}
        }

    def test_stubs_on_none_keywords(self):
        state = ApplyState(session_id="s1", parsed_initial=RESUME_WITH_KEYWORDS, keywords=None)
        assert score_initial(state) == {
            "score_initial": {"total": 0, "stub": True, "parsed_chars": 0}
        }


class TestScoreFinal:
    def test_scores_real_text(self):
        state = ApplyState(
            session_id="s1",
            parsed_final=RESUME_WITH_KEYWORDS,
            keywords={"required": ["Python"], "preferred": ["AWS"], "required_years": 0.0},
        )
        expected = {
            "score_final": {
                "total": 94.0,
                "keyword_match": 45.0,
                "experience_fit": 25.0,
                "impact_evidence": 4.0,
                "ats_format": 10.0,
                "readability": 10.0,
                "req_matched": ["Python"],
                "req_unmatched": [],
                "pref_matched": ["AWS"],
                "pref_unmatched": [],
            }
        }
        assert score_final(state) == expected

    def test_stubs_on_noop_sentinel(self):
        state = ApplyState(session_id="s1", parsed_final="<noop:parse:empty-pdf>", keywords=None)
        assert score_final(state) == {"score_final": {"total": 0, "stub": True, "parsed_chars": 0}}

    def test_stubs_on_none_parsed_final(self):
        state = ApplyState(session_id="s1", parsed_final=None, keywords=None)
        assert score_final(state) == {"score_final": {"total": 0, "stub": True, "parsed_chars": 0}}

    def test_stubs_on_none_keywords(self):
        state = ApplyState(session_id="s1", parsed_final=RESUME_WITH_KEYWORDS, keywords=None)
        assert score_final(state) == {"score_final": {"total": 0, "stub": True, "parsed_chars": 0}}


class TestParseFinal:
    def test_sentinel_for_no_pdf_path(self):
        state = ApplyState(session_id="x", pdf_path=None)
        assert parse_final(state) == {"parsed_final": "<noop:parse:no-pdf-path>"}

    def test_sentinel_for_empty_pdf(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"")
        state = ApplyState(session_id="x", pdf_path=str(p))
        assert parse_final(state) == {"parsed_final": "<noop:parse:empty-pdf>"}

    def test_sentinel_for_missing_file(self, tmp_path):
        state = ApplyState(session_id="x", pdf_path=str(tmp_path / "nonexistent.pdf"))
        assert parse_final(state) == {"parsed_final": "<noop:parse:empty-pdf>"}

    def test_extracts_txt_file(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("Python developer with AWS experience", encoding="utf-8")
        state = ApplyState(session_id="x", pdf_path=str(txt))
        assert parse_final(state) == {"parsed_final": "Python developer with AWS experience"}


class TestReport:
    def test_computes_delta(self):
        state = ApplyState(
            session_id="s1",
            score_initial={"total": 45.0},
            score_final={"total": 72.0},
        )
        assert report(state) == {
            "report": {"delta_total": 27.0, "score_initial_total": 45.0, "score_final_total": 72.0}
        }

    def test_handles_stub_scores(self):
        state = ApplyState(
            session_id="s1",
            score_initial={"total": 0, "stub": True},
            score_final={"total": 0, "stub": True},
        )
        assert report(state) == {
            "report": {"delta_total": 0, "score_initial_total": 0, "score_final_total": 0}
        }

    def test_handles_none_scores(self):
        state = ApplyState(session_id="s1", score_initial=None, score_final=None)
        assert report(state) == {
            "report": {"delta_total": 0.0, "score_initial_total": 0.0, "score_final_total": 0.0}
        }
