"""Profile node: register the resume and persist its sections."""

import logging

import callback.services.extractor as extractor
from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ProfileState
from callback.repositories import stories, story_migration
from callback.repositories.accomplishments import AccomplishmentsStore
from callback.repositories.resumes import replace_resume
from callback.repositories.wiki import WikiStore

logger = logging.getLogger("callback.profile_nodes")


def _persist_onboard_text(intake: dict) -> None:
    if onboard_text := intake.get("onboard_text"):
        AccomplishmentsStore().save_onboard_text(onboard_text)


@trace_node("profile", "onboard")
def onboard(state: ProfileState) -> dict:
    log_enter(logger, "onboard", state)
    if not state.resume_path:
        return {"intake": {"status": "no_resume"}}

    label = "primary"
    text = extractor.extract(state.resume_path)
    section_map = extractor.extract_sections(text)

    replace_resume(label, state.resume_path)

    intake = state.intake or {}
    _persist_onboard_text(intake)
    WikiStore().write_page(label, "sections.json", section_map.model_dump_json())
    story_migration.migrate_legacy_stories(label)

    story_list, _ = stories.list_stories(label)
    return {
        "resume_label": label,
        "resume_path": state.resume_path,
        "sections": section_map.model_dump(),
        "intake": {
            "status": "onboarded",
            "resume_label": label,
            "stories": [s.model_dump() for s in story_list],
        },
    }
