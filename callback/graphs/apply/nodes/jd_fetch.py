"""Apply node: fetch or accept the job description."""

import asyncio
import json
import logging
from time import perf_counter

from callback.config.observability import record_decision, trace_node
from callback.graphs.node_log import log_enter
from callback.models.state import ApplyState
from callback.services.jd_fetcher import MIN_MARKDOWN_CHARS, JDFetchError, fetch_url_to_markdown

logger = logging.getLogger("callback.apply_nodes")


jd_fetcher_logger = logging.getLogger("callback.jd_fetcher")


def _log_jd_fetch(level: int, event: str, **fields: object) -> None:
    """Emit one JSON-encoded jd_fetch lifecycle log record."""
    jd_fetcher_logger.log(level, json.dumps({"event": event, **fields}))


@trace_node("apply", "jd_fetch")
def jd_fetch(state: ApplyState) -> dict:
    """Fetch or accept a job description.

    URL input is preferred when present. Raw text is used directly only when no
    URL is provided, or as the approved fallback for URL I/O failures.
    """
    log_enter(logger, "jd_fetch", state)

    if state.jd_url:
        start = perf_counter()
        _log_jd_fetch(logging.INFO, "fetch_start", session_id=state.session_id, jd_url=state.jd_url)

        try:
            markdown = asyncio.run(fetch_url_to_markdown(state.jd_url))
        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            error_fields = {
                "session_id": state.session_id,
                "jd_url": state.jd_url,
                "duration_ms": duration_ms,
                "error_class": exc.__class__.__name__,
                "error_msg": str(exc),
            }

            if state.jd_raw_text:
                _log_jd_fetch(logging.WARNING, "fallback_used", **error_fields)
                record_decision("jd_source", "pasted_after_fetch_failed")
                return {"jd_text": state.jd_raw_text}

            _log_jd_fetch(logging.ERROR, "fetch_error", **error_fields)
            raise JDFetchError(reason="fetch_failed", url=state.jd_url, cause=exc) from exc

        duration_ms = int((perf_counter() - start) * 1000)
        byte_count = len(markdown.encode("utf-8"))
        log_fields = {
            "session_id": state.session_id,
            "jd_url": state.jd_url,
            "bytes": byte_count,
            "duration_ms": duration_ms,
        }

        if len(markdown.strip()) <= MIN_MARKDOWN_CHARS:
            _log_jd_fetch(logging.ERROR, "fetch_empty", **log_fields)
            raise JDFetchError(reason="empty_result", url=state.jd_url)

        _log_jd_fetch(logging.INFO, "fetch_ok", **log_fields)
        record_decision("jd_source", "fetched")
        return {"jd_text": markdown}

    if state.jd_raw_text:
        _log_jd_fetch(
            logging.INFO,
            "raw_text_used",
            session_id=state.session_id,
            chars=len(state.jd_raw_text),
        )
        record_decision("jd_source", "pasted")
        return {"jd_text": state.jd_raw_text}

    _log_jd_fetch(logging.ERROR, "no_input", session_id=state.session_id)
    raise ValueError("neither jd_url nor jd_raw_text provided")
