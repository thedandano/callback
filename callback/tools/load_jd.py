"""MCP tool `load_jd`."""

import sqlite3
import uuid

from callback.config.logging import log, log_exception
from callback.config.observability import (
    invoke_graph_without_native_tracing,
    trace_tool,
)
from callback.graphs.apply.graph import (
    get_apply_graph,
)
from callback.graphs.apply.graph import (
    make_config as make_apply_config,
)
from callback.models.envelope import err, ok
from callback.models.state import ApplyState
from callback.services.host_protocols import (
    EXTRACTION_PROTOCOL,
)
from callback.services.jd_fetcher import JDFetchError
from callback.tools.errors import graph_or_err
from callback.tools.resume_label import resolve_resume_label
from callback.tools.workflow import NEXT_EXTRACT_KEYWORDS, workflow


def load_jd(
    jd_url: str | None = None,
    jd_raw_text: str | None = None,
) -> dict:
    """Load a job description and return host extraction instructions.

    Takes a job description via jd_url, jd_raw_text, or both. At least one is
    required. When both are supplied, the graph attempts jd_url first and keeps
    jd_raw_text as fallback only for URL fetch failures. Empty URL content is
    reported as an error and does not fall back to pasted text.

    The resume is resolved from the internal registry: the first registered
    resume is used. If more than one is registered, a warning is logged and
    the first one wins.

    Args:
        jd_url: URL to a job description.
        jd_raw_text: Raw job description text.

    Returns:
        Envelope dict (structured content) with status, session_id, jd_text,
        extraction_protocol, and workflow guidance telling the host to call
        submit_keywords next.
    """
    session_id = str(uuid.uuid4())
    return _load_jd_impl(
        session_id,
        jd_raw_text,
        jd_url=jd_url,
    )


@trace_tool("load_jd", graph_name="apply")
def _load_jd_impl(  # noqa: C901
    session_id: str,
    jd_raw_text: str | None,
    *,
    jd_url: str | None = None,
) -> dict:
    if not (jd_url or jd_raw_text):
        return err(
            "load_jd",
            "missing_input",
            "neither jd_url nor jd_raw_text provided",
            session_id=session_id,
        )

    resolved_label, label_error = resolve_resume_label(session_id)
    if label_error:
        return label_error

    log("INFO", {"tool": "load_jd", "session_id": session_id, "resume_label": resolved_label})

    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        jd_raw_text=jd_raw_text,
        resume_label=resolved_label,
    )

    graph, graph_error = graph_or_err(get_apply_graph, session_id)
    if graph_error is not None:
        return graph_error
    try:
        config = make_apply_config(
            session_id,
            tool_name="load_jd",
            resume_label=resolved_label,
        )
        state = invoke_graph_without_native_tracing(graph, initial_state, config)
    except JDFetchError as exc:
        reason = getattr(exc, "reason", None)
        if reason == "fetch_failed":
            return err(
                stage="jd_fetch",
                code="fetch_failed",
                message=(
                    "URL fetch failed. Resubmit with jd_raw_text to use pasted "
                    "job description text."
                ),
                session_id=session_id,
                retriable=True,
            )
        if reason == "empty_result":
            return err(
                stage="jd_fetch",
                code="empty_result",
                message="URL returned no usable content.",
                session_id=session_id,
                retriable=False,
            )
        raise RuntimeError(f"unknown jd_fetch error reason: {reason}") from exc
    except sqlite3.OperationalError:
        log_exception(
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "session_store_error",
            }
        )
        return err(
            stage="load_jd",
            code="session_store_error",
            message="unable to create or update apply session store",
            session_id=session_id,
            retriable=True,
        )
    except Exception:
        log_exception(
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "unexpected_error",
            }
        )
        return err(
            stage="load_jd",
            code="unexpected_error",
            message="unexpected load_jd failure; inspect callback logs",
            session_id=session_id,
            retriable=False,
        )

    data = {
        "jd_text": state.get("jd_text"),
        "extraction_protocol": EXTRACTION_PROTOCOL,
    }
    guidance = workflow(
        phase="keyword_extraction",
        next_tool="submit_keywords",
        host_task=(
            "Extract compact JDData JSON from data.jd_text using "
            "data.extraction_protocol, then call submit_keywords."
        ),
        required_input={
            "session_id": session_id,
            "jd_json": "<compact JDData JSON string>",
        },
    )
    return ok(session_id, NEXT_EXTRACT_KEYWORDS, data, guidance)
