import logging
from pathlib import Path

import pytest

from callback.repository import stories
from callback.state import CreatedStory
from callback.wiki import WikiPageError, WikiStore

_FIELDS = {
    "primary_skill": "Python",
    "skills": ["Python", "Docker"],
    "story_type": "SBI",
    "job_title": "Engineer",
    "situation": "We had no CI.",
    "behavior": "Built it.",
    "impact": "Deploys daily.",
}
_TS = "2026-09-06T21:00:00+00:00"


@pytest.fixture
def wiki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
    return tmp_path


def test_story_to_page_exact_format():
    page = stories.story_to_page(CreatedStory(id="story-001", **_FIELDS), _TS)
    expected = (
        "---\n"
        "type: story\n"
        "title: Python\n"
        "job_title: Engineer\n"
        "tags:\n- Python\n- Docker\n"
        "story_type: SBI\n"
        f"timestamp: '{_TS}'\n"
        "---\n"
        "# Python\n\n"
        "**Situation:** We had no CI.\n\n"
        "**Behavior:** Built it.\n\n"
        "**Impact:** Deploys daily.\n"
    )
    assert page == expected


def test_project_job_title_sets_type_project():
    project_story = CreatedStory(id="story-002", **{**_FIELDS, "job_title": "Project"})
    page = stories.story_to_page(project_story, _TS)
    assert page.startswith("---\ntype: project\n")


def test_story_from_page_round_trips(wiki: Path):
    story = CreatedStory(id="story-007", **_FIELDS)
    page = stories.story_to_page(story, _TS)
    assert stories.story_from_page("experience/story-007.md", page) == story


def test_story_from_page_uses_filename_as_id_and_survives_body_edits(wiki: Path):
    page = stories.story_to_page(CreatedStory(id="story-001", **_FIELDS), _TS)
    edited = page.replace(
        "**Impact:** Deploys daily.", "**Impact:** Deploys daily; zero rollbacks."
    )
    story = stories.story_from_page("experience/story-009.md", edited)
    actual = {"id": story.id, "impact": story.impact}
    expected = {"id": "story-009", "impact": "Deploys daily; zero rollbacks."}
    assert actual == expected


def test_story_from_page_missing_label_is_empty_and_logged(wiki: Path, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    page = stories.story_to_page(CreatedStory(id="story-001", **_FIELDS), _TS).replace(
        "\n\n**Impact:** Deploys daily.\n", "\n"
    )
    story = stories.story_from_page("experience/story-001.md", page)
    actual = {"impact": story.impact, "warned": any("Impact" in r.message for r in caplog.records)}
    expected = {"impact": "", "warned": True}
    assert actual == expected


def test_story_from_page_rejects_page_without_type():
    with pytest.raises(WikiPageError) as exc_info:
        stories.story_from_page("experience/story-001.md", "# no frontmatter\n")
    assert "type" in str(exc_info.value)


def test_save_story_assigns_next_id_and_writes_one_file(wiki: Path):
    saved = stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    files = sorted(p.name for p in (wiki / "primary" / "experience").iterdir())
    actual = {
        "id": saved.id,
        "files": files,
        "type_line": (wiki / "primary" / "experience" / "story-001.md").read_text().splitlines()[1],
    }
    expected = {"id": "story-001", "files": ["story-001.md"], "type_line": "type: story"}
    assert actual == expected


def test_save_story_ids_are_sequential_after_the_highest_existing(wiki: Path):
    stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    stories.save_story("primary", CreatedStory(id="", **{**_FIELDS, "primary_skill": "Go"}))
    (wiki / "primary" / "experience" / "story-001.md").unlink()
    rust_story = CreatedStory(id="", **{**_FIELDS, "primary_skill": "Rust"})
    third = stories.save_story("primary", rust_story)
    assert third.id == "story-003"


def test_save_story_identical_content_returns_existing_without_new_file(wiki: Path):
    first = stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    second = stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    files = sorted(p.name for p in (wiki / "primary" / "experience").iterdir())
    actual = {"second_id": second.id, "same": first == second, "files": files}
    expected = {"second_id": "story-001", "same": True, "files": ["story-001.md"]}
    assert actual == expected


def test_list_stories_in_id_order_and_skips_unreadable_with_warning(wiki: Path, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    stories.save_story("primary", CreatedStory(id="", **{**_FIELDS, "primary_skill": "B"}))
    stories.save_story("primary", CreatedStory(id="", **{**_FIELDS, "primary_skill": "A"}))
    WikiStore().write_page("primary", "experience/notes.md", "# hand-written, no frontmatter\n")
    listed, warnings = stories.list_stories("primary")
    actual = {
        "ids": [s.id for s in listed],
        "skills": [s.primary_skill for s in listed],
        "warnings": warnings,
        "logged": any("notes.md" in r.message for r in caplog.records),
    }
    expected = {
        "ids": ["story-001", "story-002"],
        "skills": ["B", "A"],
        "warnings": ["experience/notes.md: skipped: frontmatter has no 'type'"],
        "logged": True,
    }
    assert actual == expected


def test_list_stories_empty_when_no_experience_dir(wiki: Path):
    assert stories.list_stories("nobody") == ([], [])
