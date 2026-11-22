"""Profile node: report whether a resume is registered."""

import logging

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ProfileState
from callback.repositories.resumes import list_resumes

logger = logging.getLogger("callback.profile_nodes")


@trace_node("profile", "check_profile")
def check_profile(state: ProfileState) -> dict:
    """A profile exists once a resume is registered — compiling (which creates the
    compiled profile) happens downstream, and check_orphans already tolerates a
    missing compiled profile.
    """
    log_enter(logger, "check_profile", state)
    return {"profile_exists": len(list_resumes()) > 0}
