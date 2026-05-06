"""Tests for profile_nodes — real store-backed implementations."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pi_apply.extractor as ext
import pi_apply.wiki as wiki_module
from pi_apply.profile_nodes import (
    check_orphans,
    check_profile,
    compile_profile,
    create_story,
    onboard,
)
from pi_apply.profilecompiler import save_compiled_profile
from pi_apply.repository.accomplishments import AccomplishmentsStore
from pi_apply.repository.resumes import save_resume
from pi_apply.state import (
    CompiledProfile,
    CreatedStory,
    OrphanedSkill,
    ProfileState,
)

RESUME_TXT = """\
Jane Doe
jane@example.com

Experience
Acme Corp | Software Engineer | 2020 - 2023
- Built Python microservices serving 10k daily users.
- Reduced deploy time by 60% via Kubernetes migration.

Skills
Python, Kubernetes, Docker
"""

_STORY_FIELDS = {
    "primary_skill": "Python",
    "skills": ["Python", "Docker"],
    "story_type": "STAR",
    "job_title": "Software Engineer",
    "situation": "Legacy system needed modernisation.",
    "behavior": "Refactored core services into microservices.",
    "impact": "Reduced latency by 40%.",
}


def _make_state(**kwargs) -> ProfileState:
    return ProfileState(session_id="test-session", **kwargs)


def _make_resume_file(tmp_path: Path) -> Path:
    resume = tmp_path / "jane_doe.txt"
    resume.write_text(RESUME_TXT, encoding="utf-8")
    return resume


def _make_compiled_profile(base_dir: Path) -> CompiledProfile:
    profile = CompiledProfile(
        schema_version="1",
        skills_index=["Python"],
        stories=[],
        orphaned_skills=[],
        compiled_at=datetime.now(UTC).isoformat(),
    )
    save_compiled_profile(profile, base_dir=base_dir)
    return profile


class TestCheckProfile:
    def test_returns_false_when_no_profile_and_no_resumes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = check_profile(_make_state())

        assert result == {"profile_exists": False}

    def test_returns_true_when_profile_and_resume_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        resume_file = _make_resume_file(tmp_path)
        save_resume("jane_doe", str(resume_file))
        _make_compiled_profile(tmp_path / "pi-apply")

        result = check_profile(_make_state())

        assert result == {"profile_exists": True}

    def test_returns_false_when_profile_exists_but_no_resumes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_compiled_profile(tmp_path / "pi-apply")

        result = check_profile(_make_state())

        assert result == {"profile_exists": False}


class TestOnboard:
    def test_no_resume_path_returns_no_resume_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")

        result = onboard(_make_state())

        assert result == {"intake": {"status": "no_resume"}}

    def test_valid_resume_path_saves_sections_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")

        resume_file = _make_resume_file(tmp_path)
        state = _make_state(resume_path=str(resume_file))

        result = onboard(state)

        sections_path = tmp_path / "profile-wiki" / "jane_doe" / "sections.json"
        assert sections_path.exists()
        assert json.loads(sections_path.read_text())["contact"]["name"] == "Jane Doe"

        text = ext.extract(str(resume_file))
        expected_sections = ext.extract_sections(text).model_dump()

        assert result == {
            "resume_label": "jane_doe",
            "resume_path": str(resume_file),
            "sections": expected_sections,
            "intake": {
                "status": "onboarded",
                "resume_label": "jane_doe",
                "stories": [],
            },
        }

    def test_onboard_saves_onboard_text_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")

        resume_file = _make_resume_file(tmp_path)
        state = _make_state(
            resume_path=str(resume_file),
            intake={"onboard_text": "I love building distributed systems."},
        )

        onboard(state)

        data = AccomplishmentsStore(base_dir=tmp_path / "pi-apply")._load()
        assert data == {
            "schema_version": "1",
            "onboard_text": "I love building distributed systems.",
            "created_stories": [],
        }


class TestCompileProfile:
    def test_builds_wiki_pages_and_saves_compiled_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")

        store = AccomplishmentsStore(base_dir=tmp_path / "pi-apply")
        saved_story = store.save_story(CreatedStory(id="", **_STORY_FIELDS))

        state = _make_state(resume_label="jane_doe")
        result = compile_profile(state)

        assert (tmp_path / "pi-apply" / "compiled_profile.json").exists()
        assert (tmp_path / "profile-wiki" / "jane_doe" / "index.md").exists()

        actual = result["compiled_profile"]
        compiled_at = actual.pop("compiled_at")
        assert isinstance(compiled_at, str) and len(compiled_at) > 0

        assert actual == {
            "schema_version": "1",
            "skills_index": sorted(["Python", "Docker"], key=str.lower),
            "stories": [saved_story.model_dump()],
            "orphaned_skills": [],
        }
        assert result["intake"] == {
            "skill_coverage_warnings": [],
            "skills_index": sorted(["Python", "Docker"], key=str.lower),
        }


class TestCheckOrphans:
    def test_returns_empty_list_when_no_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        result = check_orphans(_make_state())

        assert result == {"orphaned_skills": []}

    def test_returns_active_orphan_skills_from_loaded_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        profile = CompiledProfile(
            schema_version="1",
            skills_index=["Rust", "Go"],
            stories=[],
            orphaned_skills=[
                OrphanedSkill(skill="Rust", deferred=False),
                OrphanedSkill(skill="Go", deferred=True),
            ],
            compiled_at=datetime.now(UTC).isoformat(),
        )
        save_compiled_profile(profile, base_dir=tmp_path / "pi-apply")

        result = check_orphans(_make_state())

        assert result == {"orphaned_skills": ["Rust"]}


class TestCreateStory:
    def test_saves_story_and_returns_story_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        state = _make_state(intake=_STORY_FIELDS)
        result = create_story(state)

        stories = AccomplishmentsStore(base_dir=tmp_path / "pi-apply").list_stories()
        expected_saved = CreatedStory(id="story-001", **_STORY_FIELDS)
        assert stories == [expected_saved]

        assert result == {
            "current_story_target": "Python",
            "intake": {
                **_STORY_FIELDS,
                "story_id": "story-001",
                "needs_compile": True,
            },
        }
