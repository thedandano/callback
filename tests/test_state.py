import pytest
from pydantic import ValidationError

from pi_apply.state import (
    ApplyState,
    CompiledProfile,
    CreatedStory,
    OrphanedSkill,
    ProfileState,
    TailoredResume,
)


class TestApplyStateBasic:
    """Test ApplyState initialization and required field."""

    def test_accepts_session_id_only(self):
        """ApplyState accepts only session_id; all other fields default to None."""
        state = ApplyState(session_id="abc")
        assert state.session_id == "abc"
        assert state.jd_url is None
        assert state.jd_raw_text is None
        assert state.jd_text is None
        assert state.keywords is None
        assert state.resume_label is None
        assert state.parsed_initial is None
        assert state.parsed_final is None
        assert state.score_initial is None
        assert state.score_final is None
        assert state.tailored is None
        assert state.tailored_sections is None
        assert state.pdf_path is None
        assert state.report is None
        assert state.uncovered_skills is None
        assert state.finalized is None
        assert state.error is None
        assert state.no_coverage is None

    def test_rejects_missing_session_id(self):
        """ApplyState raises ValidationError when session_id is missing."""
        with pytest.raises(ValidationError) as exc_info:
            ApplyState()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert any("session_id" in str(e) for e in errors)

    def test_all_fields_present(self):
        """ApplyState has all required fields defined."""
        fields = ApplyState.model_fields
        required_fields = {
            "session_id",
            "jd_url",
            "jd_raw_text",
            "jd_text",
            "keywords",
            "resume_label",
            "sections",
            "wiki_index",
            "parsed_initial",
            "parsed_final",
            "score_initial",
            "score_final",
            "tailored",
            "tailored_sections",
            "pdf_path",
            "report",
            "uncovered_skills",
            "finalized",
            "finalized_at",
            "error",
            "no_coverage",
        }
        assert set(fields.keys()) == required_fields

    def test_legacy_fields_absent(self):
        """ApplyState does not have legacy fields from walking-skeleton."""
        legacy_fields = {
            "resume_content",
            "resume_path",
            "scored_resumes",
            "tailored_t1",
            "tailored_t2",
            "edits_t1",
            "edits_t2",
        }
        model_fields = set(ApplyState.model_fields.keys())
        assert not legacy_fields.intersection(model_fields)

    def test_field_types_jd_url(self):
        """jd_url field accepts str or None."""
        state1 = ApplyState(session_id="s1", jd_url="https://example.com")
        assert state1.jd_url == "https://example.com"
        state2 = ApplyState(session_id="s2", jd_url=None)
        assert state2.jd_url is None

    def test_field_types_jd_raw_text(self):
        """jd_raw_text field accepts str or None."""
        state = ApplyState(session_id="s", jd_raw_text="Raw JD text")
        assert state.jd_raw_text == "Raw JD text"

    def test_field_types_jd_text(self):
        """jd_text field accepts str or None."""
        state = ApplyState(session_id="s", jd_text="Processed JD")
        assert state.jd_text == "Processed JD"

    def test_field_types_keywords_dict(self):
        """keywords field accepts dict or None."""
        kw = {"title": "Engineer", "required": ["Python"]}
        state = ApplyState(session_id="s", keywords=kw)
        assert state.keywords == kw

    def test_field_types_resume_label(self):
        """resume_label field accepts str or None."""
        state = ApplyState(session_id="s", resume_label="backend")
        assert state.resume_label == "backend"

    def test_field_types_parsed_initial(self):
        """parsed_initial field accepts str or None."""
        state = ApplyState(session_id="s", parsed_initial="Initial text")
        assert state.parsed_initial == "Initial text"

    def test_field_types_parsed_final(self):
        """parsed_final field accepts str or None."""
        state = ApplyState(session_id="s", parsed_final="Final text")
        assert state.parsed_final == "Final text"

    def test_field_types_score_initial_dict(self):
        """score_initial field accepts dict or None."""
        score = {"total": 45, "keyword_match": 30}
        state = ApplyState(session_id="s", score_initial=score)
        assert state.score_initial == score

    def test_field_types_score_final_dict(self):
        """score_final field accepts dict or None."""
        score = {"total": 50, "keyword_match": 35}
        state = ApplyState(session_id="s", score_final=score)
        assert state.score_final == score

    def test_field_types_tailored(self):
        """tailored field accepts TailoredResume or None."""
        tr = TailoredResume(name="Jane Doe")
        state = ApplyState(session_id="s", tailored=tr)
        assert state.tailored == tr

    def test_field_types_pdf_path(self):
        """pdf_path field accepts str or None."""
        state = ApplyState(session_id="s", pdf_path="/tmp/output.pdf")
        assert state.pdf_path == "/tmp/output.pdf"

    def test_field_types_report_dict(self):
        """report field accepts dict or None."""
        report = {"audit": "trail", "timestamp": "2026-05-01"}
        state = ApplyState(session_id="s", report=report)
        assert state.report == report

    def test_field_types_uncovered_skills_list(self):
        """uncovered_skills field accepts list or None."""
        skills = ["Kubernetes", "Docker"]
        state = ApplyState(session_id="s", uncovered_skills=skills)
        assert state.uncovered_skills == skills

    def test_field_types_finalized(self):
        """finalized field accepts bool or None."""
        state_true = ApplyState(session_id="s", finalized=True)
        assert state_true.finalized is True
        state_false = ApplyState(session_id="s", finalized=False)
        assert state_false.finalized is False

    def test_field_types_error(self):
        """error field accepts str or None."""
        state = ApplyState(session_id="s", error="Some error message")
        assert state.error == "Some error message"

    def test_field_types_no_coverage(self):
        """no_coverage field accepts bool."""
        state = ApplyState(session_id="s", no_coverage=True)
        assert state.no_coverage is True

    def test_multiple_fields_together(self):
        """ApplyState accepts multiple fields set simultaneously."""
        state = ApplyState(
            session_id="s1",
            jd_url="https://example.com",
            keywords={"title": "Engineer"},
            resume_label="backend",
            finalized=False,
        )
        assert state.session_id == "s1"
        assert state.jd_url == "https://example.com"
        assert state.keywords is not None and state.keywords["title"] == "Engineer"
        assert state.resume_label == "backend"
        assert state.finalized is False


class TestProfileStateBasic:
    """Test ProfileState initialization and required field."""

    def test_accepts_session_id_only(self):
        """ProfileState accepts only session_id; all other fields default to None."""
        state = ProfileState(session_id="xyz")
        assert state.session_id == "xyz"
        assert state.profile_exists is None
        assert state.intake is None
        assert state.compiled_profile is None
        assert state.orphaned_skills is None
        assert state.current_story_target is None
        assert state.error is None

    def test_rejects_missing_session_id(self):
        """ProfileState raises ValidationError when session_id is missing."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileState()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert any("session_id" in str(e) for e in errors)

    def test_all_fields_present(self):
        """ProfileState has all required fields defined."""
        fields = ProfileState.model_fields
        required_fields = {
            "session_id",
            "profile_exists",
            "resume_label",
            "resume_path",
            "sections",
            "wiki_path",
            "intake",
            "compiled_profile",
            "orphaned_skills",
            "current_story_target",
            "error",
        }
        assert set(fields.keys()) == required_fields

    def test_field_types_profile_exists(self):
        """profile_exists field accepts bool or None."""
        state_true = ProfileState(session_id="s", profile_exists=True)
        assert state_true.profile_exists is True
        state_false = ProfileState(session_id="s", profile_exists=False)
        assert state_false.profile_exists is False

    def test_field_types_intake_dict(self):
        """intake field accepts dict or None."""
        intake = {"resume": "text", "skills": ["Python"]}
        state = ProfileState(session_id="s", intake=intake)
        assert state.intake == intake

    def test_field_types_compiled_profile_dict(self):
        """compiled_profile field accepts dict or None."""
        profile = {"skills": {"Python": ["story1"]}}
        state = ProfileState(session_id="s", compiled_profile=profile)
        assert state.compiled_profile == profile

    def test_field_types_orphaned_skills_list(self):
        """orphaned_skills field accepts list or None."""
        skills = ["Kubernetes", "Terraform"]
        state = ProfileState(session_id="s", orphaned_skills=skills)
        assert state.orphaned_skills == skills

    def test_field_types_current_story_target(self):
        """current_story_target field accepts str or None."""
        state = ProfileState(session_id="s", current_story_target="Kubernetes")
        assert state.current_story_target == "Kubernetes"

    def test_field_types_error(self):
        """error field accepts str or None."""
        state = ProfileState(session_id="s", error="Error message")
        assert state.error == "Error message"

    def test_multiple_fields_together(self):
        """ProfileState accepts multiple fields set simultaneously."""
        state = ProfileState(
            session_id="s1",
            profile_exists=True,
            orphaned_skills=["Go", "Rust"],
            current_story_target="Go",
        )
        assert state.session_id == "s1"
        assert state.profile_exists is True
        assert state.orphaned_skills == ["Go", "Rust"]
        assert state.current_story_target == "Go"


class TestCreatedStory:
    """Schema round-trips and field validation for CreatedStory."""

    def _make_story(self, **overrides):
        defaults = {
            "id": "story-001",
            "primary_skill": "Kubernetes",
            "skills": ["Kubernetes", "Helm"],
            "story_type": "technical",
            "job_title": "Platform Engineer",
            "situation": "Legacy infra had no container orchestration.",
            "behavior": "Migrated 12 services to Kubernetes on EKS.",
            "impact": "Reduced deploy time by 60%.",
        }
        return CreatedStory(**{**defaults, **overrides})

    def test_round_trip(self):
        story = self._make_story()
        assert CreatedStory.model_validate(story.model_dump()) == story

    def test_all_fields_present(self):
        expected = {
            "id",
            "primary_skill",
            "skills",
            "story_type",
            "job_title",
            "situation",
            "behavior",
            "impact",
        }
        assert set(CreatedStory.model_fields) == expected

    def test_skills_accepts_empty_list(self):
        story = self._make_story(skills=[])
        assert story.skills == []

    def test_rejects_missing_required_field(self):
        with pytest.raises(ValidationError):
            CreatedStory(id="s", primary_skill="k8s", skills=[], story_type="t", job_title="j")  # type: ignore[call-arg]


class TestOrphanedSkill:
    def test_defaults_deferred_false(self):
        expected = OrphanedSkill(skill="Terraform", deferred=False)
        assert OrphanedSkill(skill="Terraform") == expected

    def test_round_trip(self):
        o = OrphanedSkill(skill="Go", deferred=True)
        assert OrphanedSkill.model_validate(o.model_dump()) == o


class TestCompiledProfile:
    """Schema round-trips and field validation for CompiledProfile."""

    def _make_profile(self, **overrides):
        story = CreatedStory(
            id="story-001",
            primary_skill="Kubernetes",
            skills=["Kubernetes"],
            story_type="technical",
            job_title="SRE",
            situation="s",
            behavior="b",
            impact="i",
        )
        defaults = {
            "schema_version": "1",
            "skills_index": ["Kubernetes", "Terraform"],
            "stories": [story],
            "orphaned_skills": [OrphanedSkill(skill="Terraform")],
            "compiled_at": "2026-05-06T12:00:00+00:00",
        }
        return CompiledProfile(**{**defaults, **overrides})

    def test_round_trip(self):
        profile = self._make_profile()
        assert CompiledProfile.model_validate(profile.model_dump()) == profile

    def test_schema_version_is_one(self):
        profile = self._make_profile()
        assert profile.schema_version == "1"

    def test_all_fields_present(self):
        fields = set(CompiledProfile.model_fields)
        expected = {"schema_version", "skills_index", "stories", "orphaned_skills", "compiled_at"}
        assert fields == expected

    def test_empty_stories_and_orphans(self):
        profile = self._make_profile(stories=[], orphaned_skills=[])
        assert CompiledProfile.model_validate(profile.model_dump()) == profile


class TestStateModelIndependence:
    """Test that ApplyState and ProfileState are independent."""

    def test_apply_state_not_subclass_of_profile_state(self):
        """ApplyState is not a subclass of ProfileState."""
        assert not issubclass(ApplyState, ProfileState)

    def test_profile_state_not_subclass_of_apply_state(self):
        """ProfileState is not a subclass of ApplyState."""
        assert not issubclass(ProfileState, ApplyState)

    def test_distinct_classes(self):
        """ApplyState and ProfileState are distinct Python classes."""
        assert ApplyState is not ProfileState
        apply_inst = ApplyState(session_id="a")
        profile_inst = ProfileState(session_id="p")
        assert type(apply_inst) is not type(profile_inst)
