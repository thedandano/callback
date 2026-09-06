import json
from pathlib import Path

from callback import paths

_SCHEMA_VERSION_MIGRATED = "2"


class AccomplishmentsStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else paths.data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "accomplishments.json"

    def _load(self) -> dict:
        file_path = self._file_path()
        if not file_path.exists():
            return {"schema_version": "2", "onboard_text": ""}
        with open(file_path) as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        paths.write_json_atomic(self._file_path(), data)

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
