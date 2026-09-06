import json
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


def _legacy_json(tmp_path: Path, records: list[dict]) -> Path:
    data_dir = tmp_path / "callback"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "accomplishments.json"
    path.write_text(
        json.dumps({"schema_version": "1", "onboard_text": "notes", "created_stories": records})
    )
    return path


def test_migrate_writes_missing_files_and_drops_json_stories(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    path = _legacy_json(
        wiki,
        [
            {"id": "story-001", **_FIELDS},
            {"id": "story-002", **{**_FIELDS, "job_title": "Project"}},
        ],
    )
    written = stories.migrate_legacy_stories("primary")
    listed, warnings = stories.list_stories("primary")
    actual = {
        "written": written,
        "ids": [s.id for s in listed],
        "types": [
            (wiki / "primary" / "experience" / f"{s.id}.md").read_text().splitlines()[1]
            for s in listed
        ],
        "warnings": warnings,
        "json": json.loads(path.read_text()),
        "logged": any("migrated" in r.message for r in caplog.records),
    }
    expected = {
        "written": 2,
        "ids": ["story-001", "story-002"],
        "types": ["type: story", "type: project"],
        "warnings": [],
        "json": {"schema_version": "2", "onboard_text": "notes"},
        "logged": True,
    }
    assert actual == expected


def test_migrate_rewrites_a_legacy_page_without_frontmatter_but_not_one_with(
    wiki: Path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}, {"id": "story-002", **_FIELDS}])
    WikiStore().write_page("primary", "experience/story-001.md", "# old render, no frontmatter\n")
    hand_edited = stories.story_to_page(
        CreatedStory(id="story-002", **{**_FIELDS, "impact": "hand edit"}), _TS
    )
    WikiStore().write_page("primary", "experience/story-002.md", hand_edited)
    written = stories.migrate_legacy_stories("primary")
    listed, _ = stories.list_stories("primary")
    actual = {"written": written, "impacts": [s.impact for s in listed]}
    expected = {"written": 1, "impacts": ["Deploys daily.", "hand edit"]}
    assert actual == expected


def test_migrate_is_a_noop_once_json_has_no_stories(wiki: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    assert stories.migrate_legacy_stories("primary") == 0
