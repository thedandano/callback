"""Tests for pi_apply.profilecompiler — ProfileCompiler and I/O helpers."""

from pathlib import Path

import pytest
from rapidfuzz import fuzz

from pi_apply.profilecompiler import (
    ProfileCompiler,
    ProfileMissingError,
    load_compiled_profile,
    save_compiled_profile,
)
from pi_apply.state import CompiledProfile, CreatedStory, OrphanedSkill


def _make_story(
    id: str,
    primary_skill: str,
    skills: list[str],
    job_title: str = "Engineer",
) -> CreatedStory:
    return CreatedStory(
        id=id,
        primary_skill=primary_skill,
        skills=skills,
        story_type="STAR",
        job_title=job_title,
        situation="S",
        behavior="B",
        impact="I",
    )


class TestThreeTierUnion:
    def test_all_three_tiers_contribute(self):
        story = _make_story("story-001", "Kubernetes", ["Docker"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["Terraform"])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=sorted(["Docker", "Kubernetes", "Terraform"], key=str.lower),
            stories=[story],
            orphaned_skills=[OrphanedSkill(skill="Terraform", deferred=False)],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_primary_skill_floor_invariant(self):
        story = _make_story("story-001", "Kubernetes", [])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=[])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=["Kubernetes"],
            stories=[story],
            orphaned_skills=[],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_dedup_case_insensitive_preserves_first_seen_casing(self):
        story = _make_story("story-001", "Python", ["python", "PYTHON"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["PYTHON"])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=["Python"],
            stories=[story],
            orphaned_skills=[],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_skills_index_is_sorted(self):
        story = _make_story("story-001", "Terraform", ["Kubernetes", "AWS"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=[])
        assert profile.skills_index == sorted(profile.skills_index, key=str.lower)


class TestOrphanDetection:
    def test_host_tag_not_in_any_story_is_orphaned(self):
        story = _make_story("story-001", "Python", ["FastAPI"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["Rust"])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=sorted(["FastAPI", "Python", "Rust"], key=str.lower),
            stories=[story],
            orphaned_skills=[OrphanedSkill(skill="Rust", deferred=False)],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_host_tag_matching_primary_skill_is_not_orphaned(self):
        story = _make_story("story-001", "Python", [])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["python"])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=["Python"],
            stories=[story],
            orphaned_skills=[],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_host_tag_matching_story_skills_is_not_orphaned(self):
        story = _make_story("story-001", "Python", ["Docker"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["DOCKER"])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=sorted(["Docker", "Python"], key=str.lower),
            stories=[story],
            orphaned_skills=[],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected

    def test_no_host_tags_no_orphans(self):
        story = _make_story("story-001", "Python", ["Docker"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=[])
        expected = CompiledProfile(
            schema_version="1",
            skills_index=sorted(["Docker", "Python"], key=str.lower),
            stories=[story],
            orphaned_skills=[],
            compiled_at=profile.compiled_at,
        )
        assert profile == expected


class TestFuzzyWarning:
    def test_low_fuzzy_score_returns_warning(self):
        story = _make_story("story-001", "Kubernetes", ["k8s"])
        compiler = ProfileCompiler()
        _, warnings = compiler.compile([story], host_tags=[])
        score = int(fuzz.token_sort_ratio("Kubernetes", "k8s"))
        expected_warnings = [
            f"story-001: primary_skill 'Kubernetes' not found in skills"
            f" (best match: 'k8s' at {score}%)"
        ]
        assert warnings == expected_warnings

    def test_exact_match_in_skills_no_warning(self):
        story = _make_story("story-001", "Python", ["Python", "Django"])
        compiler = ProfileCompiler()
        _, warnings = compiler.compile([story], host_tags=[])
        assert warnings == []

    def test_case_insensitive_exact_match_no_warning(self):
        story = _make_story("story-001", "Kubernetes", ["kubernetes"])
        compiler = ProfileCompiler()
        _, warnings = compiler.compile([story], host_tags=[])
        assert warnings == []

    def test_empty_story_skills_emits_warning(self):
        story = _make_story("story-001", "Kubernetes", [])
        compiler = ProfileCompiler()
        _, warnings = compiler.compile([story], host_tags=[])
        expected_warnings = [
            "story-001: primary_skill 'Kubernetes' not found in skills (best match: none at 0%)"
        ]
        assert warnings == expected_warnings

    def test_multiple_stories_only_low_score_warned(self):
        story_ok = _make_story("story-001", "Python", ["Python"])
        story_bad = _make_story("story-002", "Kubernetes", ["k8s"])
        compiler = ProfileCompiler()
        _, warnings = compiler.compile([story_ok, story_bad], host_tags=[])
        score = int(fuzz.token_sort_ratio("Kubernetes", "k8s"))
        expected_warnings = [
            f"story-002: primary_skill 'Kubernetes' not found in skills"
            f" (best match: 'k8s' at {score}%)"
        ]
        assert warnings == expected_warnings


class TestNoDataMutation:
    def test_compile_does_not_modify_input_stories(self):
        story = _make_story("story-001", "Python", ["Docker"])
        original = story.model_copy()
        compiler = ProfileCompiler()
        compiler.compile([story], host_tags=["Rust"])
        assert story == original

    def test_compile_does_not_modify_host_tags(self):
        story = _make_story("story-001", "Python", [])
        host_tags = ["Rust", "Go"]
        original_tags = list(host_tags)
        compiler = ProfileCompiler()
        compiler.compile([story], host_tags=host_tags)
        assert host_tags == original_tags


class TestRoundTrip:
    def test_save_then_load_returns_equal_object(self, tmp_path: Path):
        story = _make_story("story-001", "Python", ["FastAPI", "Docker"])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=["Terraform"])
        save_compiled_profile(profile, base_dir=tmp_path)
        loaded = load_compiled_profile(base_dir=tmp_path)
        assert loaded == profile

    def test_save_creates_file(self, tmp_path: Path):
        story = _make_story("story-001", "Python", [])
        compiler = ProfileCompiler()
        profile, _ = compiler.compile([story], host_tags=[])
        save_compiled_profile(profile, base_dir=tmp_path)
        assert (tmp_path / "compiled_profile.json").exists()


class TestProfileMissingError:
    def test_load_raises_when_file_absent(self, tmp_path: Path):
        with pytest.raises(ProfileMissingError):
            load_compiled_profile(base_dir=tmp_path)
