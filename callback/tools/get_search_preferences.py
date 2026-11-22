"""MCP tool `get_search_preferences`."""

import uuid

from callback.config.logging import log
from callback.models.envelope import ok
from callback.repositories.preferences import PreferencesStore


def get_search_preferences() -> dict:
    """Return the user's job-search preferences (slim slice; no profile data).

    Returns:
        Envelope dict (structured content) with data.preferences, or
        next_action=set_search_preferences when none are stored.
    """
    session_id = str(uuid.uuid4())
    log("INFO", {"tool": "get_search_preferences", "session_id": session_id})

    prefs = PreferencesStore().load()
    if prefs is None:
        return ok(session_id, "set_search_preferences", None)
    return ok(session_id, None, {"preferences": prefs.model_dump()})
