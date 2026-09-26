"""The env.json settings file callback owns, independent of any MCP host config.

Read at server startup, before anything that caches env vars (e.g. the
LangSmith SDK) gets a chance to read the process environment first.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import MutableMapping

from callback import paths

logger = logging.getLogger(__name__)


def read_env_file() -> dict[str, str]:
    """Return the env var overrides stored in env.json, or {} if it doesn't exist."""
    path = paths.env_file()
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        # e.g. path is a directory, or permissions deny access. Converted into
        # the same ValueError every caller already knows how to handle
        # gracefully, rather than a startup-crashing exception class.
        raise ValueError(f"{path} could not be read: {exc}") from exc

    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc.msg}") from exc

    if not isinstance(loaded, dict) or not all(isinstance(value, str) for value in loaded.values()):
        raise ValueError(f"{path} must be a JSON object of string values")

    return loaded


def apply_env_file(environ: MutableMapping[str, str] = os.environ) -> None:
    """Load env.json into environ, without overriding keys already present there."""
    loaded_keys = []
    for key, value in read_env_file().items():
        if key == "XDG_CONFIG_HOME":
            # This is the bootstrap variable used to find env.json itself. Applying
            # a value stored inside the file would relocate where the next call to
            # paths.env_file() looks, splitting settings across two locations.
            logger.warning(
                "Ignoring XDG_CONFIG_HOME set inside %s — it can't relocate the "
                "file it was read from. Set it in the process environment instead.",
                paths.env_file(),
            )
            continue
        if key in environ:
            continue
        environ[key] = value
        loaded_keys.append(key)

    if loaded_keys:
        logger.info(
            "Loaded env vars from %s: %s",
            paths.env_file(),
            ", ".join(sorted(loaded_keys)),
        )
