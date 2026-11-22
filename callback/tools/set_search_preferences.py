"""MCP tool `set_search_preferences`."""

import datetime
import uuid

from pydantic import ValidationError

from callback.config.logging import log
from callback.models.preferences import SearchPreferences
from callback.repositories.preferences import PreferencesStore
from callback.tools.envelope import err, ok


def set_search_preferences(preferences: dict) -> dict:
    """Persist the user's job-search preferences.

    This call fully replaces any stored preferences — omitted optional fields
    revert to their defaults.

    Args:
        preferences: SearchPreferences fields. home_location and work_types are
            required; updated_at is stamped server-side.

    Returns:
        Envelope dict (structured content) echoing the stored preferences under data.preferences.
    """
    session_id = str(uuid.uuid4())
    log("INFO", {"tool": "set_search_preferences", "session_id": session_id})

    stamped = {**preferences, "updated_at": datetime.datetime.now(datetime.UTC).isoformat()}
    try:
        prefs = SearchPreferences.model_validate(stamped)
    except ValidationError as exc:
        return err(
            stage="set_search_preferences",
            code="invalid_preferences",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )

    PreferencesStore().save(prefs)
    return ok(session_id, None, {"preferences": prefs.model_dump()})
