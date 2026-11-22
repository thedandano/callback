"""Profile node: list skills that still lack a story."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ProfileState
from callback.repositories.compiled_profile import (
    ProfileMissingError,
    load_compiled_profile,
)

logger = logging.getLogger("callback.profile_nodes")


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
    log_enter(logger, "check_orphans", state)
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
