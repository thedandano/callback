"""Apply node: render the tailored resume to PDF."""

import json
import logging
import re
from datetime import date
from pathlib import Path

from callback.config import paths
from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState
from callback.render import render_resume

logger = logging.getLogger("callback.apply_nodes")


def _resume_filename_part(value: str | None, fallback: str) -> str:
    raw = (value or "").strip() or fallback
    safe = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_") or fallback
    return "_".join(part.capitalize() for part in safe.split("_"))


def _resume_pdf_filename(candidate_name: str | None, company_name: str | None) -> str:
    candidate = _resume_filename_part(candidate_name, "Candidate")
    company = _resume_filename_part(company_name, "Company")
    return f"{candidate}_{company}_Resume.pdf"


def _today() -> date:
    return date.today()  # local date, matching the skills' <YYYY-MM-DD> folders


def _artifact_dir(state: ApplyState) -> Path:
    """Folder for this run's PDF: the caller's output_dir, else the dated folder render
    already chose, else apps_dir/<local date>/<company-role-slug>/.

    An explicit output_dir always wins, so a retry can redirect the output. render stores
    the dated default in state.artifact_dir, so a retry that crosses midnight keeps it.
    """
    if state.output_dir:
        return Path(state.output_dir)
    if state.artifact_dir:
        return Path(state.artifact_dir)
    keywords = state.keywords or {}
    folder = paths.slug(keywords.get("company"), keywords.get("title"))
    return paths.apps_dir() / _today().isoformat() / folder


def _dated_dir_update(state: ApplyState, folder: Path) -> dict:
    """State update that remembers the dated default folder, never an explicit output_dir.

    An explicit folder is left out so a retry without output_dir picks the dated default
    again, while a dated folder stored earlier stays put (the midnight guarantee).
    """
    if state.output_dir:
        return {}
    return {"artifact_dir": str(folder)}


@trace_node("apply", "render")
def render(state: ApplyState) -> dict:
    """Render tailored resume to PDF via HTML + Playwright."""
    log_enter(logger, "render", state)
    if state.tailored is None:
        return {"error": "render: state.tailored is None — tailor node must run first"}

    base_dir = _artifact_dir(state)
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {
            "error": f"render: cannot create output dir {base_dir}: {exc}",
            **_dated_dir_update(state, base_dir),
        }
    company_name = state.keywords.get("company") if state.keywords else None
    output_path = str(base_dir / _resume_pdf_filename(state.tailored.name, company_name))

    result = render_resume(state.tailored.model_dump(), output_path)
    if result["success"]:
        logger.info(
            json.dumps({"node": "render", "session_id": state.session_id, "pdf_path": output_path})
        )
        return {
            "pdf_path": output_path,
            "render_page_count": result.get("page_count"),
            "render_warnings": result.get("warnings") or [],
            **_dated_dir_update(state, base_dir),
        }
    else:
        logger.error(
            json.dumps({"node": "render", "session_id": state.session_id, "error": result["error"]})
        )
        return {
            "error": f"render: {result['error']}",
            **_dated_dir_update(state, base_dir),
        }
