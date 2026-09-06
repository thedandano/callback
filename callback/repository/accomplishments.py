import json
from pathlib import Path

from callback import paths
from callback.state import CreatedStory


class StoryNotFoundError(Exception):
    pass


_SCHEMA_VERSION_MIGRATED = "2"


class AccomplishmentsStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else paths.data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "accomplishments.json"

    def _load(self) -> dict:
        file_path = self._file_path()
        if not file_path.exists():
            return {"schema_version": "1", "onboard_text": "", "created_stories": []}
        with open(file_path) as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        paths.write_json_atomic(self._file_path(), data)

    def save_story(self, story: CreatedStory) -> CreatedStory:
        """Persist a story. Saving a story identical to one already stored returns
        the stored one instead of appending a duplicate, so a retry after a
        failure that happened after the write is safe."""
        data = self._load()
        content = story.model_dump(exclude={"id"})
        for record in data["created_stories"]:
            if {k: v for k, v in record.items() if k != "id"} == content:
                return CreatedStory.model_validate(record)
        story_id = f"story-{len(data['created_stories']) + 1:03d}"
        story_with_id = story.model_copy(update={"id": story_id})
        data["created_stories"].append(story_with_id.model_dump())
        self._save(data)
        return story_with_id

    def get_story(self, id: str) -> CreatedStory:
        data = self._load()
        for record in data["created_stories"]:
            if record.get("id") == id:
                return CreatedStory.model_validate(record)
        raise StoryNotFoundError(f"Story {id} not found")

    def list_stories(self) -> list[CreatedStory]:
        data = self._load()
        return [CreatedStory.model_validate(r) for r in data["created_stories"]]

    def save_onboard_text(self, text: str) -> None:
        data = self._load()
        data["onboard_text"] = text
        self._save(data)

    def load_onboard_text(self) -> str:
        return self._load().get("onboard_text", "")

    def legacy_stories(self) -> list[dict]:
        """Stories still held in the JSON (schema 1). Empty once migrated."""
        return list(self._load().get("created_stories") or [])

    def drop_legacy_stories(self) -> None:
        data = self._load()
        data.pop("created_stories", None)
        data["schema_version"] = _SCHEMA_VERSION_MIGRATED
        self._save(data)
