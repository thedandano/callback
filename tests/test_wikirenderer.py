"""Tests for callback.wikirenderer — WikiRenderer."""

from pathlib import Path

from callback.profilecompiler import ProfileCompiler
from callback.state import CompiledProfile, CreatedStory
from callback.wiki import WikiStore
from callback.wikirenderer import WikiRenderer


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
    profile, _ = ProfileCompiler().compile(stories, host_tags=host_tags)
    return profile


def _make_store(tmp_path: Path) -> WikiStore:

    store = WikiStore()
    store.__class__ = type(
        "PatchedWikiStore",
        (WikiStore,),
        {"wiki_root": lambda self, label: tmp_path / label},
    )
    return store


class TestExperiencePage:
    def test_experience_page_written(self, tmp_path: Path):
        story = _make_story()
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_experience_page("backend", story)

        page = tmp_path / "backend" / "experience" / "story-001.md"
        assert page.exists()

    def test_experience_page_has_sbi_sections(self, tmp_path: Path):
        story = _make_story(
            situation="We had no auth.",
            behavior="Implemented OAuth.",
            impact="Zero incidents.",
        )
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_experience_page("backend", story)

        content = (tmp_path / "backend" / "experience" / "story-001.md").read_text()
        assert "**Situation:** We had no auth." in content
        assert "**Behavior:** Implemented OAuth." in content
        assert "**Impact:** Zero incidents." in content

    def test_experience_page_has_skills_line(self, tmp_path: Path):
        story = _make_story(skills=["FastAPI", "Python"])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_experience_page("backend", story)

        content = (tmp_path / "backend" / "experience" / "story-001.md").read_text()
        assert "Skills:" in content
        assert "FastAPI" in content
        assert "Python" in content

    def test_experience_page_has_job_title(self, tmp_path: Path):
        story = _make_story(job_title="Platform Engineer")
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_experience_page("backend", story)

        content = (tmp_path / "backend" / "experience" / "story-001.md").read_text()
        assert "Platform Engineer" in content

    def test_company_slug_derivation(self, tmp_path: Path):
        story = _make_story(id="story-042")
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_experience_page("backend", story)

        assert (tmp_path / "backend" / "experience" / "story-042.md").exists()

    def test_deterministic_output(self, tmp_path: Path):
        story = _make_story()
        r1 = WikiRenderer(store=_make_store(tmp_path))
        r1.render_experience_page("backend", story)
        content1 = (tmp_path / "backend" / "experience" / "story-001.md").read_text()

        r2 = WikiRenderer(store=_make_store(tmp_path))
        r2.render_experience_page("backend", story)
        content2 = (tmp_path / "backend" / "experience" / "story-001.md").read_text()

        assert content1 == content2


class TestIndexPage:
    def test_index_written(self, tmp_path: Path):
        story = _make_story()
        profile = _make_profile([story])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_index("backend", profile)

        assert (tmp_path / "backend" / "index.md").exists()

    def test_index_links_covered_skills(self, tmp_path: Path):
        story = _make_story(primary_skill="Python", skills=["FastAPI"])
        profile = _make_profile([story])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "[Python]" in content
        assert "[FastAPI]" in content

    def test_index_links_point_to_experience_pages(self, tmp_path: Path):
        story = _make_story(id="story-001", primary_skill="Python", skills=[])
        profile = _make_profile([story])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "experience/story-001.md" in content

    def test_index_has_orphaned_skills_section(self, tmp_path: Path):
        story = _make_story(primary_skill="Python", skills=[])
        profile = _make_profile([story], orphans=["Rust"])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "## Orphaned Skills" in content
        assert "Rust" in content

    def test_index_no_orphan_section_when_empty(self, tmp_path: Path):
        story = _make_story(primary_skill="Python", skills=[])
        profile = _make_profile([story])
        renderer = WikiRenderer(store=_make_store(tmp_path))
        renderer.render_index("backend", profile)

        content = (tmp_path / "backend" / "index.md").read_text()
        assert "## Orphaned Skills" not in content

    def test_index_deterministic(self, tmp_path: Path):
        story = _make_story()
        profile = _make_profile([story])
        r1 = WikiRenderer(store=_make_store(tmp_path))
        r1.render_index("backend", profile)
        content1 = (tmp_path / "backend" / "index.md").read_text()

        r2 = WikiRenderer(store=_make_store(tmp_path))
        r2.render_index("backend", profile)
        content2 = (tmp_path / "backend" / "index.md").read_text()

        assert content1 == content2
