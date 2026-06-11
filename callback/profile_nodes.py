"""Profile graph node implementations.

Each node logs entry and returns a dict update to the graph state. Nodes do
I/O only — no LLM/API calls. All inference is performed by the host (calling LLM).
"""

import json
import logging

import callback.extractor as extractor
from callback.observability import trace_node
from callback.profilecompiler import (
    ProfileCompiler,
    ProfileMissingError,
    load_compiled_profile,
    save_compiled_profile,
)
from callback.repository.accomplishments import AccomplishmentsStore
from callback.repository.resumes import clear_resumes, list_resumes, save_resume
from callback.section_map import SectionMap
from callback.state import CreatedStory, ProfileState
from callback.wiki import WikiStore
from callback.wikirenderer import WikiRenderer

logger = logging.getLogger(__name__)


def _log_enter(node: str, state: ProfileState) -> None:
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))


def _persist_onboard_text(intake: dict) -> None:
    if onboard_text := intake.get("onboard_text"):
        AccomplishmentsStore().save_onboard_text(onboard_text)


def _resume_skills(label: str) -> list[str]:
    """Return all skills from sections.json for the given resume label."""
    if label == "default":
        registered = list_resumes()
        if registered:
            label = registered[0]
    pages = WikiStore().read_pages(label, ["sections.json"])
    sections_json = pages.get("sections.json", "")
    if not sections_json:
        return []
    try:
        section_map = SectionMap.model_validate_json(sections_json)
    except Exception:
        return []
    skills: list[str] = list(section_map.skills.flat)
    for items in section_map.skills.categorized.values():
        skills.extend(items)
    return skills


def _render_wiki(label: str, profile) -> None:
    renderer = WikiRenderer()
    for story in profile.stories:
        renderer.render_experience_page(label, story)
    renderer.render_index(label, profile)


@trace_node("profile", "check_profile")
def check_profile(state: ProfileState) -> dict:
    _log_enter("check_profile", state)
    try:
        load_compiled_profile()
        has_resumes = len(list_resumes()) > 0
        return {"profile_exists": has_resumes}
    except ProfileMissingError:
        return {"profile_exists": False}


@trace_node("profile", "onboard")
def onboard(state: ProfileState) -> dict:
    _log_enter("onboard", state)
    if not state.resume_path:
        return {"intake": {"status": "no_resume"}}

    label = "primary"
    clear_resumes()
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


@trace_node("profile", "compile_profile")
def compile_profile(state: ProfileState) -> dict:
    _log_enter("compile_profile", state)
    stories = AccomplishmentsStore().list_stories()
    host_tags = (
        state.compiled_profile.get("host_tags", [])
        if isinstance(state.compiled_profile, dict)
        else []
    )
    label = state.resume_label or "default"
    resume_skills = _resume_skills(label)
    all_tags = list(dict.fromkeys(host_tags + resume_skills))
    profile, warnings = ProfileCompiler().compile(stories, all_tags)
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


@trace_node("profile", "check_orphans")
def check_orphans(state: ProfileState) -> dict:
    _log_enter("check_orphans", state)
    try:
        profile = load_compiled_profile()
        active = [o.skill for o in profile.orphaned_skills if not o.deferred]
        return {"orphaned_skills": active}
    except ProfileMissingError:
        return {"orphaned_skills": []}


@trace_node("profile", "create_story")
def create_story(state: ProfileState) -> dict:
    _log_enter("create_story", state)
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
    saved = AccomplishmentsStore().save_story(story)
    return {
        "current_story_target": saved.primary_skill,
        "intake": {**intake, "story_id": saved.id, "needs_compile": True},
    }
