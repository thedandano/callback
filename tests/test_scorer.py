"""Unit tests for callback.scorer — pure function, no I/O."""

import pytest

from callback import scorer
from callback.scorer import (
    ATSHeaderDiagnostic,
    ScoringConfig,
    _normalize_for_match,
    _score_ats,
    score,
)

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


def _ats_diag(
    expected: str,
    observed: str | None,
    matched: bool,
) -> ATSHeaderDiagnostic:
    return ATSHeaderDiagnostic(
        expected=expected,
        observed=observed,
        matched=matched,
        closeable_by="source_pdf",
    )


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

    def test_score_ats_all_headers_matched(self):
        """_score_ats on text with all three canonical headers → full score, all matched=True."""
        cfg = ScoringConfig()
        text = "Experience\nSenior Engineer role.\n\nEducation\nB.Sc. CS\n\nSkills\nPython"
        scalar, diags = _score_ats(text, cfg)
        assert scalar == pytest.approx(cfg.weights.ats_format)
        assert diags == [
            _ats_diag("Experience", "Experience", True),
            _ats_diag("Education", "Education", True),
            _ats_diag("Skills", "Skills", True),
        ]

    def test_score_ats_missing_skills_header(self):
        """_score_ats on text missing Skills header → 2/3 score, Skills diagnostic matched=False."""
        cfg = ScoringConfig()
        text = "Experience\nBuilt distributed systems.\n\nEducation\nB.Sc. CS"
        scalar, diags = _score_ats(text, cfg)
        assert scalar == pytest.approx(cfg.weights.ats_format * 2 / 3)
        assert diags == [
            _ats_diag("Experience", "Experience", True),
            _ats_diag("Education", "Education", True),
            _ats_diag("Skills", None, False),
        ]


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
        exp_half = result_half.breakdown.experience_fit
        exp_full = result_full.breakdown.experience_fit
        assert exp_half is not None
        assert exp_full is not None
        assert exp_half < exp_full

    def test_zero_required_years_not_evaluated(self):
        result = score("", required=[], preferred=[], candidate_years=0.0, required_years=0.0)
        assert result.breakdown.experience_fit is None

    def test_overqualification_penalty_applied(self):
        result_over = score("", required=[], preferred=[], candidate_years=12.0, required_years=5.0)
        result_exact = score("", required=[], preferred=[], candidate_years=5.0, required_years=5.0)
        exp_over = result_over.breakdown.experience_fit
        exp_exact = result_exact.breakdown.experience_fit
        assert exp_over is not None
        assert exp_exact is not None
        assert exp_over < exp_exact


class TestExperienceFitV2:
    RESUME = "Experience\nPython work\nEducation\nB.S.\nSkills\nPython"

    def test_not_evaluated_when_no_required_years(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=0.0)
        assert result.breakdown.experience_fit is None

    def test_not_evaluated_when_candidate_years_unknown(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=5.0)
        assert result.breakdown.experience_fit is None

    def test_partial_years_credit(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=5.0, required_years=10.0
        )
        # years-only: 5/10 = 0.5 → 0.5 × 15.0 = 7.5
        assert result.breakdown.experience_fit == 7.5

    def test_negative_candidate_years_clamps_to_zero(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=-3.0, required_years=5.0
        )
        assert result.breakdown.experience_fit == 0.0

    def test_overqualification_penalty(self):
        result = scorer.score(
            self.RESUME, ["Python"], [], candidate_years=25.0, required_years=10.0
        )
        # capped 1.0 × 0.85 penalty × 15.0 = 12.75
        assert result.breakdown.experience_fit == 12.75

    def test_total_renormalizes_when_not_evaluated(self):
        result = scorer.score(self.RESUME, ["Python"], [], required_years=0.0)
        b = result.breakdown
        base = b.keyword_match + b.impact_evidence + b.ats_format + b.readability
        assert b.total() == base * (100.0 / 85.0)  # exp weight is 15.0

    def test_unknown_seniority_kwarg_is_gone(self):
        with pytest.raises(TypeError):
            scorer.score(self.RESUME, ["Python"], [], seniority_match="exact")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("agent-based workflows", "agent based workflows"),
        ("machine–learning", "machine learning"),
        ("machine—learning", "machine learning"),
        ("retrieval­augmented generation", "retrieval augmented generation"),
        ("non‑breaking", "non breaking"),
        ("zero​width", "zero width"),
        ("ﬁnancial", "financial"),
        ("CI/CD", "CI/CD"),
        ("non-technical", "non technical"),
        ("", ""),
    ],
)
def test_normalize_for_match(text: str, expected: str) -> None:
    assert _normalize_for_match(text) == expected


def test_normalize_for_match_deterministic() -> None:
    result_a = _normalize_for_match("agent-based workflows")
    result_b = _normalize_for_match("agent-based workflows")
    assert result_a == result_b == "agent based workflows"


class TestNormalizedKeywordMatching:
    def test_hyphen_keyword_matches_space_in_resume(self):
        result = score(
            "agent based workflows in production",
            required=["agent-based workflows"],
            preferred=[],
        )
        assert result.keywords.req_pct == 1.0
        assert "agent-based workflows" in result.keywords.req_matched

    def test_en_dash_in_resume_matches_hyphen_keyword(self):
        result = score("machine–learning platform", required=["machine-learning"], preferred=[])
        assert result.keywords.req_pct == 1.0

    def test_soft_hyphen_in_resume_matches_keyword(self):
        result = score(
            "retrieval­augmented generation",
            required=["retrieval-augmented generation"],
            preferred=[],
        )
        assert result.keywords.req_pct == 1.0

    def test_fi_ligature_in_resume_matches_keyword(self):
        result = score("ﬁnancial modeling and analysis", required=["financial"], preferred=[])
        assert result.keywords.req_pct == 1.0

    def test_slash_term_still_matches(self):
        result = score("CI/CD pipelines", required=["CI/CD"], preferred=[])
        assert result.keywords.req_pct == 1.0

    def test_false_positive_guard(self):
        result = score("technical skills only", required=["non-technical"], preferred=[])
        assert result.keywords.req_pct == 0.0
        assert "non-technical" in result.keywords.req_unmatched


class TestPassThreshold:
    def test_strong_resume_passes(self):
        result = score(
            RESUME_WITH_SECTIONS, required=["Python", "Kubernetes"], preferred=["FastAPI"]
        )
        assert result.passes()

    def test_empty_resume_fails(self):
        result = score("", required=["Python", "Go", "Kubernetes"], preferred=["Rust"])
        assert not result.passes()


class TestImpactContactExclusion:
    def test_contact_lines_do_not_count_as_metrics(self):
        resume = (
            "Jane Doe\n"
            "555-867-5309 | jane@example.com | Austin, TX 78701\n"
            "linkedin.com/in/janedoe\n"
            "Experience\n"
            "- Reduced costs by 40%\n"
        )
        result = score(resume, ["Python"], [])
        assert result.metric_bullets == ["- Reduced costs by 40%"]


class TestPassThresholdConfig:
    def test_custom_pass_threshold_is_honored(self):
        from callback import scorer as scorer_mod

        cfg = scorer_mod.ScoringConfig(pass_threshold=99.0)
        result = scorer_mod.score("Experience\nPython work", ["Python"], [], cfg=cfg)
        assert result.pass_threshold == 99.0
        assert not result.passes()

    def test_default_config_threshold_is_70(self):
        from callback import scorer as scorer_mod

        assert scorer_mod.DEFAULT_SCORING_CONFIG.pass_threshold == 70.0
