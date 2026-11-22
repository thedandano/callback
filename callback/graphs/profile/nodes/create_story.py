"""Profile node: persist one behavioral story."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.graphs.profile.registered_label import registered_label
from callback.models.profile import CreatedStory
from callback.models.state import ProfileState
from callback.repositories import stories, story_migration

logger = logging.getLogger("callback.profile_nodes")


@trace_node("profile", "create_story")
def create_story(state: ProfileState) -> dict:
    log_enter(logger, "create_story", state)
    intake = state.intake or {}
    primary_skill = intake.get("primary_skill") or state.current_story_target
    if not primary_skill:
        raise ValueError("primary_skill is required in intake or via current_story_target")
    story = CreatedStory(
        id="",
        primary_skill=primary_skill,
        skills=intake.get("skills", []),
        story_type=intake.get("story_type", "STAR"),
        job_title=intake.get("job_title", ""),
        situation=intake.get("situation", ""),
        behavior=intake.get("behavior", ""),
        impact=intake.get("impact", ""),
    )
    label = registered_label(state.resume_label)
    story_migration.migrate_legacy_stories(label)  # before next_story_id can claim a legacy id
    saved = stories.save_story(label, story)
    return {
        "current_story_target": saved.primary_skill,
        "intake": {**intake, "story_id": saved.id, "needs_compile": True},
    }
