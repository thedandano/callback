"""Tests for callback.wikirenderer — render_index."""

from pathlib import Path

import pytest

from callback.profilecompiler import compile_profile
from callback.state import CompiledProfile, CreatedStory
from callback.wikirenderer import render_index


def _make_story(
    id: str = "story-001",
    primary_skill: str = "Python",
    skills: list[str] | None = None,
    job_title: str = "Backend Engineer",
    situation: str = "We had no auth.",
    behavior: str = "Implemented OAuth.",
    impact: str = "Zero incidents.",
) -> CreatedStory:
    return CreatedStory(
        id=id,
        primary_skill=primary_skill,
        skills=skills if skills is not None else ["Python", "FastAPI"],
        story_type="technical",
        job_title=job_title,
        situation=situation,
        behavior=behavior,
        impact=impact,
    )


def _make_profile(stories: list[CreatedStory], orphans: list[str] | None = None) -> CompiledProfile:
    host_tags = orphans or []
    profile, _ = compile_profile(stories, host_tags=host_tags)
    return profile


class TestIndexPage:
    def test_index_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story()
        profile = _make_profile([story])
        render_index("backend", profile)

        assert (tmp_path / "backend" / "index.md").exists()

    def test_index_links_covered_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story(primary_skill="Python", skills=["FastAPI"])
        profile = _make_profile([story])
        render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "[Python]" in content
        assert "[FastAPI]" in content

    def test_index_links_point_to_experience_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story(id="story-001", primary_skill="Python", skills=[])
        profile = _make_profile([story])
        render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "experience/story-001.md" in content

    def test_index_has_orphaned_skills_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story(primary_skill="Python", skills=[])
        profile = _make_profile([story], orphans=["Rust"])
        render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "## Orphaned Skills" in content
        assert "Rust" in content

    def test_index_no_orphan_section_when_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story(primary_skill="Python", skills=[])
        profile = _make_profile([story])
        render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "## Orphaned Skills" not in content

    def test_index_deterministic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
        story = _make_story()
        profile = _make_profile([story])
        render_index("backend", profile)
        content1 = (tmp_path / "backend" / "index.md").read_text()

        render_index("backend", profile)
        content2 = (tmp_path / "backend" / "index.md").read_text()

        assert content1 == content2
