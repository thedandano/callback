import json
import os
from datetime import UTC, datetime
from pathlib import Path

from rapidfuzz import fuzz

from pi_apply.state import CompiledProfile, CreatedStory, OrphanedSkill

_SCHEMA_VERSION = "1"
_COMPILED_PROFILE_FILE = "compiled_profile.json"
_FUZZY_THRESHOLD = 80


class ProfileMissingError(Exception):
    pass


def _data_dir() -> Path:
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "pi-apply"
    return Path.home() / ".local" / "share" / "pi-apply"


def _insert_skills(seen: dict[str, str], skills: list[str]) -> None:
    for skill in skills:
        if (key := skill.lower()) not in seen:
            seen[key] = skill


def _build_skills_index(stories: list[CreatedStory], host_tags: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    _insert_skills(seen, [s.primary_skill for s in stories])
    _insert_skills(seen, [skill for s in stories for skill in s.skills])
    _insert_skills(seen, host_tags)
    return sorted(seen.values(), key=str.lower)


def _covered_skills_set(stories: list[CreatedStory]) -> set[str]:
    covered: set[str] = set()
    for story in stories:
        covered.add(story.primary_skill.lower())
        covered.update(s.lower() for s in story.skills)
    return covered


def _detect_orphans(host_tags: list[str], covered: set[str]) -> list[OrphanedSkill]:
    return [OrphanedSkill(skill=tag) for tag in host_tags if tag.lower() not in covered]


def _lint_story_coverage(story: CreatedStory) -> str | None:
    primary = story.primary_skill
    if primary.lower() in {s.lower() for s in story.skills}:
        return None
    if not story.skills:
        return f"{story.id}: primary_skill {primary!r} not found in skills (best match: none at 0%)"
    best_skill, best_score = max(
        ((s, fuzz.token_sort_ratio(primary, s)) for s in story.skills),
        key=lambda pair: pair[1],
    )
    if int(best_score) < _FUZZY_THRESHOLD:
        return (
            f"{story.id}: primary_skill {primary!r} not found in skills"
            f" (best match: {best_skill!r} at {int(best_score)}%)"
        )
    return None


def _lint_coverage(stories: list[CreatedStory]) -> list[str]:
    return [w for story in stories if (w := _lint_story_coverage(story)) is not None]


class ProfileCompiler:
    def compile(
        self,
        stories: list[CreatedStory],
        host_tags: list[str],
    ) -> tuple[CompiledProfile, list[str]]:
        skills_index = _build_skills_index(stories, host_tags)
        covered = _covered_skills_set(stories)
        orphaned = _detect_orphans(host_tags, covered)
        warnings = _lint_coverage(stories)
        profile = CompiledProfile(
            schema_version=_SCHEMA_VERSION,
            skills_index=skills_index,
            stories=list(stories),
            orphaned_skills=orphaned,
            compiled_at=datetime.now(UTC).isoformat(),
        )
        return profile, warnings


def save_compiled_profile(profile: CompiledProfile, base_dir: Path | None = None) -> None:
    target_dir = base_dir if base_dir is not None else _data_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / _COMPILED_PROFILE_FILE
    tmp_path = file_path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(profile.model_dump(), f)
    os.replace(tmp_path, file_path)


def load_compiled_profile(base_dir: Path | None = None) -> CompiledProfile:
    target_dir = base_dir if base_dir is not None else _data_dir()
    file_path = target_dir / _COMPILED_PROFILE_FILE
    if not file_path.exists():
        raise ProfileMissingError(f"No compiled profile at {file_path}")
    with open(file_path) as f:
        return CompiledProfile.model_validate(json.load(f))
