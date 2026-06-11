import json
import os
from pathlib import Path

from callback.state import CreatedStory


class StoryNotFoundError(Exception):
    pass


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


class AccomplishmentsStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "accomplishments.json"

    def _load(self) -> dict:
        file_path = self._file_path()
        if not file_path.exists():
            return {"schema_version": "1", "onboard_text": "", "created_stories": []}
        with open(file_path) as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        file_path = self._file_path()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, file_path)

    def save_story(self, story: CreatedStory) -> CreatedStory:
        data = self._load()
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
