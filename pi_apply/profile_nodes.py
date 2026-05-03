"""Profile graph node implementations.

Stub implementations of profile graph nodes. Each node logs entry and returns
sentinel values as placeholders. In real implementations, these will:
- onboard: collect user resume, skills, and accomplishment data
- compile_profile: compute the compiled profile record from user data
- create_story: extract behavioral stories for orphaned skills
"""

import json
import logging

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
    """No-op stub: onboard a new user.

    Returns:
        dict with sentinel intake value
    """
    _log_enter("onboard", state)
    return {"intake": {"stub": "onboard"}}


def compile_profile(state: ProfileState) -> dict:
    """No-op stub: compile the profile.

    Returns:
        dict with sentinel compiled_profile value
    """
    _log_enter("compile_profile", state)
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
