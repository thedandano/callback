"""Profile graph node implementations.

Each node logs entry and returns a dict update to the graph state. Nodes do
I/O only — no LLM/API calls. All inference is performed by the host (calling LLM).
"""

import json
import logging
from pathlib import Path

import pi_apply.extractor as extractor
from pi_apply.profilecompiler import (
    ProfileCompiler,
    ProfileMissingError,
    load_compiled_profile,
    save_compiled_profile,
)
from pi_apply.repository.accomplishments import AccomplishmentsStore
from pi_apply.repository.resumes import list_resumes, save_resume
from pi_apply.state import CreatedStory, ProfileState
from pi_apply.wiki import WikiStore
from pi_apply.wikirenderer import WikiRenderer

logger = logging.getLogger(__name__)


def _log_enter(node: str, state: ProfileState) -> None:
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))


def _persist_onboard_text(intake: dict) -> None:
    if onboard_text := intake.get("onboard_text"):
        AccomplishmentsStore().save_onboard_text(onboard_text)


def _render_wiki(label: str, profile) -> None:
    renderer = WikiRenderer()
    for story in profile.stories:
        renderer.render_experience_page(label, story)
    renderer.render_index(label, profile)


def check_profile(state: ProfileState) -> dict:
    _log_enter("check_profile", state)
    try:
        load_compiled_profile()
        has_resumes = len(list_resumes()) > 0
        return {"profile_exists": has_resumes}
    except ProfileMissingError:
        return {"profile_exists": False}


def onboard(state: ProfileState) -> dict:
    _log_enter("onboard", state)
    if not state.resume_path:
        return {"intake": {"status": "no_resume"}}

    label = Path(state.resume_path).stem
    save_resume(label, state.resume_path)
    text = extractor.extract(state.resume_path)
    section_map = extractor.extract_sections(text)

    intake = state.intake or {}
    _persist_onboard_text(intake)
    WikiStore().write_page(label, "sections.json", section_map.model_dump_json())

    stories = AccomplishmentsStore().list_stories()
    return {
        "resume_label": label,
        "resume_path": state.resume_path,
        "sections": section_map.model_dump(),
        "intake": {
            "status": "onboarded",
            "resume_label": label,
            "stories": [s.model_dump() for s in stories],
        },
    }


def compile_profile(state: ProfileState) -> dict:
    _log_enter("compile_profile", state)
    stories = AccomplishmentsStore().list_stories()
    host_tags = (
        state.compiled_profile.get("host_tags", [])
        if isinstance(state.compiled_profile, dict)
        else []
    )
    profile, warnings = ProfileCompiler().compile(stories, host_tags)

    label = state.resume_label or "default"
    _render_wiki(label, profile)
    save_compiled_profile(profile)

    return {
        "compiled_profile": profile.model_dump(),
        "intake": {
            **(state.intake or {}),
            "skill_coverage_warnings": warnings,
            "skills_index": profile.skills_index,
        },
    }


def check_orphans(state: ProfileState) -> dict:
    _log_enter("check_orphans", state)
    try:
        profile = load_compiled_profile()
        active = [o.skill for o in profile.orphaned_skills if not o.deferred]
        return {"orphaned_skills": active}
    except ProfileMissingError:
        return {"orphaned_skills": []}


def create_story(state: ProfileState) -> dict:
    _log_enter("create_story", state)
    intake = state.intake or {}
    story = CreatedStory(
        id="",
        primary_skill=intake.get("primary_skill", state.current_story_target or ""),
        skills=intake.get("skills", []),
        story_type=intake.get("story_type", "STAR"),
        job_title=intake.get("job_title", ""),
        situation=intake.get("situation", ""),
        behavior=intake.get("behavior", ""),
        impact=intake.get("impact", ""),
    )
    saved = AccomplishmentsStore().save_story(story)
    return {
        "current_story_target": saved.primary_skill,
        "intake": {**intake, "story_id": saved.id, "needs_compile": True},
    }
