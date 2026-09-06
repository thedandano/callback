"""Tests for profile_nodes — real store-backed implementations."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import callback.extractor as ext
import callback.repository.resumes as resumes_module
from callback import paths
from callback.profile_nodes import (
    _resume_skills,
    check_orphans,
    check_profile,
    compile_profile,
    create_story,
    onboard,
)
from callback.profilecompiler import save_compiled_profile
from callback.repository import stories
from callback.repository.accomplishments import AccomplishmentsStore
from callback.repository.resumes import (
    get_resume,
    list_resumes,
    replace_resume,
    save_resume,
)
from callback.state import (
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
        _make_compiled_profile(tmp_path / "callback")

        result = check_profile(_make_state())

        assert result == {"profile_exists": True}

    def test_returns_false_when_profile_exists_but_no_resumes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _make_compiled_profile(tmp_path / "callback")

        result = check_profile(_make_state())

        assert result == {"profile_exists": False}

    def test_check_profile_true_with_resume_but_no_compiled_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        resume_file = _make_resume_file(tmp_path)
        save_resume("jane_doe", str(resume_file))

        result = check_profile(_make_state())

        assert result == {"profile_exists": True}


class TestOnboard:
    def test_no_resume_path_returns_no_resume_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        result = onboard(_make_state())

        assert result == {"intake": {"status": "no_resume"}}

    def test_valid_resume_path_saves_sections_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        resume_file = _make_resume_file(tmp_path)
        state = _make_state(resume_path=str(resume_file))

        result = onboard(state)

        sections_path = tmp_path / "profile-wiki" / "primary" / "sections.json"
        assert sections_path.exists()
        assert json.loads(sections_path.read_text())["contact"]["name"] == "Jane Doe"

        text = ext.extract(str(resume_file))
        expected_sections = ext.extract_sections(text).model_dump()

        assert result == {
            "resume_label": "primary",
            "resume_path": str(resume_file),
            "sections": expected_sections,
            "intake": {
                "status": "onboarded",
                "resume_label": "primary",
                "stories": [],
            },
        }

    def test_onboard_saves_onboard_text_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        resume_file = _make_resume_file(tmp_path)
        state = _make_state(
            resume_path=str(resume_file),
            intake={"onboard_text": "I love building distributed systems."},
        )

        onboard(state)

        text = AccomplishmentsStore(base_dir=tmp_path / "callback").load_onboard_text()
        assert text == "I love building distributed systems."

    def test_onboard_migrates_legacy_stories_from_accomplishments_json(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        legacy_story = {"id": "story-001", **_STORY_FIELDS}
        accomplishments_dir = tmp_path / "callback"
        accomplishments_dir.mkdir(parents=True)
        (accomplishments_dir / "accomplishments.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "onboard_text": "",
                    "created_stories": [legacy_story],
                }
            ),
            encoding="utf-8",
        )

        resume_file = _make_resume_file(tmp_path)
        state = _make_state(resume_path=str(resume_file))

        result = onboard(state)

        page = tmp_path / "profile-wiki" / "primary" / "experience" / "story-001.md"
        actual = {
            "intake_stories": result["intake"]["stories"],
            "page_has_frontmatter": page.is_file() and page.read_text().startswith("---\n"),
        }
        expected = {
            "intake_stories": [CreatedStory(**legacy_story).model_dump()],
            "page_has_frontmatter": True,
        }
        assert actual == expected


class TestCompileProfile:
    def test_builds_wiki_pages_and_saves_compiled_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        saved_story = stories.save_story("jane_doe", CreatedStory(id="", **_STORY_FIELDS))
        page_path = tmp_path / "profile-wiki" / "jane_doe" / "experience" / "story-001.md"
        page_before = page_path.read_text()

        state = _make_state(resume_label="jane_doe")
        result = compile_profile(state)

        compiled_profile = result["compiled_profile"]
        compiled_at = compiled_profile.pop("compiled_at")

        actual = {
            "compiled_at_is_nonempty_str": isinstance(compiled_at, str) and len(compiled_at) > 0,
            "compiled_profile_json_exists": (
                tmp_path / "callback" / "compiled_profile.json"
            ).exists(),
            "index_md_exists": (tmp_path / "profile-wiki" / "jane_doe" / "index.md").exists(),
            "story_page_untouched": page_path.read_text() == page_before,
            "compiled_profile": compiled_profile,
            "intake": result["intake"],
        }
        expected = {
            "compiled_at_is_nonempty_str": True,
            "compiled_profile_json_exists": True,
            "index_md_exists": True,
            "story_page_untouched": True,
            "compiled_profile": {
                "schema_version": "1",
                "skills_index": sorted(["Python", "Docker"], key=str.lower),
                "stories": [saved_story.model_dump()],
                "orphaned_skills": [],
            },
            "intake": {
                "skill_coverage_warnings": [],
                "skills_index": sorted(["Python", "Docker"], key=str.lower),
            },
        }
        assert actual == expected


class TestResumeSkills:
    def test_invalid_sections_json_returns_empty_list_and_logs_warning(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        page_dir = tmp_path / "profile-wiki" / "jane_doe"
        page_dir.mkdir(parents=True)
        (page_dir / "sections.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level("WARNING"):
            result = _resume_skills("jane_doe")

        actual = {
            "result": result,
            "warning_logged": any(
                record.levelname == "WARNING" and "jane_doe" in record.getMessage()
                for record in caplog.records
            ),
        }
        expected = {"result": [], "warning_logged": True}
        assert actual == expected


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
        save_compiled_profile(profile, base_dir=tmp_path / "callback")

        result = check_orphans(_make_state())

        assert result == {"orphaned_skills": ["Rust"]}

    def test_uses_thread_state_compiled_profile_over_disk(self, tmp_path, monkeypatch):
        """A concurrent session's disk compile must not swap in different orphans."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        disk_profile = CompiledProfile(
            schema_version="1",
            skills_index=["Terraform"],
            stories=[],
            orphaned_skills=[OrphanedSkill(skill="Terraform", deferred=False)],
            compiled_at=datetime.now(UTC).isoformat(),
        )
        save_compiled_profile(disk_profile, base_dir=tmp_path / "callback")

        state = _make_state(
            compiled_profile={
                "orphaned_skills": [
                    {"skill": "Rust", "deferred": False},
                    {"skill": "Go", "deferred": True},
                ]
            }
        )
        result = check_orphans(state)

        assert result == {"orphaned_skills": ["Rust"]}

    def test_falls_back_to_disk_when_thread_state_has_no_compiled_profile(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        disk_profile = CompiledProfile(
            schema_version="1",
            skills_index=["Terraform"],
            stories=[],
            orphaned_skills=[OrphanedSkill(skill="Terraform", deferred=False)],
            compiled_at=datetime.now(UTC).isoformat(),
        )
        save_compiled_profile(disk_profile, base_dir=tmp_path / "callback")

        result = check_orphans(_make_state(compiled_profile=None))

        assert result == {"orphaned_skills": ["Terraform"]}


class TestCreateStory:
    def test_saves_story_and_returns_story_id(self, tmp_path, monkeypatch):
        # No resume is registered, so create_story's _registered_label falls back
        # to "default" — that fallback is what this test exercises.
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        state = _make_state(intake=_STORY_FIELDS)
        result = create_story(state)

        expected_saved = CreatedStory(id="story-001", **_STORY_FIELDS)
        actual = {
            "stored": stories.list_stories("default")[0],
            "result": result,
        }
        expected = {
            "stored": [expected_saved],
            "result": {
                "current_story_target": "Python",
                "intake": {
                    **_STORY_FIELDS,
                    "story_id": "story-001",
                    "needs_compile": True,
                },
            },
        }
        assert actual == expected


class TestOnboardValidatesBeforeClearing:
    def test_onboard_keeps_old_resume_when_replacement_is_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        existing_resume = _make_resume_file(tmp_path)
        save_resume("existing_label", str(existing_resume))

        missing_path = str(tmp_path / "does_not_exist.pdf")
        state = _make_state(resume_path=missing_path)

        with pytest.raises(FileNotFoundError):
            onboard(state)

        assert list_resumes() == ["existing_label"]


class TestOnboardIdempotency:
    def test_re_onboard_replaces_resume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "profile-wiki")

        resume1_txt = """\
Jane Doe
jane@example.com

Experience
Acme | Engineer | 2020 - 2021
- Built systems

Skills
Python, Docker
"""
        resume1 = tmp_path / "first.txt"
        resume1.write_text(resume1_txt, encoding="utf-8")

        resume2_txt = """\
Jane Doe
jane@example.com

Experience
Beta | Senior Engineer | 2021 - 2022
- Led projects

Skills
Rust, Go
"""
        resume2 = tmp_path / "second.txt"
        resume2.write_text(resume2_txt, encoding="utf-8")

        state1 = _make_state(resume_path=str(resume1))
        onboard(state1)

        state2 = _make_state(resume_path=str(resume2))
        onboard(state2)

        assert list_resumes() == ["primary"]


class TestReplaceResume:
    def test_replace_resume_with_registered_file_as_source_keeps_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        source = tmp_path / "resume.txt"
        source.write_text("original content", encoding="utf-8")
        save_resume("primary", str(source))

        replace_resume("primary", get_resume("primary"))

        assert list_resumes() == ["primary"]
        assert Path(get_resume("primary")).read_text(encoding="utf-8") == "original content"

    def test_replace_resume_keeps_old_when_copy_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        source = tmp_path / "resume.txt"
        source.write_text("original content", encoding="utf-8")
        save_resume("primary", str(source))

        replacement = tmp_path / "replacement.txt"
        replacement.write_text("new content", encoding="utf-8")

        def _raise_disk_full(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(resumes_module.shutil, "copy2", _raise_disk_full)

        with pytest.raises(OSError, match="disk full"):
            replace_resume("primary", str(replacement))

        assert list_resumes() == ["primary"]
        assert list(paths.inputs_dir().glob("*.staging")) == []
