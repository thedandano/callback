"""Unit tests for callback.repository.accomplishments."""

import json

from callback.repository.accomplishments import AccomplishmentsStore

_STORY_FIELDS = dict(
    primary_skill="Kubernetes",
    skills=["Kubernetes", "Helm"],
    story_type="technical",
    job_title="Platform Engineer",
    situation="Legacy infra had no container orchestration.",
    behavior="Migrated 12 services to k8s.",
    impact="Reduced deploy time by 60%.",
)


def test_onboard_text_round_trips(tmp_path):
    store = AccomplishmentsStore(base_dir=tmp_path)
    store.save_onboard_text("raw notes")
    actual = {
        "text": store.load_onboard_text(),
        "json": json.loads((tmp_path / "accomplishments.json").read_text()),
    }
    expected = {
        "text": "raw notes",
        "json": {"schema_version": "2", "onboard_text": "raw notes"},
    }
    assert actual == expected


def test_missing_file_reads_as_empty_text_and_no_legacy_stories(tmp_path):
    store = AccomplishmentsStore(base_dir=tmp_path)
    actual = {"text": store.load_onboard_text(), "legacy": store.legacy_stories()}
    expected = {"text": "", "legacy": []}
    assert actual == expected


def test_legacy_stories_are_read_then_dropped(tmp_path):
    legacy = {
        "schema_version": "1",
        "onboard_text": "keep me",
        "created_stories": [{"id": "story-001", **_STORY_FIELDS}],
    }
    (tmp_path / "accomplishments.json").write_text(json.dumps(legacy))
    store = AccomplishmentsStore(base_dir=tmp_path)
    before = store.legacy_stories()
    store.drop_legacy_stories()
    actual = {
        "before": before,
        "after": store.legacy_stories(),
        "json": json.loads((tmp_path / "accomplishments.json").read_text()),
    }
    expected = {
        "before": [{"id": "story-001", **_STORY_FIELDS}],
        "after": [],
        "json": {"schema_version": "2", "onboard_text": "keep me"},
    }
    assert actual == expected
