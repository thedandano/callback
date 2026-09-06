"""Version check: fetch latest GitHub release tag and compare to installed version."""

from __future__ import annotations

import http.client
import importlib.metadata
import json
import logging
import urllib.request

from packaging.version import InvalidVersion, Version

logger = logging.getLogger("callback.version_check")

_LATEST_URL = "https://api.github.com/repos/thedandano/callback/releases/latest"
_cached: dict | None = None


def _current_version() -> str:
    try:
        return importlib.metadata.version("callback")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def fetch_latest_tag() -> str | None:
    try:
        with urllib.request.urlopen(_LATEST_URL, timeout=3) as response:  # noqa: S310
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError(f"release payload is a {type(payload).__name__}, not an object")
        return payload.get("tag_name")
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # OSError: URLError/HTTPError/timeouts. ValueError: bad JSON or a non-object payload.
        # HTTPException: a truncated body (IncompleteRead) surfaces from json.load.
        logger.warning(
            "latest release lookup failed (%s: %s); update status unknown", type(exc).__name__, exc
        )
        return None


def check_update() -> dict:
    global _cached
    if _cached is not None:
        return _cached

    latest = fetch_latest_tag()
    if latest is None:
        _cached = {"checked": False}
        return _cached

    current = _current_version()
    try:
        update_available = Version(latest.lstrip("v")) > Version(current)
    except InvalidVersion:
        update_available = latest.lstrip("v") != current

    _cached = {
        "checked": True,
        "current": current,
        "latest": latest,
        "update_available": update_available,
    }
    return _cached
