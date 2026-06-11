"""Tests for tracing configuration adapters."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


def test_langsmith_is_declared_as_direct_dependency():
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    dependencies = pyproject["project"]["dependencies"]
    assert any(dependency.startswith("langsmith") for dependency in dependencies)


def test_build_graph_config_noops_without_trace_backend(monkeypatch):
    from pi_apply.observability import build_graph_config

    monkeypatch.delenv("PI_APPLY_TRACE_BACKEND", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    config = build_graph_config(
        session_id="session-1",
        graph_name="apply",
        tool_name="load_jd",
        resume_label="default",
    )

    assert config == {"configurable": {"thread_id": "session-1"}}


def test_build_graph_config_noops_and_warns_when_langsmith_key_missing(monkeypatch, caplog):
    from pi_apply.observability import build_graph_config

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    caplog.set_level(logging.WARNING, logger="pi_apply.observability")

    config = build_graph_config(
        session_id="session-1",
        graph_name="apply",
        tool_name="load_jd",
        resume_label="default",
    )

    assert config == {"configurable": {"thread_id": "session-1"}}
    assert "LANGSMITH_API_KEY is required" in caplog.text


def test_build_graph_config_adds_langsmith_metadata(monkeypatch):
    from pi_apply.observability import build_graph_config

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-key")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    config = build_graph_config(
        session_id="session-1",
        graph_name="apply",
        tool_name="load_jd",
        resume_label="default",
    )

    actual = {
        "configurable": config.get("configurable"),
        "run_name": config.get("run_name"),
        "tags": config.get("tags"),
        "metadata": config.get("metadata"),
        "project_name": config.get("project_name"),
        "config_project": config.get("LANGSMITH_PROJECT"),
        "env_project": __import__("os").environ["LANGSMITH_PROJECT"],
        "env_endpoint": __import__("os").environ["LANGSMITH_ENDPOINT"],
    }
    expected = {
        "configurable": {"thread_id": "session-1"},
        "run_name": "pi-apply.apply.load_jd",
        "tags": ["pi-apply", "apply", "load_jd"],
        "metadata": {
            "session_id": "session-1",
            "graph_name": "apply",
            "tool_name": "load_jd",
            "resume_label": "default",
            "transport": "stdio",
        },
        "project_name": None,
        "config_project": None,
        "env_project": "Pi-Apply",
        "env_endpoint": "https://api.smith.langchain.com",
    }

    assert actual == expected


def test_trace_tool_noops_when_backend_disabled(monkeypatch):
    from pi_apply.observability import trace_tool

    monkeypatch.delenv("PI_APPLY_TRACE_BACKEND", raising=False)

    def fail_get_traceable():
        raise AssertionError("traceable should not be imported")

    monkeypatch.setattr("pi_apply.observability._get_traceable", fail_get_traceable)

    @trace_tool("load_jd", graph_name="apply")
    def sample_tool(session_id: str, jd_raw_text: str) -> dict:
        return {"status": "ok", "session_id": session_id, "jd_text": jd_raw_text}

    assert sample_tool("session-1", "secret jd body") == {
        "status": "ok",
        "session_id": "session-1",
        "jd_text": "secret jd body",
    }


def test_trace_tool_uses_traceable_with_full_redacted_payload(monkeypatch):
    """Sanitized inputs/outputs carry real business content; contact PII is replaced."""
    from pi_apply.observability import trace_tool

    captured: dict[str, Any] = {}

    def fake_traceable(**options):
        captured["options"] = options

        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                raw_inputs = {
                    "session_id": args[0],
                    "edits": args[1],
                    "jd_raw_text": kwargs["jd_raw_text"],
                }
                result = func(*args, **kwargs)
                captured["inputs"] = options["process_inputs"](raw_inputs)
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_tool("submit_tailor", graph_name="apply")
    def sample_tool(
        session_id: str,
        edits: list[dict],
        *,
        jd_raw_text: str,
    ) -> str:
        return (
            '{"status": "ok", "next_action": null, '
            '"data": {"jd_text": "needs Python experience", "pdf_path": "/tmp/out.pdf"}, '
            '"workflow": {"phase": "complete", "next_tool": null}}'
        )

    sample_tool(
        "session-1",
        [{"target": "exp-0-b0", "value": "reduced latency by 40%"}],
        jd_raw_text="We need Python experience",
    )

    actual = {
        "name": captured["options"]["name"],
        "inputs": captured["inputs"],
        "outputs": captured["outputs"],
    }
    expected = {
        "name": "pi-apply.apply.submit_tailor",
        "inputs": {
            "tool_name": "submit_tailor",
            "graph_name": "apply",
            "transport": "stdio",
            "session_id": "session-1",
            "edits": [{"target": "exp-0-b0", "value": "reduced latency by 40%"}],
            "jd_raw_text": "We need Python experience",
        },
        "outputs": {
            "status": "ok",
            "next_action": None,
            "data": {"jd_text": "needs Python experience", "pdf_path": "/tmp/out.pdf"},
            "workflow": {"phase": "complete", "next_tool": None},
        },
    }

    assert actual == expected


def test_trace_tool_redacts_contact_pii_in_payload(monkeypatch):
    """Contact fields in inputs/outputs are replaced with typed placeholders."""
    from pi_apply.observability import trace_tool

    captured: dict[str, Any] = {}

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                raw_inputs = {
                    "session_id": args[0],
                    "jd_raw_text": kwargs.get("jd_raw_text", ""),
                }
                result = func(*args, **kwargs)
                captured["inputs"] = options["process_inputs"](raw_inputs)
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_tool("submit_tailor", graph_name="apply")
    def sample_tool(session_id: str, *, jd_raw_text: str) -> str:
        return (
            '{"status": "ok", "data": {"name": "Jane Doe", "email": "jane@example.com",'
            ' "phone": "555-867-5309", "score": 82}}'
        )

    sample_tool("session-1", jd_raw_text="Contact jane@example.com or call 555-867-5309")

    actual = {
        "output_data": captured["outputs"]["data"],
        "input_jd_raw_text": captured["inputs"]["jd_raw_text"],
    }
    expected = {
        "output_data": {"name": "[name]", "email": "[email]", "phone": "[phone]", "score": 82},
        "input_jd_raw_text": "Contact [email] or call [phone]",
    }

    assert actual == expected


def test_trace_tool_emits_sanitized_error_output_when_wrapped_function_raises(monkeypatch):
    from pi_apply.observability import trace_tool

    captured: dict[str, Any] = {}

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_tool("load_jd", graph_name="apply")
    def sample_tool() -> dict:
        raise RuntimeError("secret jd body leaked in exception")

    with pytest.raises(RuntimeError):
        sample_tool()

    assert captured["outputs"] == {
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "exception",
            "class": "RuntimeError",
        },
    }
    assert "secret" not in repr(captured["outputs"])


def test_trace_tool_forces_enabled_for_explicit_span(monkeypatch):
    from pi_apply.observability import trace_tool

    captured: dict[str, Any] = {}

    def fake_traceable(**options):
        captured["enabled"] = options.get("enabled")

        def decorator(func: Callable):
            return func

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_tool("load_jd", graph_name="apply")
    def sample_tool() -> dict:
        return {"status": "ok"}

    sample_tool()

    assert captured == {"enabled": True}


def test_trace_node_emits_full_state_and_update_redacted(monkeypatch):
    """Node inputs carry full state values; contact fields are redacted."""
    from pi_apply.observability import trace_node

    captured: dict[str, Any] = {}

    class FakeState:
        session_id = "session-1"
        resume_label = "primary"

        def model_dump(self):
            return {
                "session_id": "session-1",
                "resume_label": "primary",
                "jd_raw_text": "We need Python experience",
                "keywords": {"required": ["python", "django"]},
                "name": "Jane Doe",
                "email": "jane@example.com",
                "empty": None,
            }

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                captured["inputs"] = options["process_inputs"]({"state": args[0]})
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_node("apply", "jd_fetch")
    def sample_node(state: FakeState) -> dict:
        return {"jd_text": "We need Python experience", "score_initial": {"total": 72}}

    sample_node(FakeState())

    actual = {
        "inputs": captured["inputs"],
        "outputs": captured["outputs"],
    }
    expected = {
        "inputs": {
            "graph_name": "apply",
            "node_name": "jd_fetch",
            "transport": "stdio",
            "state": {
                "session_id": "session-1",
                "resume_label": "primary",
                "jd_raw_text": "We need Python experience",
                "keywords": {"required": ["python", "django"]},
                "name": "[name]",
                "email": "[email]",
                "empty": None,
            },
        },
        "outputs": {
            "jd_text": "We need Python experience",
            "score_initial": {"total": 72},
        },
    }

    assert actual == expected


def test_trace_node_marks_error_updates_as_status_error(monkeypatch):
    from pi_apply.observability import trace_node

    captured: dict[str, Any] = {}

    class FakeState:
        session_id = "session-1"
        resume_label = "primary"

        def model_dump(self):
            return {"session_id": "session-1", "resume_label": "primary"}

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_node("apply", "render")
    def sample_node(state: FakeState) -> dict:
        return {"error": "render: /Users/example/private.pdf failed"}

    sample_node(FakeState())

    assert captured["outputs"] == {
        "status": "error",
        "error": {"stage": "render", "code": "node_error"},
    }
    assert "private" not in repr(captured["outputs"])


def test_trace_node_emits_sanitized_error_output_when_node_raises(monkeypatch):
    from pi_apply.observability import trace_node

    captured: dict[str, Any] = {}

    class FakeState:
        session_id = "session-1"
        resume_label = "primary"

        def model_dump(self):
            return {"session_id": "session-1", "resume_label": "primary"}

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_node("apply", "jd_fetch")
    def sample_node(state: FakeState) -> dict:
        raise ValueError("private indeed url")

    with pytest.raises(ValueError):
        sample_node(FakeState())

    assert captured["outputs"] == {
        "status": "error",
        "error": {
            "stage": "jd_fetch",
            "code": "exception",
            "class": "ValueError",
        },
    }
    assert "indeed" not in repr(captured["outputs"])


def test_trace_node_forces_enabled_for_explicit_span(monkeypatch):
    from pi_apply.observability import trace_node

    captured: dict[str, Any] = {}

    def fake_traceable(**options):
        captured["enabled"] = options.get("enabled")

        def decorator(func: Callable):
            return func

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)

    @trace_node("apply", "jd_fetch")
    def sample_node(state: object) -> dict:
        return {"jd_text": "secret jd body"}

    sample_node(object())

    assert captured == {"enabled": True}


def test_trace_tool_stamps_thread_from_args_session_id(monkeypatch):
    """Tool span with session_id as first arg (submit_keywords style) stamps run metadata."""
    from pi_apply.observability import trace_tool

    fake_rt_metadata: dict[str, Any] = {}

    class FakeRunTree:
        metadata = fake_rt_metadata

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: FakeRunTree())

    @trace_tool("submit_keywords", graph_name="apply")
    def sample_tool(session_id: str, jd_raw_text: str) -> str:
        return '{"status": "ok"}'

    sample_tool("sess-abc", "some jd text")

    assert fake_rt_metadata == {"session_id": "sess-abc", "thread_id": "sess-abc"}


def test_trace_tool_stamps_thread_from_kwargs_session_id(monkeypatch):
    """Tool span with session_id passed as a keyword arg stamps run metadata."""
    from pi_apply.observability import trace_tool

    fake_rt_metadata: dict[str, Any] = {}

    class FakeRunTree:
        metadata = fake_rt_metadata

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: FakeRunTree())

    @trace_tool("get_wiki_pages", graph_name="apply")
    def sample_tool(session_id: str, page_ids: list[str]) -> str:
        return '{"status": "ok"}'

    sample_tool(session_id="sess-kw", page_ids=["p1"])

    assert fake_rt_metadata == {"session_id": "sess-kw", "thread_id": "sess-kw"}


def test_trace_node_stamps_thread_from_state_session_id(monkeypatch):
    """Node span stamps session_id from state.session_id onto run metadata."""
    from pi_apply.observability import trace_node

    fake_rt_metadata: dict[str, Any] = {}

    class FakeRunTree:
        metadata = fake_rt_metadata

    class FakeState:
        session_id = "sess-node-1"
        resume_label = "primary"

        def model_dump(self):
            return {"session_id": "sess-node-1", "resume_label": "primary"}

    def fake_traceable(**options):
        def decorator(func: Callable):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")
    monkeypatch.setattr("pi_apply.observability._get_traceable", lambda: fake_traceable)
    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: FakeRunTree())

    @trace_node("apply", "jd_fetch")
    def sample_node(state: FakeState) -> dict:
        return {"jd_text": "some text"}

    sample_node(FakeState())

    assert fake_rt_metadata == {"session_id": "sess-node-1", "thread_id": "sess-node-1"}


def test_stamp_thread_noop_when_no_run_tree(monkeypatch):
    """No active run tree: _stamp_thread is a no-op and does not raise."""
    from pi_apply.observability import _stamp_thread

    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: None)

    assert _stamp_thread("sess-123") is None


def test_stamp_thread_noop_when_session_id_absent(monkeypatch):
    """Empty/None session_id short-circuits before touching the run tree."""
    from pi_apply.observability import _stamp_thread

    def fail_get_current_run_tree():
        raise AssertionError("run tree should not be fetched when session_id is absent")

    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", fail_get_current_run_tree)

    assert _stamp_thread(None) is None
    assert _stamp_thread("") is None


def test_invoke_graph_suppresses_native_langchain_tracing(monkeypatch):
    from langsmith import utils

    from pi_apply.observability import invoke_graph_without_native_tracing

    class FakeGraph:
        def invoke(self, graph_input: dict, config: dict) -> dict:
            return {
                "input": graph_input,
                "config": config,
                "native_tracing_enabled": utils.tracing_is_enabled(),
            }

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")

    result = invoke_graph_without_native_tracing(
        FakeGraph(),
        {"session_id": "session-1"},
        {"configurable": {"thread_id": "session-1"}},
    )

    assert result == {
        "input": {"session_id": "session-1"},
        "config": {"configurable": {"thread_id": "session-1"}},
        "native_tracing_enabled": False,
    }


# ---------------------------------------------------------------------------
# _redact_pii unit tests
# ---------------------------------------------------------------------------


def test_redact_pii_replaces_contact_fields_with_placeholders():
    from pi_apply.observability import _redact_pii

    actual = _redact_pii(
        {
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-867-5309",
            "location": "San Francisco, CA",
            "linkedin": "https://linkedin.com/in/jane",
            "website": "https://janedoe.dev",
            "address": "123 Main St",
        }
    )
    expected = {
        "name": "[name]",
        "email": "[email]",
        "phone": "[phone]",
        "location": "[location]",
        "linkedin": "[url]",
        "website": "[url]",
        "address": "[location]",
    }

    assert actual == expected


def test_redact_pii_passes_non_pii_values_unchanged():
    from pi_apply.observability import _redact_pii

    actual = _redact_pii(
        {
            "jd_text": "We need Python and Django experience",
            "keywords": ["python", "django", "rest"],
            "score": 82,
            "bullet": "reduced costs 40% across 12000 users in 2024",
        }
    )
    expected = {
        "jd_text": "We need Python and Django experience",
        "keywords": ["python", "django", "rest"],
        "score": 82,
        "bullet": "reduced costs 40% across 12000 users in 2024",
    }

    assert actual == expected


def test_redact_pii_regex_backstop_cleans_free_text_strings():
    from pi_apply.observability import _redact_pii

    actual = _redact_pii("Contact us at support@example.com or call 800-555-1234")
    expected = "Contact us at [email] or call [phone]"

    assert actual == expected


def test_redact_pii_regex_backstop_no_false_positives_on_metrics():
    from pi_apply.observability import _redact_pii

    cases = [
        "reduced costs 40% across 12000 users in 2024",
        "handled 4500 requests per second",
        "99.9% uptime over 365 days",
        "version 3.11.2 released",
    ]
    for text in cases:
        assert _redact_pii(text) == text, f"false positive on: {text!r}"


def test_redact_pii_recurses_into_nested_structures():
    from pi_apply.observability import _redact_pii

    actual = _redact_pii(
        {
            "contact": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "skills": ["python", "django"],
            },
            "bullets": ["reduced latency 30%", "led team of 8 engineers"],
        }
    )
    expected = {
        "contact": {
            "name": "[name]",
            "email": "[email]",
            "skills": ["python", "django"],
        },
        "bullets": ["reduced latency 30%", "led team of 8 engineers"],
    }

    assert actual == expected


def test_redact_pii_preserves_business_content_outside_contact_block():
    """Project titles, company/school names, and job locations stay visible.

    Only the contact block (reached via the `contact` key / contact-shaped dict) is
    redacted. ProjectEntry.name, ExperienceEntry.company, and an experience location
    are business content the user wants to see, so they must survive a realistic
    SectionMap dump.
    """
    from pi_apply.observability import _redact_pii

    actual = _redact_pii(
        {
            "contact": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-867-5309",
                "location": "San Francisco, CA",
            },
            "projects": [{"name": "pi-apply", "bullets": ["cut latency 30% for 12000 users"]}],
            "experience": [{"company": "Acme Corp", "role": "Engineer", "location": "Austin, TX"}],
            "education": [{"institution": "State University"}],
        }
    )
    expected = {
        "contact": {
            "name": "[name]",
            "email": "[email]",
            "phone": "[phone]",
            "location": "[location]",
        },
        "projects": [{"name": "pi-apply", "bullets": ["cut latency 30% for 12000 users"]}],
        "experience": [{"company": "Acme Corp", "role": "Engineer", "location": "Austin, TX"}],
        "education": [{"institution": "State University"}],
    }

    assert actual == expected


def test_redact_pii_does_not_mutate_input():
    from pi_apply.observability import _redact_pii

    # Input that genuinely gets redacted (email key), so a mutating impl would be caught.
    original = {"email": "jane@example.com", "score": 72}
    result = _redact_pii(original)

    assert original == {"email": "jane@example.com", "score": 72}
    assert result == {"email": "[email]", "score": 72}


def test_redact_pii_skips_empty_string_pii_values():
    from pi_apply.observability import _redact_pii

    # Empty strings in PII fields should pass through (nothing to redact).
    actual = _redact_pii({"email": "", "name": "", "score": 90})
    expected = {"email": "", "name": "", "score": 90}

    assert actual == expected


# ---------------------------------------------------------------------------
# Tool-input and node-input passthrough tests
# ---------------------------------------------------------------------------


def test_sanitize_tool_inputs_jd_raw_text_and_edits_survive():
    """Real jd_raw_text and edits values are present in sanitized tool inputs."""
    from pi_apply.observability import _sanitize_tool_inputs

    processor = _sanitize_tool_inputs("submit_tailor", "apply")
    result = processor(
        {
            "session_id": "sess-1",
            "jd_raw_text": "We need Python and Django experience",
            "edits": [{"target": "exp-0-b0", "value": "reduced latency by 40%"}],
            "output_dir": "/tmp/out",
        }
    )

    assert result == {
        "tool_name": "submit_tailor",
        "graph_name": "apply",
        "transport": "stdio",
        "session_id": "sess-1",
        "jd_raw_text": "We need Python and Django experience",
        "edits": [{"target": "exp-0-b0", "value": "reduced latency by 40%"}],
        "output_dir": "/tmp/out",
    }


def test_sanitize_node_inputs_full_state_present_contact_redacted():
    """Full state is present in node inputs; contact keys are redacted."""
    from pi_apply.observability import _sanitize_node_inputs

    class FakeState:
        def model_dump(self):
            return {
                "session_id": "sess-1",
                "resume_label": "primary",
                "jd_raw_text": "Python required",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-867-5309",
                "score_initial": {"total": 68},
            }

    processor = _sanitize_node_inputs("apply", "score_initial")
    result = processor({"state": FakeState()})

    assert result == {
        "graph_name": "apply",
        "node_name": "score_initial",
        "transport": "stdio",
        "state": {
            "session_id": "sess-1",
            "resume_label": "primary",
            "jd_raw_text": "Python required",
            "name": "[name]",
            "email": "[email]",
            "phone": "[phone]",
            "score_initial": {"total": 68},
        },
    }
