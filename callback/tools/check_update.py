"""MCP tool `check_update`."""

import callback.services.version_check as version_check
from callback.models.envelope import ok


def check_update() -> dict:
    """Return current version, latest GitHub release tag, and update_available flag."""
    return ok("", data=version_check.check_update())
