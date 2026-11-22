"""Playwright browser install used at server startup."""

import subprocess
import sys

from callback.config.logging import log


def ensure_browsers() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
    )
    if result.returncode != 0:
        log("WARNING", {"event": "browser_install_failed", "returncode": result.returncode})
