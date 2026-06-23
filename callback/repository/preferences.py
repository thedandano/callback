import json
import os
from pathlib import Path

from callback.preferences import SearchPreferences


def data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "callback"
    return Path.home() / ".local" / "share" / "callback"


class PreferencesStore:
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir if base_dir is not None else data_dir()

    def _file_path(self) -> Path:
        return self._base_dir / "preferences.json"

    def load(self) -> SearchPreferences | None:
        file_path = self._file_path()
        if not file_path.exists():
            return None
        with open(file_path) as f:
            return SearchPreferences.model_validate(json.load(f))

    def save(self, prefs: SearchPreferences) -> None:
        file_path = self._file_path()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(prefs.model_dump(), f)
        os.replace(tmp_path, file_path)
