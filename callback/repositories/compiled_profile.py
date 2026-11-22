"""Read and write compiled_profile.json under the data folder."""

from __future__ import annotations

import json
from pathlib import Path

from callback.config import paths
from callback.models.profile import CompiledProfile
from callback.repositories.atomic import write_json_atomic

_COMPILED_PROFILE_FILE = "compiled_profile.json"


class ProfileMissingError(Exception):
    pass


def save_compiled_profile(profile: CompiledProfile, base_dir: Path | None = None) -> None:
    target_dir = base_dir if base_dir is not None else paths.data_dir()
    write_json_atomic(target_dir / _COMPILED_PROFILE_FILE, profile.model_dump())


def load_compiled_profile(base_dir: Path | None = None) -> CompiledProfile:
    target_dir = base_dir if base_dir is not None else paths.data_dir()
    file_path = target_dir / _COMPILED_PROFILE_FILE
    if not file_path.exists():
        raise ProfileMissingError(f"No compiled profile at {file_path}")
    with open(file_path) as f:
        return CompiledProfile.model_validate(json.load(f))
