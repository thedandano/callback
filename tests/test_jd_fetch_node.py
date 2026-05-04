"""Tests for the jd_fetch apply node."""

import json
import logging
from typing import Any
from unittest.mock import ANY

import pytest

import pi_apply.apply_nodes as apply_nodes
from pi_apply.jd_fetcher import MIN_MARKDOWN_CHARS, JDFetchError
from pi_apply.state import ApplyState


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []
    result = {"value": "# Senior Python Engineer\n\nBuild APIs and ship reliable systems."}

    async def fetch_url_to_markdown(url: str) -> str:
        calls.append(url)
        if isinstance(result["value"], Exception):
            raise result["value"]
        return result["value"]

    monkeypatch.setattr(apply_nodes, "fetch_url_to_markdown", fetch_url_to_markdown)
    return calls, result


def make_state(**overrides):
    data: dict[str, Any] = {"session_id": "session-123", "resume_path": "/tmp/resume.txt"}
    data.update(overrides)
    return ApplyState(**data)


def jd_log_payloads(caplog):
    payloads = []
    for record in caplog.records:
        if record.name == "pi_apply.jd_fetcher":
            payloads.append((record.levelno, json.loads(record.message)))
    return payloads


def test_jd_fetch_url_success_returns_markdown_and_logs(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    calls, result_value = fake_fetch
    jd_url = "https://example.com/job"
    state = make_state(jd_url=jd_url)

    result = apply_nodes.jd_fetch(state)

    assert result == {"jd_text": result_value["value"]}
    assert calls == [jd_url]
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "fetch_start", "session_id": state.session_id, "jd_url": jd_url},
        ),
        (
            logging.INFO,
            {
                "event": "fetch_ok",
                "session_id": state.session_id,
                "jd_url": jd_url,
                "bytes": len(result_value["value"].encode("utf-8")),
                "duration_ms": ANY,
            },
        ),
    ]


def test_jd_fetch_raw_text_passthrough_unchanged(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    calls, _ = fake_fetch
    raw_text = "Python engineer needed\nRemote role"
    state = make_state(jd_raw_text=raw_text)

    result = apply_nodes.jd_fetch(state)

    assert result == {"jd_text": raw_text}
    assert calls == []
    assert jd_log_payloads(caplog) == []


def test_jd_fetch_io_failure_with_raw_text_falls_back_and_logs_warning(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    _, result_value = fake_fetch
    result_value["value"] = TimeoutError("site timed out")
    jd_url = "https://example.com/job"
    state = make_state(jd_url=jd_url, jd_raw_text="Fallback JD")

    result = apply_nodes.jd_fetch(state)

    assert result == {"jd_text": "Fallback JD"}
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "fetch_start", "session_id": state.session_id, "jd_url": jd_url},
        ),
        (
            logging.WARNING,
            {
                "event": "fallback_used",
                "session_id": state.session_id,
                "jd_url": jd_url,
                "duration_ms": ANY,
                "error_class": "TimeoutError",
                "error_msg": "site timed out",
            },
        ),
    ]


def test_jd_fetch_io_failure_without_raw_text_raises_and_logs_error(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    _, result_value = fake_fetch
    result_value["value"] = RuntimeError("dns failed")
    jd_url = "https://example.com/job"
    state = make_state(jd_url=jd_url)

    with pytest.raises(JDFetchError) as exc_info:
        apply_nodes.jd_fetch(state)

    assert exc_info.value.reason == "fetch_failed"
    assert exc_info.value.url == jd_url
    assert isinstance(exc_info.value.cause, RuntimeError)
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "fetch_start", "session_id": state.session_id, "jd_url": jd_url},
        ),
        (
            logging.ERROR,
            {
                "event": "fetch_error",
                "session_id": state.session_id,
                "jd_url": jd_url,
                "duration_ms": ANY,
                "error_class": "RuntimeError",
                "error_msg": "dns failed",
            },
        ),
    ]


def test_jd_fetch_empty_result_with_raw_text_still_raises(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    _, result_value = fake_fetch
    result_value["value"] = "x" * MIN_MARKDOWN_CHARS
    jd_url = "https://example.com/job"
    state = make_state(jd_url=jd_url, jd_raw_text="Fallback JD")

    with pytest.raises(JDFetchError) as exc_info:
        apply_nodes.jd_fetch(state)

    assert exc_info.value.reason == "empty_result"
    assert exc_info.value.url == jd_url
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "fetch_start", "session_id": state.session_id, "jd_url": jd_url},
        ),
        (
            logging.ERROR,
            {
                "event": "fetch_empty",
                "session_id": state.session_id,
                "jd_url": jd_url,
                "bytes": MIN_MARKDOWN_CHARS,
                "duration_ms": ANY,
            },
        ),
    ]


def test_jd_fetch_empty_result_without_raw_text_raises(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    _, result_value = fake_fetch
    result_value["value"] = "too short"
    jd_url = "https://example.com/job"
    state = make_state(jd_url=jd_url)

    with pytest.raises(JDFetchError) as exc_info:
        apply_nodes.jd_fetch(state)

    assert exc_info.value.reason == "empty_result"
    assert exc_info.value.url == jd_url
    assert jd_log_payloads(caplog) == [
        (
            logging.INFO,
            {"event": "fetch_start", "session_id": state.session_id, "jd_url": jd_url},
        ),
        (
            logging.ERROR,
            {
                "event": "fetch_empty",
                "session_id": state.session_id,
                "jd_url": jd_url,
                "bytes": len(result_value["value"].encode("utf-8")),
                "duration_ms": ANY,
            },
        ),
    ]


def test_jd_fetch_no_input_raises_value_error_and_logs(caplog, fake_fetch):
    caplog.set_level(logging.INFO, logger="pi_apply.jd_fetcher")
    state = make_state()

    with pytest.raises(ValueError, match="neither jd_url nor jd_raw_text provided"):
        apply_nodes.jd_fetch(state)

    logs = jd_log_payloads(caplog)
    assert len(logs) == 1
    assert logs[0][0] == logging.ERROR
    assert logs[0][1] == {"event": "no_input", "session_id": state.session_id}
