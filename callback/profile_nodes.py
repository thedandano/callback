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
from callback.repository.resumes import list_resumes, replace_resume
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


def _registered_label(state_label: str | None) -> str:
    """Resolve the resume label to use for reading/writing wiki content.

    Uses the state's resume_label when set, else the first registered resume,
    else falls back to "default" (no resumes registered at all).
    """
    if state_label:
        return state_label
    registered = list_resumes()
    return registered[0] if registered else "default"


def _resume_skills(label: str) -> list[str]:
    """Return all skills from sections.json for the given resume label."""
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
    """A profile exists once a resume is registered — compiling (which creates the
    compiled profile) happens downstream, and check_orphans already tolerates a
    missing compiled profile.
    """
    _log_enter("check_profile", state)
    return {"profile_exists": len(list_resumes()) > 0}


@trace_node("profile", "onboard")
def onboard(state: ProfileState) -> dict:
    _log_enter("onboard", state)
    if not state.resume_path:
        return {"intake": {"status": "no_resume"}}

    label = "primary"
    text = extractor.extract(state.resume_path)
    section_map = extractor.extract_sections(text)

    replace_resume(label, state.resume_path)

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
    host_tags = list(state.host_tags or [])
    label = _registered_label(state.resume_label)
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


def _active_orphans_from_state(compiled_profile: dict) -> list[str] | None:
    """Derive active orphans from the thread's own compiled_profile state, if usable.

    Returns None when compiled_profile isn't the expected shape, so the caller
    falls back to the disk-loaded profile (a new thread that skipped compile).
    """
    orphaned = compiled_profile.get("orphaned_skills")
    if not isinstance(orphaned, list):
        return None
    return [o["skill"] for o in orphaned if isinstance(o, dict) and not o.get("deferred")]


@trace_node("profile", "check_orphans")
def check_orphans(state: ProfileState) -> dict:
    _log_enter("check_orphans", state)
    if isinstance(state.compiled_profile, dict):
        active = _active_orphans_from_state(state.compiled_profile)
        if active is not None:
            return {"orphaned_skills": active}
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
