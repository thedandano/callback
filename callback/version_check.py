"""Version check: fetch latest GitHub release tag and compare to installed version."""

from __future__ import annotations

import importlib.metadata

import httpx
from packaging.version import InvalidVersion, Version

_LATEST_URL = "https://api.github.com/repos/thedandano/callback/releases/latest"
_cached: dict | None = None


def _current_version() -> str:
    try:
        return importlib.metadata.version("callback")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def fetch_latest_tag() -> str | None:
    try:
        response = httpx.get(_LATEST_URL, timeout=3)
        response.raise_for_status()
        return response.json().get("tag_name")
    except Exception:
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
