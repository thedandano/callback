"""Unit tests for pi_apply.repository.accomplishments."""

import json

import pytest

from pi_apply.repository.accomplishments import (
    AccomplishmentsStore,
    StoryNotFoundError,
)
from pi_apply.state import CreatedStory


def _make_story(**overrides) -> CreatedStory:
    """Helper to build a story with sensible defaults."""
    defaults = dict(
        id="",  # will be assigned by save_story
        primary_skill="Kubernetes",
        skills=["Kubernetes", "Helm"],
        story_type="technical",
        job_title="Platform Engineer",
        situation="Legacy infra had no container orchestration.",
        behavior="Migrated 12 services to k8s.",
        impact="Reduced deploy time by 60%.",
    )
    return CreatedStory(**{**defaults, **overrides})


class TestSaveGetRoundTrip:
    """Test saving and retrieving stories."""

    def test_save_and_get_story(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story = _make_story()

        saved = store.save_story(story)
        retrieved = store.get_story(saved.id)

        assert retrieved == saved


class TestFirstStoryGetsStory001:
    """Test that the first story gets ID story-001."""

    def test_first_story_id(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story = _make_story()

        saved = store.save_story(story)

        assert saved.id == "story-001"


class TestSequentialIDs:
    """Test that stories get sequential IDs."""

    def test_two_stories_get_sequential_ids(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story1 = _make_story(primary_skill="Python")
        story2 = _make_story(primary_skill="Go")

        saved1 = store.save_story(story1)
        saved2 = store.save_story(story2)

        assert (saved1.id, saved2.id) == ("story-001", "story-002")


class TestListAll:
    """Test listing all stories."""

    def test_list_three_stories(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story1 = _make_story(
            primary_skill="Python",
            job_title="Backend Engineer",
        )
        story2 = _make_story(
            primary_skill="Go",
            job_title="Platform Engineer",
        )
        story3 = _make_story(
            primary_skill="Rust",
            job_title="Systems Engineer",
        )

        saved1 = store.save_story(story1)
        saved2 = store.save_story(story2)
        saved3 = store.save_story(story3)

        all_stories = store.list_stories()

        assert len(all_stories) == 3
        assert all_stories == [saved1, saved2, saved3]


class TestGetMissingRaises:
    """Test that getting a missing story raises."""

    def test_get_missing_story_raises(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)

        with pytest.raises(StoryNotFoundError, match="Story story-999 not found"):
            store.get_story("story-999")


class TestSchemaVersionField:
    """Test that the raw JSON file has schema_version field."""

    def test_schema_version_in_json(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story = _make_story()

        store.save_story(story)

        file_path = tmp_path / "accomplishments.json"
        with open(file_path) as f:
            data = json.load(f)

        assert data["schema_version"] == "1"


class TestAtomicWrite:
    """Test that the file is valid JSON after save."""

    def test_file_is_valid_json_after_save(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story = _make_story()

        store.save_story(story)

        file_path = tmp_path / "accomplishments.json"
        with open(file_path) as f:
            data = json.load(f)

        assert isinstance(data, dict)
        assert "schema_version" in data
        assert "created_stories" in data
        assert "onboard_text" in data


class TestOnboardTextPreserved:
    """Test that saving onboard text doesn't lose stories."""

    def test_onboard_text_preserved_with_stories(self, tmp_path):
        store = AccomplishmentsStore(base_dir=tmp_path)
        story1 = _make_story(primary_skill="Python")
        story2 = _make_story(primary_skill="Go")

        saved1 = store.save_story(story1)
        saved2 = store.save_story(story2)
        store.save_onboard_text("some text")

        all_stories = store.list_stories()

        assert len(all_stories) == 2
        assert all_stories == [saved1, saved2]

        file_path = tmp_path / "accomplishments.json"
        with open(file_path) as f:
            data = json.load(f)

        assert data["onboard_text"] == "some text"
