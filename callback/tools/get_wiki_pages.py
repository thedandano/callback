"""MCP tool `get_wiki_pages`."""

from callback.config.logging import log
from callback.config.observability import (
    trace_tool,
)
from callback.graphs.apply.graph import (
    get_apply_graph,
)
from callback.graphs.apply.graph import (
    make_config as make_apply_config,
)
from callback.models.envelope import err, ok
from callback.repositories.wiki import WikiPageIdError, WikiStore
from callback.tools.errors import graph_or_err
from callback.tools.workflow import workflow


def get_wiki_pages(session_id: str, page_ids: list[str]) -> dict:
    """Batch-fetch wiki pages for a session's resume.

    This tool exists because the wiki lives on the server's local filesystem and
    the host LLM has no direct file access in an MCP context — it can only reach
    files through tools the server exposes. The host reads the index returned by
    submit_keywords, picks the relevant page paths, and fetches their content here.

    Args:
        session_id: Apply session ID (used to resolve the resume_label).
        page_ids: Page paths relative to wiki root (e.g., ['experience/acme.md']).

    Returns:
        Envelope dict (structured content) with pages dict {page_id: content}.
        Missing pages return empty string.
    """
    return _get_wiki_pages_impl(session_id, page_ids)


@trace_tool("get_wiki_pages", graph_name="apply")
def _get_wiki_pages_impl(session_id: str, page_ids: list[str]) -> dict:
    log("INFO", {"tool": "get_wiki_pages", "session_id": session_id, "page_count": len(page_ids)})

    graph, graph_error = graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    config = make_apply_config(session_id, tool_name="get_wiki_pages")
    snapshot = graph.get_state(config)

    if not snapshot.values:
        return err(
            stage="get_wiki_pages",
            code="invalid_session",
            message="session_id not found",
            session_id=session_id,
        )

    state_values = snapshot.values
    resume_label = state_values.get("resume_label")
    if not resume_label:
        return err(
            stage="get_wiki_pages",
            code="no_resume_label",
            message="no resume_label in session; call load_jd first",
            session_id=session_id,
        )

    try:
        pages = WikiStore().read_pages(resume_label, page_ids)
    except WikiPageIdError as exc:
        log(
            "WARNING",
            {"tool": "get_wiki_pages", "session_id": session_id, "event": "invalid_page_id"},
        )
        return err(
            stage="get_wiki_pages",
            code="invalid_page_id",
            message=str(exc),
            session_id=session_id,
            retriable=True,
        )
    guidance = workflow(
        phase="tailor_editing",
        next_tool="submit_tailor",
        host_task=(
            "Use these pages with the previously returned sections, score gaps, "
            "and tailor instructions to construct honest edits, then call submit_tailor."
        ),
        required_input={
            "session_id": session_id,
            "edits": [
                {
                    "section": "experience",
                    "op": "replace",
                    "target": "exp-0-b0",
                    "value": "<truthful revised bullet>",
                }
            ],
            "no_coverage": False,
        },
    )
    return ok(session_id, data={"pages": pages}, workflow=guidance)
