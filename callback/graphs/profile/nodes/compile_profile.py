"""Profile node: recompile the profile from stories and resume skills."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.graphs.profile.registered_label import registered_label
from callback.models.section_map import SectionMap
from callback.models.state import ProfileState
from callback.repositories import stories, story_migration
from callback.repositories.compiled_profile import (
    save_compiled_profile,
)
from callback.repositories.wiki import WikiStore
from callback.services.profilecompiler import compile_profile as build_profile
from callback.services.wikirenderer import render_index

logger = logging.getLogger("callback.profile_nodes")


def _resume_skills(label: str) -> list[str]:
    """Return all skills from sections.json for the given resume label."""
    pages = WikiStore().read_pages(label, ["sections.json"])
    sections_json = pages.get("sections.json", "")
    if not sections_json:
        return []
    try:
        # ValidationError (invalid JSON or schema) is a ValueError subclass, so
        # catching ValueError alone covers both failure modes.
        section_map = SectionMap.model_validate_json(sections_json)
    except ValueError as exc:
        logger.warning("resume skills unavailable for %s: %s: %s", label, type(exc).__name__, exc)
        return []
    return section_map.skills.all_skills()


@trace_node("profile", "compile_profile")
def compile_profile(state: ProfileState) -> dict:
    log_enter(logger, "compile_profile", state)
    label = registered_label(state.resume_label)
    story_migration.migrate_legacy_stories(label)
    story_list, page_warnings = stories.list_stories(label)
    host_tags = list(state.host_tags or [])
    resume_skills = _resume_skills(label)
    all_tags = list(dict.fromkeys(host_tags + resume_skills))
    profile, lint_warnings = build_profile(story_list, all_tags)
    render_index(label, profile)
    save_compiled_profile(profile)

    return {
        "compiled_profile": profile.model_dump(),
        "intake": {
            **(state.intake or {}),
            "skill_coverage_warnings": [*page_warnings, *lint_warnings],
            "skills_index": profile.skills_index,
        },
    }
