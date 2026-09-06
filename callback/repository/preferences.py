import json
from pathlib import Path

from callback import paths
from callback.preferences import SearchPreferences


class PreferencesStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else paths.data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "preferences.json"

    def load(self) -> SearchPreferences | None:
        file_path = self._file_path()
        if not file_path.exists():
            return None
        with open(file_path) as f:
            return SearchPreferences.model_validate(json.load(f))

    def save(self, prefs: SearchPreferences) -> None:
        paths.write_json_atomic(self._file_path(), prefs.model_dump())
