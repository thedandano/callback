"""Unit tests for pi_apply.scorer — pure function, no I/O."""
import pytest

from pi_apply.scorer import ScoringConfig, score


RESUME_WITH_SECTIONS = """
Experience
Led migration of 3 legacy services to Kubernetes, reducing deploy time by 60%.
Built Python and FastAPI microservices serving 10k daily users.
Introduced CI/CD pipelines that cut release cycle from 2 weeks to 2 days.

Education
B.Sc. Computer Science

Skills
Python, FastAPI, Kubernetes, Docker, PostgreSQL
"""

RESUME_PLAIN = "Python developer with experience in FastAPI and Docker."


class TestKeywordScoring:
    def test_required_keyword_matched(self):
        result = score(RESUME_PLAIN, required=["Python"], preferred=[])
        assert result.keywords.req_pct == 1.0
        assert "Python" in result.keywords.req_matched

    def test_required_keyword_unmatched(self):
        result = score(RESUME_PLAIN, required=["Kubernetes"], preferred=[])
        assert result.keywords.req_pct == 0.0
        assert "Kubernetes" in result.keywords.req_unmatched

    def test_preferred_only_uses_full_weight(self):
        result = score(RESUME_PLAIN, required=[], preferred=["Python"])
        cfg = ScoringConfig()
        assert result.breakdown.keyword_match == pytest.approx(cfg.weights.keyword_match)

    def test_special_chars_keyword(self):
        resume = "Strong C++ and .NET background."
        result = score(resume, required=["C++", ".NET"], preferred=[])
        assert result.keywords.req_pct == 1.0

    def test_case_insensitive_match(self):
        result = score("skilled in PYTHON", required=["python"], preferred=[])
        assert result.keywords.req_pct == 1.0

    def test_no_keywords_returns_zero(self):
        result = score(RESUME_PLAIN, required=[], preferred=[])
        assert result.breakdown.keyword_match == 0.0


class TestImpactScoring:
    def test_metric_bullet_detected(self):
        result = score(RESUME_WITH_SECTIONS, required=[], preferred=[])
        assert len(result.metric_bullets) >= 2

    def test_no_metrics_scores_zero(self):
        result = score("I worked on stuff.", required=[], preferred=[])
        assert result.breakdown.impact_evidence == 0.0

    def test_version_string_not_counted_as_metric(self):
        resume = "Migrated from Python 2.7 to Python 3.11."
        result = score(resume, required=[], preferred=[])
        assert result.breakdown.impact_evidence == 0.0

    def test_calendar_year_not_counted_as_metric(self):
        resume = "Joined the team in 2019."
        result = score(resume, required=[], preferred=[])
        assert result.breakdown.impact_evidence == 0.0


class TestATSFormatScoring:
    def test_all_sections_present_full_score(self):
        result = score(RESUME_WITH_SECTIONS, required=[], preferred=[])
        cfg = ScoringConfig()
        assert result.breakdown.ats_format == pytest.approx(cfg.weights.ats_format)

    def test_no_sections_scores_zero(self):
        result = score("Just some text.", required=[], preferred=[])
        assert result.breakdown.ats_format == 0.0


class TestReadabilityScoring:
    def test_filler_phrase_detected(self):
        result = score("I was responsible for deploying services.", required=[], preferred=[])
        assert "responsible for" in result.filler_phrases

    def test_no_fillers_full_score(self):
        result = score(RESUME_WITH_SECTIONS, required=[], preferred=[])
        cfg = ScoringConfig()
        assert result.breakdown.readability == pytest.approx(cfg.weights.readability)

    def test_multiple_fillers_penalized(self):
        resume = "I was responsible for and worked on and helped with things."
        result = score(resume, required=[], preferred=[])
        cfg = ScoringConfig()
        expected = max(cfg.weights.readability - 3 * cfg.readability_penalty_per_filler, 0.0)
        assert result.breakdown.readability == pytest.approx(expected)


class TestExperienceScoring:
    def test_years_met_full_credit(self):
        result = score("", required=[], preferred=[], candidate_years=5.0, required_years=5.0)
        cfg = ScoringConfig()
        assert result.breakdown.experience_fit == pytest.approx(cfg.weights.experience_fit)

    def test_years_unmet_partial_credit(self):
        result_half = score("", required=[], preferred=[], candidate_years=2.5, required_years=5.0)
        result_full = score("", required=[], preferred=[], candidate_years=5.0, required_years=5.0)
        assert result_half.breakdown.experience_fit < result_full.breakdown.experience_fit

    def test_zero_required_years_full_credit(self):
        result = score("", required=[], preferred=[], candidate_years=0.0, required_years=0.0)
        cfg = ScoringConfig()
        assert result.breakdown.experience_fit == pytest.approx(cfg.weights.experience_fit)

    def test_overqualification_penalty_applied(self):
        result_over = score("", required=[], preferred=[], candidate_years=12.0, required_years=5.0)
        result_exact = score("", required=[], preferred=[], candidate_years=5.0, required_years=5.0)
        assert result_over.breakdown.experience_fit < result_exact.breakdown.experience_fit


class TestPassThreshold:
    def test_strong_resume_passes(self):
        result = score(RESUME_WITH_SECTIONS, required=["Python", "Kubernetes"], preferred=["FastAPI"])
        assert result.passes()

    def test_empty_resume_fails(self):
        result = score("", required=["Python", "Go", "Kubernetes"], preferred=["Rust"])
        assert not result.passes()
