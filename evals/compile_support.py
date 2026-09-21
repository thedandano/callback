"""Stage an E3 case into a throwaway data dir and run the real compile_profile node."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from callback.profile_nodes import compile_profile
from callback.state import ProfileState


def install_case(case_dir: Path, data_root: Path, label: str = "primary") -> Path:
    """Copy stories and sections.json under data_root/callback and register a resume."""
    wiki = data_root / "callback" / "profile-wiki" / label
    (wiki / "experience").mkdir(parents=True)
    for story in sorted((case_dir / "stories").glob("story-*.md")):
        shutil.copy(story, wiki / "experience" / story.name)
    shutil.copy(case_dir / "sections.json", wiki / "sections.json")
    inputs = data_root / "callback" / "inputs"
    inputs.mkdir(parents=True)
    (inputs / f"{label}.txt").write_text("eval resume placeholder", encoding="utf-8")
    return wiki


def compile_case(data_root: Path, label: str = "primary") -> dict:
    """Run the compile_profile node; XDG_DATA_HOME must already point at data_root."""
    env = os.environ.get("XDG_DATA_HOME")
    if env != str(data_root):
        raise ValueError(f"XDG_DATA_HOME is {env!r}, expected {data_root}")
    result = compile_profile(ProfileState(session_id="eval-compile", resume_label=label))
    return result["compiled_profile"]
