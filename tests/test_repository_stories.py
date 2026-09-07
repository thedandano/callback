import json
import logging
from pathlib import Path

import pytest

from callback.repository import stories
from callback.repository.accomplishments import AccomplishmentsStore
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


def test_story_from_page_rejects_bad_tags_before_logging_missing_labels(caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    page = "---\ntype: story\ntags: notalist\n---\n# No paragraphs at all\n"
    with pytest.raises(WikiPageError, match="tags must be a list"):
        stories.story_from_page("experience/story-001.md", page)
    assert not any("no '**" in r.message for r in caplog.records)


def test_body_paragraphs_duplicate_label_keeps_last_and_warns(caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    page = stories.story_to_page(CreatedStory(id="story-001", **_FIELDS), _TS).replace(
        "**Impact:** Deploys daily.\n",
        "**Impact:** Deploys daily.\n\n**Impact:** Overwritten by a second paragraph.\n",
    )
    story = stories.story_from_page("experience/story-001.md", page)
    actual = {
        "impact": story.impact,
        "warned": any("'**Impact:**' appears twice" in r.message for r in caplog.records),
    }
    expected = {
        "impact": "Overwritten by a second paragraph.",
        "warned": True,
    }
    assert actual == expected


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


def _with_registered_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Migration refuses to run with no resume registered (A4); tests that exercise
    the write path stand one up."""
    monkeypatch.setattr("callback.repository.stories.list_resumes", lambda: ["primary"])


def test_migrate_writes_missing_files_and_drops_json_stories(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
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
        "migrated_records": sorted(
            r.message for r in caplog.records if r.message.startswith("story migrated:")
        ),
    }
    expected = {
        "written": 2,
        "ids": ["story-001", "story-002"],
        "types": ["type: story", "type: project"],
        "warnings": [],
        "json": {"schema_version": "2", "onboard_text": "notes"},
        "logged": True,
        "migrated_records": [
            "story migrated: experience/story-001.md (Python, created)",
            "story migrated: experience/story-002.md (Python, created)",
        ],
    }
    assert actual == expected


def test_migrate_rewrites_a_legacy_page_without_frontmatter_but_not_one_with(
    wiki: Path, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}, {"id": "story-002", **_FIELDS}])
    WikiStore().write_page("primary", "experience/story-001.md", "# old render, no frontmatter\n")
    hand_edited = stories.story_to_page(
        CreatedStory(id="story-002", **{**_FIELDS, "impact": "hand edit"}), _TS
    )
    WikiStore().write_page("primary", "experience/story-002.md", hand_edited)
    written = stories.migrate_legacy_stories("primary")
    listed, _ = stories.list_stories("primary")
    actual = {
        "written": written,
        "impacts": [s.impact for s in listed],
        "migrated_records": sorted(
            r.message for r in caplog.records if r.message.startswith("story migrated:")
        ),
    }
    expected = {
        "written": 1,
        "impacts": ["Deploys daily.", "hand edit"],
        "migrated_records": ["story migrated: experience/story-001.md (Python, overwritten)"],
    }
    assert actual == expected


def test_migrate_is_a_noop_once_json_has_no_stories(wiki: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    assert stories.migrate_legacy_stories("primary") == 0


def test_migrate_skips_invalid_record_but_writes_valid_ones(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    path = _legacy_json(
        wiki,
        [
            {"id": "story-001", **_FIELDS},
            {"id": "story-002", "primary_skill": "Broken"},
        ],
    )
    written = stories.migrate_legacy_stories("primary")
    listed, _ = stories.list_stories("primary")
    actual = {
        "written": written,
        "ids": [s.id for s in listed],
        "warned_invalid_id": any("story-002" in r.message for r in caplog.records),
        "json_schema_version": json.loads(path.read_text())["schema_version"],
        "json_has_stories": "created_stories" in json.loads(path.read_text()),
    }
    expected = {
        "written": 1,
        "ids": ["story-001"],
        "warned_invalid_id": True,
        "json_schema_version": "1",
        "json_has_stories": True,
    }
    assert actual == expected


def test_migrate_keeps_json_when_read_back_fails(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    path = _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    monkeypatch.setattr(stories, "list_stories", lambda label: ([], []))
    written = stories.migrate_legacy_stories("primary")
    actual = {
        "written": written,
        "page_written": (wiki / "primary" / "experience" / "story-001.md").is_file(),
        "warned_kept": any("kept in accomplishments.json" in r.message for r in caplog.records),
        "json_intact": json.loads(path.read_text()),
    }
    expected = {
        "written": 1,
        "page_written": True,
        "warned_kept": True,
        "json_intact": {
            "schema_version": "1",
            "onboard_text": "notes",
            "created_stories": [{"id": "story-001", **_FIELDS}],
        },
    }
    assert actual == expected


def test_migrate_refuses_when_no_resume_registered(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    monkeypatch.setattr("callback.repository.stories.list_resumes", lambda: [])
    path = _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    written = stories.migrate_legacy_stories("primary")
    actual = {
        "written": written,
        "page_written": (wiki / "primary" / "experience" / "story-001.md").is_file(),
        "warned_no_resume": any("no resume registered" in r.message for r in caplog.records),
        "json_intact": json.loads(path.read_text()),
    }
    expected = {
        "written": 0,
        "page_written": False,
        "warned_no_resume": True,
        "json_intact": {
            "schema_version": "1",
            "onboard_text": "notes",
            "created_stories": [{"id": "story-001", **_FIELDS}],
        },
    }
    assert actual == expected


def test_migrate_drops_empty_legacy_key_without_resume_check(wiki: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    monkeypatch.setattr("callback.repository.stories.list_resumes", lambda: [])
    path = _legacy_json(wiki, [])
    written = stories.migrate_legacy_stories("primary")
    actual = {"written": written, "json": json.loads(path.read_text())}
    expected = {"written": 0, "json": {"schema_version": "2", "onboard_text": "notes"}}
    assert actual == expected


def test_migrate_leaves_a_crlf_bom_page_with_frontmatter_alone(wiki: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    hand_edited = stories.story_to_page(
        CreatedStory(id="story-001", **{**_FIELDS, "impact": "hand edit"}), _TS
    )
    crlf = "\ufeff" + hand_edited.replace("\n", "\r\n")
    WikiStore().write_page("primary", "experience/story-001.md", crlf)
    written = stories.migrate_legacy_stories("primary")
    listed, _ = stories.list_stories("primary")
    actual = {
        "written": written,
        "impact": listed[0].impact,
        "json_dropped": not AccomplishmentsStore().legacy_stories(),
    }
    expected = {"written": 0, "impact": "hand edit", "json_dropped": True}
    assert actual == expected


def test_migrate_leaves_a_malformed_page_alone_and_keeps_json(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    WikiStore().write_page(
        "primary", "experience/story-001.md", "---\ntype: story\n# no closing fence\n"
    )
    written = stories.migrate_legacy_stories("primary")
    page = WikiStore().read_pages("primary", ["experience/story-001.md"])["experience/story-001.md"]
    actual = {
        "written": written,
        "page_untouched": page == "---\ntype: story\n# no closing fence\n",
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
        "warned": any("malformed fence" in r.message for r in caplog.records),
    }
    expected = {"written": 0, "page_untouched": True, "json_kept": 1, "warned": True}
    assert actual == expected


def test_save_story_strips_body_whitespace_so_a_retry_is_identical(wiki: Path):
    padded = CreatedStory(
        id="", **{**_FIELDS, "situation": "  We had no CI.\n", "impact": "Deploys daily.  "}
    )
    first = stories.save_story("primary", padded)
    second = stories.save_story("primary", padded)
    files = sorted(p.name for p in (wiki / "primary" / "experience").iterdir())
    actual = {"same": first == second, "files": files, "situation": first.situation}
    expected = {"same": True, "files": ["story-001.md"], "situation": "We had no CI."}
    assert actual == expected


def test_list_stories_skips_a_non_utf8_page_and_keeps_the_rest(wiki: Path, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    bad = wiki / "primary" / "experience" / "story-002.md"
    bad.write_bytes("---\ntype: story\ntitle: caf\xe9\n---\n# x\n".encode("latin-1"))
    listed, warnings = stories.list_stories("primary")
    actual = {
        "ids": [s.id for s in listed],
        "warned": any("story-002.md" in w and "UTF-8" in w for w in warnings),
        "logged": any("story-002.md" in r.message for r in caplog.records),
    }
    expected = {"ids": ["story-001"], "warned": True, "logged": True}
    assert actual == expected


def test_story_to_page_rejects_a_structural_label_line_inside_a_field():
    story = CreatedStory(id="story-001", **{**_FIELDS, "situation": "line one\n**Impact:** hijack"})
    with pytest.raises(ValueError) as exc_info:
        stories.story_to_page(story, _TS)
    assert "situation" in str(exc_info.value)


def test_migrate_skips_a_record_with_a_label_line_and_keeps_json(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    bad = {"id": "story-001", **{**_FIELDS, "behavior": "did x\n**Impact:** nested"}}
    _legacy_json(wiki, [bad, {"id": "story-002", **_FIELDS}])
    written = stories.migrate_legacy_stories("primary")
    listed, _ = stories.list_stories("primary")
    actual = {
        "written": written,
        "ids": [s.id for s in listed],
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
        "warned": any(
            "story-001" in r.message and "structural label" in r.message for r in caplog.records
        ),
    }
    expected = {"written": 1, "ids": ["story-002"], "json_kept": 2, "warned": True}
    assert actual == expected


def test_migrate_keeps_json_when_a_written_page_reads_back_differently(
    wiki: Path, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    altered = CreatedStory(id="story-001", **{**_FIELDS, "impact": "something else"})
    monkeypatch.setattr(stories, "list_stories", lambda label: ([altered], []))
    written = stories.migrate_legacy_stories("primary")
    actual = {
        "written": written,
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
        "warned": any("read back differently" in r.message for r in caplog.records),
    }
    expected = {"written": 1, "json_kept": 1, "warned": True}
    assert actual == expected


def test_story_from_page_warns_when_type_disagrees_with_job_title(caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    page = stories.story_to_page(
        CreatedStory(id="story-001", **{**_FIELDS, "job_title": "Project"}), _TS
    )
    stale = page.replace("type: project", "type: story", 1)
    story = stories.story_from_page("experience/story-001.md", stale)
    actual = {
        "job_title": story.job_title,
        "warned": any("disagrees" in r.message for r in caplog.records),
    }
    expected = {"job_title": "Project", "warned": True}
    assert actual == expected


def test_migrate_leaves_an_empty_frontmatter_page_alone(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    WikiStore().write_page(
        "primary", "experience/story-001.md", "---\n---\n# hand edit in progress\n"
    )
    written = stories.migrate_legacy_stories("primary")
    page = WikiStore().read_pages("primary", ["experience/story-001.md"])["experience/story-001.md"]
    actual = {
        "written": written,
        "page_untouched": page == "---\n---\n# hand edit in progress\n",
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
    }
    expected = {"written": 0, "page_untouched": True, "json_kept": 1}
    assert actual == expected


def test_migrate_leaves_a_non_utf8_page_alone_and_keeps_json(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "story-001", **_FIELDS}])
    bad = wiki / "primary" / "experience" / "story-001.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    raw = "---\ntype: story\ntitle: caf\xe9\n---\n# x\n".encode("latin-1")
    bad.write_bytes(raw)
    written = stories.migrate_legacy_stories("primary")
    actual = {
        "written": written,
        "bytes_untouched": bad.read_bytes() == raw,
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
        "warned": any("story-001.md" in r.message and "UTF-8" in r.message for r in caplog.records),
    }
    expected = {"written": 0, "bytes_untouched": True, "json_kept": 1, "warned": True}
    assert actual == expected


def test_next_story_id_reserves_ids_still_held_in_legacy_json(wiki: Path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    invalid = {"id": "story-005", "primary_skill": "Broken"}  # fails validation, so never migrated
    _legacy_json(wiki, [invalid])
    saved = stories.save_story("primary", CreatedStory(id="", **_FIELDS))
    files = sorted(p.name for p in (wiki / "primary" / "experience").iterdir())
    actual = {"id": saved.id, "files": files}
    expected = {"id": "story-006", "files": ["story-006.md"]}
    assert actual == expected


@pytest.mark.parametrize("raw", ["tags: {}", "tags: ''", "tags: 0", "tags: false"])
def test_story_from_page_rejects_falsy_non_list_tags(raw: str):
    page = f"---\ntype: story\ntitle: X\n{raw}\n---\n# X\n\n**Situation:** s\n"
    with pytest.raises(WikiPageError) as exc_info:
        stories.story_from_page("experience/story-001.md", page)
    assert "tags must be a list" in str(exc_info.value)


def test_story_from_page_treats_absent_or_null_tags_as_empty():
    absent = stories.story_from_page("experience/story-001.md", "---\ntype: story\n---\n# X\n")
    null = stories.story_from_page("experience/story-002.md", "---\ntype: story\ntags:\n---\n# X\n")
    actual = {"absent": absent.skills, "null": null.skills}
    expected = {"absent": [], "null": []}
    assert actual == expected


def test_story_from_page_reads_null_scalars_as_empty_strings():
    page = "---\ntype: story\ntitle:\njob_title: null\nstory_type:\n---\n# X\n\n**Situation:** s\n"
    story = stories.story_from_page("experience/story-001.md", page)
    actual = {"skill": story.primary_skill, "job": story.job_title, "type": story.story_type}
    expected = {"skill": "", "job": "", "type": ""}
    assert actual == expected


def test_migrate_skips_a_record_whose_id_is_not_story_nnn(wiki: Path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="callback.repository.stories")
    monkeypatch.setenv("XDG_DATA_HOME", str(wiki))
    _with_registered_resume(monkeypatch)
    _legacy_json(wiki, [{"id": "../evil", **_FIELDS}, {"id": "story-002", **_FIELDS}])
    written = stories.migrate_legacy_stories("primary")
    outside = (wiki / "primary" / "evil.md").exists() or (wiki / "evil.md").exists()
    actual = {
        "written": written,
        "outside_written": outside,
        "json_kept": len(AccomplishmentsStore().legacy_stories()),
        "warned": any("../evil" in r.message and "story-NNN" in r.message for r in caplog.records),
    }
    expected = {"written": 1, "outside_written": False, "json_kept": 2, "warned": True}
    assert actual == expected
