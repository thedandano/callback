"""Profile graph node implementations.

Each node logs entry and returns a dict update to the graph state. Nodes do
I/O only — no LLM/API calls. All inference is performed by the host (calling LLM).
"""

import json
import logging
from pathlib import Path

import pi_apply.extractor as extractor
from pi_apply.state import ProfileState
from pi_apply.wiki import WikiStore

logger = logging.getLogger(__name__)


def _log_enter(node: str, state: ProfileState) -> None:
    """Log entry to a node with structured JSON."""
    present = [k for k, v in state.model_dump().items() if v is not None]
    logger.info(json.dumps({"node": node, "session_id": state.session_id, "input_fields": present}))


def check_profile(state: ProfileState) -> dict:
    """Router node: check if profile exists.

    Logs entry but does not modify state. Returns empty dict.
    The conditional edge reads this node's result and routes.

    Returns:
        Empty dict (router nodes don't write state)
    """
    _log_enter("check_profile", state)
    return {}


def onboard(state: ProfileState) -> dict:
    """Extract resume sections and persist sections.json to the profile wiki.

    Returns:
        dict with resume_label, sections, and intake status.
        If no resume_path is set, returns no_resume status and no-ops.
    """
    _log_enter("onboard", state)
    if not state.resume_path:
        return {"intake": {"status": "no_resume"}}

    resume_label = Path(state.resume_path).stem
    text = extractor.extract(state.resume_path)
    section_map = extractor.extract_sections(text)

    store = WikiStore()
    store.write_page(resume_label, "sections.json", section_map.model_dump_json())

    return {
        "resume_label": resume_label,
        "sections": section_map.model_dump(),
        "intake": {"status": "onboarded", "resume_label": resume_label},
    }


def compile_profile(state: ProfileState) -> dict:
    """Phase 1: return sections and intake for host to generate wiki pages.

    The host (calling LLM) uses the returned sections to generate wiki markdown.
    Wiki writes are handled by the MCP tool in server.py.

    Returns:
        dict with compiled_profile placeholder.
        Does not touch orphaned_skills — managed exclusively by create_story.
    """
    _log_enter("compile_profile", state)
    logger.info(json.dumps({"node": "compile_profile", "session_id": state.session_id, "phase": 1}))
    return {"compiled_profile": {"stub": True}}


def check_orphans(state: ProfileState) -> dict:
    """Router node: check if orphaned skills remain.

    Logs entry but does not modify state. Returns empty dict.
    The conditional edge reads this node's result and routes.

    Returns:
        Empty dict (router nodes don't write state)
    """
    _log_enter("check_orphans", state)
    return {}


def create_story(state: ProfileState) -> dict:
    """No-op stub: create a story for one orphaned skill.

    Drains one skill from orphaned_skills to make the cycle terminate.
    In real implementation, this collects SBI story details from the user.
    The stub removes one orphan per invocation to ensure the cycle ends.

    Returns:
        dict with updated orphaned_skills list and current_story_target
    """
    _log_enter("create_story", state)
    # Drain one orphan from the list to enable cycle termination
    orphans = state.orphaned_skills or []
    if not orphans:
        return {"orphaned_skills": [], "current_story_target": None}
    # Pop first orphan and return the shortened list
    current_target = orphans[0]
    remaining = orphans[1:]
    return {"orphaned_skills": remaining, "current_story_target": current_target}
