"""Tracing configuration adapters for callback workflows."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from typing import Any

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

TRACE_BACKEND_ENV = "CALLBACK_TRACE_BACKEND"
LANGSMITH_BACKEND = "langsmith"
LANGSMITH_TRACING_ENV = "LANGSMITH_TRACING"
LANGSMITH_API_KEY_ENV = "LANGSMITH_API_KEY"
LANGSMITH_ENDPOINT_ENV = "LANGSMITH_ENDPOINT"
LANGSMITH_PROJECT_ENV = "LANGSMITH_PROJECT"
DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "Callback"
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
TRANSPORT = "stdio"

# Contact-PII keys, redacted by key name when walking dicts.
# `email` / `phone` are unambiguous — no business model uses those key names — so
# they are redacted anywhere they appear. `name` / `location` / `website` / etc.
# collide with business content (ProjectEntry.name, ExperienceEntry/EducationEntry
# locations), so they are redacted ONLY inside a contact block (a dict reached via a
# `contact` key, or one that is contact-shaped: it has an `email` or `phone` key).
# This keeps project titles, company/school names, and job locations visible while
# scrubbing the resume's contact header. See ContactInfo (section_map.py),
# TailoredResume header (state.py), and html_builder.py contact items.
_ALWAYS_PII_KEYS: frozenset[str] = frozenset({"email", "phone"})
_CONTACT_ONLY_KEYS: frozenset[str] = frozenset(
    {"name", "location", "address", "linkedin", "website"}
)

_PII_PLACEHOLDER: dict[str, str] = {
    "email": "[email]",
    "phone": "[phone]",
    "name": "[name]",
    "location": "[location]",
    "address": "[location]",
    "linkedin": "[url]",
    "website": "[url]",
}

# Regex backstop: redacts email and phone patterns embedded in free-text strings.
# Phone pattern: optional country code (+1 or 1), then 10 digits optionally grouped
# with spaces/dashes/dots/parens. Conservative: 4-to-9-digit bare numbers, percentages,
# and years never match — but a bare 10-digit (or 11-digit with country code) sequence
# is treated as a phone number. Acceptable for JD/resume text, which has no such numbers.
_EMAIL_RE = re.compile(r"[\w.%+\-]+@[\w.\-]+\.\w{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)"  # not preceded by a digit
    r"(?:\+?1[\s.\-]?)?"  # optional country code
    r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"  # NXX-NXX-XXXX
    r"(?!\d)"  # not followed by a digit
)


def _is_contact_block(mapping: Mapping[str, Any]) -> bool:
    """A dict is a contact block if it has an `email` or `phone` key (any case)."""
    keys = {str(k).lower() for k in mapping}
    return "email" in keys or "phone" in keys


def _redact_pii(value: Any, *, in_contact: bool = False) -> Any:  # noqa: C901
    """Recursively walk *value* and return a new structure with contact PII redacted.

    Never mutates the input — all containers are rebuilt. Two-layer strategy:
    1. Key-based (primary): `email` / `phone` keys are redacted anywhere; the broader
       contact keys (`name`, `location`, `website`, ...) are redacted only inside a
       contact block, so business fields like ProjectEntry.name stay visible.
    2. Regex backstop (secondary): for any plain string anywhere in the tree, redact
       embedded email and US-phone patterns.
    """
    if isinstance(value, Mapping):
        contact_here = in_contact or _is_contact_block(value)
        result: dict[str, Any] = {}
        for k, v in value.items():
            k_lower = str(k).lower()
            redact_key = k_lower in _ALWAYS_PII_KEYS or (
                contact_here and k_lower in _CONTACT_ONLY_KEYS
            )
            if redact_key and isinstance(v, str) and v.strip():
                result[k] = _PII_PLACEHOLDER[k_lower]
            else:
                # A value reached via a `contact` key is itself a contact block.
                result[k] = _redact_pii(v, in_contact=contact_here or k_lower == "contact")
        return result
    if isinstance(value, (list, tuple)):
        redacted = [_redact_pii(item, in_contact=in_contact) for item in value]
        return type(value)(redacted)
    if isinstance(value, str):
        out = _EMAIL_RE.sub("[email]", value)
        out = _PHONE_RE.sub("[phone]", out)
        return out
    return value


class _TraceExceptionOutput:
    """Sentinel returned only so process_outputs can record sanitized errors."""

    def __init__(self, exc: BaseException, sanitized: dict[str, Any]) -> None:
        self.exc = exc
        self.sanitized = sanitized


def _base_config(session_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": session_id}}


def _env_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_ENV_VALUES


def _langsmith_ready() -> bool:
    if not _env_enabled(os.environ.get(LANGSMITH_TRACING_ENV)):
        logger.warning(
            "%s=langsmith requires %s=true; tracing disabled",
            TRACE_BACKEND_ENV,
            LANGSMITH_TRACING_ENV,
        )
        return False
    if not os.environ.get(LANGSMITH_API_KEY_ENV):
        logger.warning(
            "%s is required when %s=langsmith; tracing disabled",
            LANGSMITH_API_KEY_ENV,
            TRACE_BACKEND_ENV,
        )
        return False
    os.environ.setdefault(LANGSMITH_ENDPOINT_ENV, DEFAULT_LANGSMITH_ENDPOINT)
    os.environ.setdefault(LANGSMITH_PROJECT_ENV, DEFAULT_LANGSMITH_PROJECT)
    return True


def _get_traceable() -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    from langsmith import traceable

    return traceable


def _stamp_thread(session_id: str | None) -> None:
    """Stamp session_id / thread_id onto the active LangSmith run tree.

    Must be called from within a @traceable execution so the run tree is open.
    No-op when session_id is absent or no active run tree exists.
    """
    if not session_id:
        return
    from langsmith.run_helpers import get_current_run_tree

    rt = get_current_run_tree()
    if rt is not None:
        rt.metadata["session_id"] = session_id
        rt.metadata["thread_id"] = session_id


def _trace_enabled() -> bool:
    backend = os.environ.get(TRACE_BACKEND_ENV, "").strip().lower()
    return backend == LANGSMITH_BACKEND and _langsmith_ready()


@contextmanager
def _suppress_native_langchain_tracing() -> Iterator[None]:
    if not _trace_enabled():
        yield
        return

    from langsmith.run_helpers import tracing_context

    with tracing_context(enabled=False):
        yield


def invoke_graph_without_native_tracing(
    graph: Any,
    graph_input: Any,
    config: RunnableConfig,
) -> Any:
    """Invoke a LangGraph while relying on explicit sanitized spans only."""
    with _suppress_native_langchain_tracing():
        return graph.invoke(graph_input, config)


def _mapping_value(inputs: Mapping[str, Any], key: str) -> Any:
    if key in inputs:
        return inputs[key]
    kwargs = inputs.get("kwargs")
    if isinstance(kwargs, Mapping):
        return kwargs.get(key)
    return None


def _parse_envelope(output: Any) -> Mapping[str, Any] | None:
    if isinstance(output, _TraceExceptionOutput):
        return output.sanitized
    if isinstance(output, Mapping):
        return output
    if not isinstance(output, str):
        return None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _sanitize_tool_inputs(
    tool_name: str,
    graph_name: str | None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def _processor(inputs: Mapping[str, Any]) -> dict[str, Any]:
        # Collect the real call inputs, then redact contact PII throughout.
        raw: dict[str, Any] = {
            "tool_name": tool_name,
            "transport": TRANSPORT,
        }
        if graph_name is not None:
            raw["graph_name"] = graph_name

        for key in (
            "session_id",
            "jd_url",
            "jd_raw_text",
            "jd_json",
            "edits",
            "page_ids",
            "no_coverage",
            "resume_label",
            "output_dir",
        ):
            value = _mapping_value(inputs, key)
            if value is not None:
                raw[key] = value

        return _redact_pii(raw)

    return _processor


def _summarize_compiled_profile(value: Any) -> Any:
    """Reduce a compiled_profile payload to counts — never export story narratives."""
    if not isinstance(value, dict):
        return value
    return {
        "story_count": len(value.get("stories") or []),
        "skills_index_count": len(value.get("skills_index") or []),
        "orphaned_skills_count": len(value.get("orphaned_skills") or []),
    }


def _summarize_sections(value: Any) -> Any:
    """Reduce a sections payload to its key names — section bodies never leave the span."""
    if not isinstance(value, dict):
        return value
    return {"keys": sorted(value.keys())}


def _summarize_intake_value(value: Any) -> Any:
    """Summarize one intake field: lengths for containers, placeholders for text."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sorted(value.keys())
    if isinstance(value, str) and value:
        return "<redacted>"
    return value


def _summarize_intake(value: Any) -> Any:
    """Reduce an intake payload field-by-field (covers stories, onboard_text, etc.)."""
    if not isinstance(value, dict):
        return value
    return {key: _summarize_intake_value(val) for key, val in value.items()}


_SKILL_LIST_KEYS: frozenset[str] = frozenset(
    {"skills_index", "orphaned_skills", "skill_coverage_warnings"}
)


def _summarize_skill_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce top-level skill-name-bearing fields to counts/placeholders.

    Skill names are business content, same as story narratives — the span
    contract is counts and key names only.
    """
    summarized = dict(data)
    for key in _SKILL_LIST_KEYS:
        if key in summarized and isinstance(summarized[key], list):
            summarized[key] = len(summarized[key])
    primary_skill = summarized.get("primary_skill")
    if isinstance(primary_skill, str):
        summarized["primary_skill"] = "<redacted>"
    return summarized


def _summarize_profile_content(envelope: dict[str, Any]) -> dict[str, Any]:
    """Summarize profile/resume business content within envelope["data"] to counts
    and key names. No skill names (skills_index, orphaned_skills,
    skill_coverage_warnings, primary_skill) or story identifiers leave the span.
    """
    data = envelope.get("data")
    if not isinstance(data, dict):
        return envelope
    summarized = _summarize_skill_fields(data)
    if "compiled_profile" in summarized:
        summarized["compiled_profile"] = _summarize_compiled_profile(summarized["compiled_profile"])
    if "sections" in summarized:
        summarized["sections"] = _summarize_sections(summarized["sections"])
    if "intake" in summarized:
        summarized["intake"] = _summarize_intake(summarized["intake"])
    if isinstance(summarized.get("story_id"), str):
        summarized["story_id"] = "<redacted>"
    return {**envelope, "data": summarized}


def _sanitize_tool_output(output: Any) -> dict[str, Any]:
    if isinstance(output, _TraceExceptionOutput):
        return output.sanitized

    envelope = _parse_envelope(output)
    if envelope is None:
        return {"output_type": type(output).__name__}

    # Contact PII is stripped from the envelope. Profile/resume business content
    # (compiled_profile, sections, intake) is summarized to counts and key names —
    # story narratives, section text, and resume text never leave the span.
    return _summarize_profile_content(_redact_pii(dict(envelope)))


# Span-summarization contract for LangGraph node traces (CLAUDE.md: "safe
# booleans/counts and state/update key names" — never resume text, JD text,
# wiki content, story narratives, or skill names).
_SPAN_MAPPING_EXEMPT_KEYS: frozenset[str] = frozenset(
    {"session_id", "graph_name", "node_name", "transport", "status"}
)
_SPAN_ERROR_EXEMPT_KEYS: frozenset[str] = frozenset({"stage", "code", "retriable"})
# Numeric state fields that are genuine counts. Every other number (e.g.
# candidate_years, a measurement about the candidate) is redacted.
_SPAN_COUNT_KEYS: frozenset[str] = frozenset({"render_page_count", "max_pages"})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _summarize_span_value(value: Any) -> Any:
    """Reduce one span value to a count/boolean/key-name shape — never content."""
    if isinstance(value, bool) or value is None:
        return value
    if _is_number(value):
        return "<redacted>"
    if isinstance(value, str):
        return {"len": len(value)}
    if isinstance(value, (list, tuple)):
        return {"len": len(value)}
    if isinstance(value, dict):
        return {"keys": sorted(value.keys())}
    if hasattr(value, "model_dump"):
        return _summarize_span_mapping(value.model_dump())
    return type(value).__name__


def _summarize_span_error(error: dict[str, Any]) -> dict[str, Any]:
    summarized: dict[str, Any] = {}
    for key, val in error.items():
        if key in _SPAN_ERROR_EXEMPT_KEYS:
            summarized[key] = val
        elif key == "message" and isinstance(val, str):
            summarized[key] = {"len": len(val)}
        else:
            summarized[key] = _summarize_span_value(val)
    return summarized


def _summarize_span_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize every value in *mapping* except the safe metadata/error keys."""
    summarized: dict[str, Any] = {}
    for key, value in mapping.items():
        if key in _SPAN_MAPPING_EXEMPT_KEYS or (key in _SPAN_COUNT_KEYS and _is_number(value)):
            summarized[key] = value
        elif key == "error" and isinstance(value, dict):
            summarized[key] = _summarize_span_error(value)
        else:
            summarized[key] = _summarize_span_value(value)
    return summarized


def _sanitize_node_inputs(
    graph_name: str,
    node_name: str,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def _processor(inputs: Mapping[str, Any]) -> dict[str, Any]:
        state = _mapping_value(inputs, "state")
        raw: dict[str, Any] = {
            "graph_name": graph_name,
            "node_name": node_name,
            "transport": TRANSPORT,
        }
        if hasattr(state, "model_dump"):
            raw["state"] = _summarize_span_mapping(state.model_dump())
        return _redact_pii(raw)

    return _processor


def _sanitize_node_output(node_name: str) -> Callable[[Any], dict[str, Any]]:
    def _processor(output: Any) -> dict[str, Any]:
        if isinstance(output, _TraceExceptionOutput):
            return output.sanitized
        if isinstance(output, Mapping):
            summarized: dict[str, Any] = _summarize_span_mapping(dict(output))
            if "error" in output:
                summarized["status"] = "error"
                summarized["error"] = {
                    "stage": node_name,
                    "code": "node_error",
                }
            return summarized
        return {"output_type": type(output).__name__}

    return _processor


def _exception_output(stage: str, exc: BaseException) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {
            "stage": stage,
            "code": "exception",
            "class": exc.__class__.__name__,
        },
    }


def _raise_traced_exception(result: Any) -> Any:
    if isinstance(result, _TraceExceptionOutput):
        raise result.exc
    return result


def _return_exception_output(
    func: Callable[..., Any],
    *,
    stage: str,
    get_session_id: Callable[[tuple[Any, ...], dict[str, Any], Any], str | None] | None = None,
) -> Callable[..., Any]:
    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
            if get_session_id is not None:
                _stamp_thread(get_session_id(args, kwargs, result))
            return result
        except BaseException as exc:
            return _TraceExceptionOutput(exc, _exception_output(stage, exc))

    return _wrapper


def _tool_session_id(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> str | None:
    """Extract session_id for thread-stamping from a tool call.

    Every traced tool impl (load_jd, submit_keywords, submit_tailor,
    get_wiki_pages, onboard_user) receives session_id as its first positional
    argument; load_jd's public wrapper generates the id and passes it in. So the
    session_id is always present in args/kwargs.
    """
    if args and isinstance(args[0], str) and args[0]:
        return args[0]
    sid = kwargs.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    return None


def trace_tool(
    tool_name: str,
    graph_name: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Trace an MCP tool implementation with sanitized inputs and outputs."""

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _trace_enabled():
                return func(*args, **kwargs)

            name_parts = ["callback"]
            if graph_name:
                name_parts.append(graph_name)
            name_parts.append(tool_name)
            traced = _get_traceable()(
                name=".".join(name_parts),
                run_type="tool",
                tags=["callback", "mcp-tool", tool_name],
                metadata={"tool_name": tool_name, "graph_name": graph_name, "transport": TRANSPORT},
                enabled=True,
                process_inputs=_sanitize_tool_inputs(tool_name, graph_name),
                process_outputs=_sanitize_tool_output,
            )(_return_exception_output(func, stage=tool_name, get_session_id=_tool_session_id))
            return _raise_traced_exception(traced(*args, **kwargs))

        return _wrapper

    return _decorator


def _node_session_id(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> str | None:
    """Extract session_id from the node's state argument (first positional arg)."""
    state = args[0] if args else kwargs.get("state")
    return getattr(state, "session_id", None)


def trace_node(
    graph_name: str,
    node_name: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Trace a LangGraph node with sanitized state/update metadata only."""

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _trace_enabled():
                return func(*args, **kwargs)

            traced = _get_traceable()(
                name=f"callback.{graph_name}.{node_name}",
                run_type="chain",
                tags=["callback", graph_name, node_name],
                metadata={"graph_name": graph_name, "node_name": node_name, "transport": TRANSPORT},
                enabled=True,
                process_inputs=_sanitize_node_inputs(graph_name, node_name),
                process_outputs=_sanitize_node_output(node_name),
            )(_return_exception_output(func, stage=node_name, get_session_id=_node_session_id))
            return _raise_traced_exception(traced(*args, **kwargs))

        return _wrapper

    return _decorator


@trace_tool("trace_check")
def emit_trace_check_probe(
    session_id: str = "trace-check",
    target: str = "env",
    project: str = DEFAULT_LANGSMITH_PROJECT,
) -> dict[str, Any]:
    """Emit one safe trace-check span."""
    return {
        "status": "ok",
        "session_id": session_id,
        "target": target,
        "project": project,
    }


def build_graph_config(
    *,
    session_id: str,
    graph_name: str,
    tool_name: str | None = None,
    resume_label: str | None = None,
    transport: str = "stdio",
) -> RunnableConfig:
    """Return LangGraph RunnableConfig with optional LangSmith trace metadata."""
    config = _base_config(session_id)
    backend = os.environ.get(TRACE_BACKEND_ENV, "").strip().lower()
    if backend != LANGSMITH_BACKEND:
        return config
    if not _langsmith_ready():
        return config

    effective_tool = tool_name or "unknown"
    metadata: dict[str, Any] = {
        "session_id": session_id,
        "graph_name": graph_name,
        "tool_name": effective_tool,
        "resume_label": resume_label,
        "transport": transport,
    }
    config["run_name"] = f"callback.{graph_name}.{effective_tool}"
    config["tags"] = ["callback", graph_name, effective_tool]
    config["metadata"] = metadata
    return config
