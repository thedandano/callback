"""MCP server for callback: host handoff and profile management.

Exposes fourteen tools, each defined in its own module under `callback.tools`:
1. load_jd — loads JD markdown and returns host extraction instructions
2. submit_keywords — accepts host-extracted JDData and returns score/tailor context
3. submit_responsibilities — optional pass 2: stores the host's key_responsibilities list
4. submit_tailor — accepts host edits and finalizes PDF/report artifacts
5. get_wiki_pages — returns profile wiki pages selected by the host
6. onboard_user — enters profile graph at onboard node
7. compile_profile — enters profile graph at compile_profile node
8. create_story — enters profile graph at create_story node
9. check_update — returns current version, latest release, and update_available flag
10. get_search_preferences, 11. set_search_preferences — job-search preferences
12. find_job, 13. record_status, 14. export_ledger — the application ledger
"""

import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

import callback.services.version_check as version_check
from callback.config import paths, settings
from callback.config.logging import configure_logging, current_log_path, log, log_exception
from callback.services.browser_install import ensure_browsers
from callback.tools.check_update import check_update
from callback.tools.compile_profile import compile_profile
from callback.tools.create_story import create_story
from callback.tools.export_ledger import export_ledger
from callback.tools.find_job import find_job
from callback.tools.get_search_preferences import get_search_preferences
from callback.tools.get_wiki_pages import get_wiki_pages
from callback.tools.load_jd import load_jd
from callback.tools.onboard_user import onboard_user
from callback.tools.record_status import record_status
from callback.tools.set_search_preferences import set_search_preferences
from callback.tools.submit_keywords import submit_keywords
from callback.tools.submit_responsibilities import submit_responsibilities
from callback.tools.submit_tailor import submit_tailor


async def _startup_version_check() -> None:
    info = await asyncio.to_thread(version_check.check_update)
    if info.get("update_available"):
        log(
            "INFO",
            {
                "event": "update_available",
                "current": info.get("current"),
                "latest": info.get("latest"),
            },
        )


async def _startup_ensure_browsers() -> None:
    log("INFO", {"event": "browser_ensure_start"})
    await asyncio.to_thread(ensure_browsers)


@asynccontextmanager
async def _lifespan(server: object) -> AsyncIterator[None]:
    asyncio.create_task(_startup_version_check())
    asyncio.create_task(_startup_ensure_browsers())
    yield


mcp = FastMCP("callback", lifespan=_lifespan)

mcp.tool()(load_jd)
mcp.tool()(submit_keywords)
mcp.tool()(submit_responsibilities)
mcp.tool()(submit_tailor)
mcp.tool()(onboard_user)
mcp.tool()(compile_profile)
mcp.tool()(create_story)
mcp.tool()(set_search_preferences)
mcp.tool()(get_search_preferences)
mcp.tool()(get_wiki_pages)
mcp.tool()(check_update)
mcp.tool()(find_job)
mcp.tool()(record_status)
mcp.tool()(export_ledger)


def _load_settings_file() -> None:
    """Apply ~/.config/callback/env.json for `python -m callback.server`.

    `callback serve` already does this in the CLI's root callback. A damaged
    env.json is reported and skipped rather than raised, same as the CLI.
    """
    try:
        settings.apply_env_file()
    except ValueError as exc:
        print(
            f"warning: {exc}; continuing without settings-file overrides. "
            "Run `callback config status` to inspect it, or fix/remove it by hand.",
            file=sys.stderr,
        )


def run() -> None:
    """Run the FastMCP stdio server."""
    if current_log_path() is None:
        configure_logging(os.environ.get("CALLBACK_LOG_PATH") or paths.log_path())
    log_path = current_log_path()
    started_at = time.monotonic()
    log(
        "INFO",
        {
            "event": "server_start",
            "transport": "stdio",
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "log_path": str(log_path) if log_path is not None else None,
        },
    )
    try:
        mcp.run(transport="stdio", show_banner=False)
    except Exception as exc:
        log_exception(
            {
                "event": "server_crash",
                "transport": "stdio",
                "pid": os.getpid(),
                "uptime_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
        raise RuntimeError("callback MCP stdio server crashed") from exc
    finally:
        log(
            "INFO",
            {
                "event": "server_stop",
                "transport": "stdio",
                "pid": os.getpid(),
                "uptime_ms": int((time.monotonic() - started_at) * 1000),
            },
        )


if __name__ == "__main__":
    _load_settings_file()
    run()
