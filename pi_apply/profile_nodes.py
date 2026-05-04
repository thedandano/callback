"""Profile graph node implementations.

Stub implementations of profile graph nodes. Each node logs entry and returns
sentinel values as placeholders. In real implementations, these will:
- onboard: collect user resume, skills, and accomplishment data
- compile_profile: compute the compiled profile record from user data
- create_story: extract behavioral stories for orphaned skills
"""

import json
import logging
from pathlib import Path

from pi_apply import extractor
from pi_apply import wiki as wiki_module
from pi_apply.state import ProfileState

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
    """Onboard a new user by extracting sections from their resume file.

    Reads state.resume_path, extracts text and section structure, writes
    sections.json to the profile-wiki directory, and returns updated state fields.

    Returns:
        dict with resume_label, sections (serialized SectionMap), and wiki_path
    Raises:
        ValueError: if resume_path is missing or the file does not exist
    """
    _log_enter("onboard", state)
    if not state.resume_path or not Path(state.resume_path).exists():
        raise ValueError("resume_path required for onboarding")

    text = extractor.extract(state.resume_path)
    section_map = extractor.extract_sections(text)
    resume_label = Path(state.resume_path).stem

    wiki_dir = wiki_module.BASE_DIR / resume_label
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "sections.json").write_text(json.dumps(section_map.model_dump()), encoding="utf-8")

    return {
        "resume_label": resume_label,
        "sections": section_map.model_dump(),
        "wiki_path": str(wiki_dir),
    }


def compile_profile(state: ProfileState) -> dict:
    """Return sections and intake for host to generate wiki pages.

    Single-phase node: returns data needed for host LLM to produce wiki
    markdown pages. Wiki writing happens in the MCP tool layer (server.py),
    not here. No LLM calls are made in this node.

    Returns:
        dict with compiled_profile status and sections/intake data
    """
    _log_enter("compile_profile", state)
    return {
        "compiled_profile": {
            "status": "needs_wiki_pages",
            "sections": state.sections,
            "intake": state.intake,
            "resume_label": state.resume_label,
        }
    }


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
