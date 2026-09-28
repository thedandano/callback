"""Runner: prompts mirror the real tool payloads, host replies are parsed, table is exact."""

from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from langsmith.utils import LangSmithError

from evals import runner
from evals.checks import Check
from evals.runner import (
    CHECKS_ONLY_SKIP_MESSAGE,
    EvalRow,
    HostError,
    call_host,
    extract_json_object,
    extract_prompt,
    format_table,
    main,
    run_extract,
    run_tailor,
    tailor_prompt,
)
from evals.tailor_checks import TailorCase


@pytest.mark.parametrize(
    ("host", "port", "url"),
    [
        ("ollama", None, "http://127.0.0.1:11434/v1/chat/completions"),
        ("llamacpp", None, "http://127.0.0.1:8080/v1/chat/completions"),
        ("ollama", 12345, "http://127.0.0.1:12345/v1/chat/completions"),
        ("llamacpp", 8081, "http://127.0.0.1:8081/v1/chat/completions"),
    ],
)
def test_local_host_sends_chat_request(host, port, url, monkeypatch):
    seen = {}

    def open_request(request, *, timeout):
        seen.update(url=request.full_url, method=request.get_method(), timeout=timeout)
        seen["body"] = json.loads(request.data)
        seen["content_type"] = request.get_header("Content-type")
        return BytesIO(b'{"choices": [{"message": {"content": "MODEL REPLY"}}]}')

    def fake_opener(handler):
        seen["proxies"] = handler.proxies
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(runner, "build_opener", fake_opener, raising=False)
    reply = call_host(host, "chosen-model", "PROMPT", port=port)

    assert reply == "MODEL REPLY"
    assert seen == {
        "url": url,
        "method": "POST",
        "timeout": 900,
        "body": {
            "model": "chosen-model",
            "messages": [{"role": "user", "content": "PROMPT"}],
            "stream": False,
        },
        "content_type": "application/json",
        "proxies": {},
    }


@pytest.mark.parametrize("host", ["ollama", "llamacpp"])
def test_local_host_requires_model_before_fixture_work(host, monkeypatch, capsys):
    def forbidden():
        raise AssertionError("validation must precede git and fixture work")

    monkeypatch.setattr(runner, "_commit", forbidden)
    assert main(["--host", host]) == 1
    assert f"--model is required for --host {host}" in capsys.readouterr().err


@pytest.mark.parametrize(
    "flags",
    [
        ["--host", "ollama", "--model", " "],
        ["--host", "claude", "--model", ""],
        ["--host", "ollama", "--model", "m", "--port", "0"],
        ["--host", "llamacpp", "--model", "m", "--port", "-1"],
        ["--host", "ollama", "--model", "m", "--port", "65536"],
        ["--host", "claude", "--port", "8080"],
        ["--host", "codex", "--port", "8080"],
        ["--host", "hermes", "--port", "8080"],
        ["--host", "ollama", "--model", "m", "--provider", "openrouter"],
        ["--host", "hermes", "--provider", " "],
    ],
)
def test_invalid_host_arguments_fail_before_fixture_work(flags, monkeypatch, capsys):
    def forbidden():
        raise AssertionError("invalid options must not touch fixtures")

    monkeypatch.setattr(runner, "_commit", forbidden)
    assert main(flags) == 1
    assert capsys.readouterr().err


@pytest.mark.parametrize("port", [1, 65535])
def test_local_port_accepts_boundaries(port):
    args = runner._parse_args(["--host", "ollama", "--model", "m", "--port", str(port)])
    runner._validate_args(args)


def test_noninteger_port_is_an_argument_error():
    with pytest.raises(SystemExit) as exc:
        runner._parse_args(["--host", "ollama", "--model", "m", "--port", "abc"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "error",
    [
        URLError("connection refused"),
        HTTPError("http://127.0.0.1:11434", 404, "model not found", {}, None),
        TimeoutError("timed out"),
    ],
)
def test_local_connection_errors_reach_the_user(error, monkeypatch):
    def open_request(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        runner, "build_opener", lambda *_: SimpleNamespace(open=open_request), raising=False
    )
    with pytest.raises(HostError, match="ollama.*11434"):
        call_host("ollama", "m", "PROMPT")


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"choices": []}',
        b'{"choices": [{"message": {"content": null}}]}',
        b'{"choices": [{"message": {"content": " "}}]}',
    ],
)
def test_local_invalid_response_is_a_host_error(body, monkeypatch):
    monkeypatch.setattr(
        runner,
        "build_opener",
        lambda *_: SimpleNamespace(open=lambda *args, **kwargs: BytesIO(body)),
        raising=False,
    )
    with pytest.raises(HostError, match="ollama.*11434"):
        call_host("ollama", "m", "PROMPT")


@pytest.mark.parametrize("host", ["ollama", "llamacpp", "hermes"])
def test_new_hosts_checks_only_need_no_model_or_transport(host, tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    expected = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    _write_extract_fixture(extract_dir, "acme", expected)
    monkeypatch.setattr(runner, "EXTRACT_DIR", extract_dir)
    monkeypatch.setattr(runner, "_commit", lambda: "abc1234")

    def forbidden(*args, **kwargs):
        raise AssertionError("checks-only must stay offline")

    monkeypatch.setattr(runner, "call_host", forbidden)
    monkeypatch.setattr(runner.experiments, "record_extract", forbidden)
    assert main(["--host", host, "--checks-only", "--eval", "extract"]) == 0


def test_local_failure_clears_saved_reply_and_continues(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    expected = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    for board in ["a", "b"]:
        _write_extract_fixture(extract_dir, board, expected)
    monkeypatch.setattr(runner, "EXTRACT_DIR", extract_dir)
    replies = iter(
        [
            URLError("connection refused"),
            {"choices": [{"message": {"content": json.dumps(expected)}}]},
        ]
    )

    def open_request(*args, **kwargs):
        reply = next(replies)
        if isinstance(reply, URLError):
            raise reply
        return BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(runner, "build_opener", lambda *_: SimpleNamespace(open=open_request))
    rows = run_extract("ollama", "m", ["a", "b"], checks_only=False, run=None, commit="abc")
    saved = json.loads((extract_dir / "a.host.json").read_text())
    assert saved["output"] is None
    assert "connection refused" in saved["raw"]
    assert [(row.fixture, row.passed) for row in rows] == [("a", False), ("b", True)]


@pytest.mark.parametrize("model", [None, "chosen-model"])
@pytest.mark.parametrize("provider", [None, "openrouter"])
def test_hermes_calls_isolated_cli_with_stdin(model, provider):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"type":"result","exit_code":0,"text":"MODEL REPLY"}\n', stderr=""
        )

    assert call_host("hermes", model, "PROMPT", run=fake_run, provider=provider) == "MODEL REPLY"
    cmd, kwargs = calls[0]
    expected = [
        "hermes",
        "chat",
        "--query-file",
        "-",
        "--oneshot",
        "--quiet",
        "--format",
        "stream-json",
        "--safe-mode",
    ]
    if model:
        expected.extend(["--model", model])
    if provider:
        expected.extend(["--provider", provider])
    assert cmd == expected
    assert kwargs["input"] == "PROMPT"
    assert kwargs["timeout"] == 900
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["cwd"] != str(Path.cwd())


def test_hermes_reads_only_terminal_answer():
    stdout = "\n".join(
        [
            '{"type":"system","subtype":"init","model":"m"}',
            '{"type":"text","text":"a discarded draft"}',
            '{"type":"tool_use","name":"example"}',
            '{"type":"tool_result","name":"example","output":"tool text"}',
            '{"type":"result","exit_code":0,"text":"final answer"}',
        ]
    )
    assert runner._hermes_result(stdout) == "final answer"


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        "[]",
        '{"type":"text","text":"draft"}',
        '{"type":"result","exit_code":1,"text":"partial answer"}',
        '{"type":"result","exit_code":0,"text":"answer","error":"failed"}',
        '{"type":"result","exit_code":0,"text":null}',
        '{"type":"result","exit_code":0,"text":" "}',
        '{"type":"result","exit_code":0,"text":"one"}\n{"type":"result","exit_code":0,"text":"two"}',
    ],
)
def test_invalid_hermes_events_raise_host_error(stdout):
    with pytest.raises(HostError, match="hermes"):
        runner._hermes_result(stdout)


def test_codex_without_model_does_not_force_a_model():
    def fake_run(cmd, **kwargs):
        assert "-m" not in cmd
        Path(cmd[cmd.index("-o") + 1]).write_text("ANSWER")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    assert call_host("codex", None, "PROMPT", run=fake_run) == "ANSWER"


@pytest.mark.parametrize("host", ["claude", "codex", "hermes"])
def test_missing_cli_is_a_host_error(host):
    def missing(cmd, **kwargs):
        raise FileNotFoundError("not installed")

    with pytest.raises(HostError, match=f"{host}.*not installed"):
        call_host(host, None, "PROMPT", run=missing)


@pytest.mark.parametrize(
    ("host", "env", "filename", "config", "model", "provider"),
    [
        ("claude", "CLAUDE_CONFIG_DIR", "settings.json", '{"model":"sonnet"}', "sonnet", None),
        ("codex", "CODEX_HOME", "config.toml", 'model = "gpt-5.6-terra"', "gpt-5.6-terra", None),
        (
            "hermes",
            "HERMES_HOME",
            "config.yaml",
            "model:\n  default: chosen-model\n  provider: openrouter\n",
            "chosen-model",
            "openrouter",
        ),
    ],
)
def test_saved_harness_defaults_are_used_without_loading_other_settings(
    host, env, filename, config, model, provider, tmp_path, monkeypatch
):
    (tmp_path / filename).write_text(config)
    monkeypatch.setenv(env, str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_MODEL", raising=False)
    assert runner._harness_defaults(host) == (model, provider)


@pytest.mark.parametrize("host", ["claude", "codex", "hermes"])
def test_missing_harness_config_uses_native_defaults(host, tmp_path, monkeypatch):
    for env in ["CLAUDE_CONFIG_DIR", "CODEX_HOME", "HERMES_HOME"]:
        monkeypatch.setenv(env, str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_MODEL", raising=False)
    assert runner._harness_defaults(host) == (None, None)


def test_invalid_harness_config_is_not_silently_ignored(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text('model = "unterminated')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    with pytest.raises(HostError, match="codex.*config"):
        runner._harness_defaults("codex")


SECTIONS = {
    "summary": "Backend engineer.",
    "skills": {"flat": ["Python"], "categorized": {}},
    "experience": [
        {
            "company": "Acme Corp",
            "role": "Engineer",
            "start_date": "2021-03",
            "bullets": ["Built APIs in Python"],
        }
    ],
    "projects": [],
    "education": [],
    "contact": {"name": "Jane Doe"},
}
KEYWORDS = {
    "title": "Engineer",
    "required": ["Python", "Go"],
    "preferred": [],
    "required_years": 0.0,
}


def test_extract_json_object_finds_the_object_inside_prose():
    actual = extract_json_object('Sure! Here it is:\n```json\n{"a": 1, "b": [2]}\n```\nDone.')

    expected = {"a": 1, "b": [2]}
    assert actual == expected


def test_extract_json_object_returns_none_when_absent():
    actual = extract_json_object("no braces here")

    expected = None
    assert actual == expected


def test_extract_prompt_carries_protocol_and_jd():
    prompt = extract_prompt("JD BODY")

    actual = {
        "has_protocol": "Extract keywords from jd_text using this exact protocol" in prompt,
        "has_jd": "<jd_text>\nJD BODY\n</jd_text>" in prompt,
        "asks_for_json_only": "Respond with only the JSON object" in prompt,
    }

    expected = {"has_protocol": True, "has_jd": True, "asks_for_json_only": True}
    assert actual == expected


def test_tailor_prompt_carries_every_input():
    case = TailorCase(
        SECTIONS, KEYWORDS, {"index.md": "# Profile Index\n"}, {"expect_no_coverage": False}
    )
    prompt = tailor_prompt(case)

    actual = {
        "has_instructions": "V4 voice constraints" in prompt,
        "has_sections": json.dumps(SECTIONS, ensure_ascii=False, indent=2) in prompt,
        "has_keywords": json.dumps(KEYWORDS, ensure_ascii=False, indent=2) in prompt,
        "has_gaps": '"required_missing": [\n    "Go"\n  ]' in prompt,
        "has_page": "## index.md\n# Profile Index" in prompt,
        "has_schema": "section: str (summary | skills | experience | projects)" in prompt,
    }

    expected = {k: True for k in actual}
    assert actual == expected


def test_call_host_claude_reads_result_field():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["input"]))
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"result": '{"ok": 1}'}), stderr=""
        )

    reply = call_host("claude", None, "PROMPT", run=fake_run)

    actual = {"reply": reply, "calls": calls}
    expected = {
        "reply": '{"ok": 1}',
        "calls": [
            (
                [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    "--no-session-persistence",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                    "--tools",
                    "",
                    "--setting-sources",
                    "",
                ],
                "PROMPT",
            )
        ],
    }
    assert actual == expected


def test_call_host_claude_passes_model_flag():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "x"}), stderr="")

    call_host("claude", "sonnet", "P", run=fake_run)

    actual = calls
    expected = [
        [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            "",
            "--setting-sources",
            "",
            "--model",
            "sonnet",
        ]
    ]
    assert actual == expected


def test_call_host_codex_reads_last_message_file(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[cmd.index("-o") + 1]).write_text('codex says {"ok": 2}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    reply = call_host("codex", "gpt-5.6-terra", "P", run=fake_run)

    out_file = Path(calls[0][calls[0].index("-o") + 1])
    actual = {"reply": reply, "calls": calls}
    expected = {
        "reply": 'codex says {"ok": 2}',
        "calls": [
            [
                "codex",
                "exec",
                "-m",
                "gpt-5.6-terra",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--sandbox",
                "read-only",
                "-o",
                str(out_file),
            ]
        ],
    }
    assert actual == expected


def test_call_host_nonzero_exit_raises_with_stderr():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom: not logged in")

    with pytest.raises(HostError, match="claude exited 2: boom: not logged in"):
        call_host("claude", None, "P", run=fake_run)


def test_call_host_claude_raises_on_non_json_stdout():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    with pytest.raises(HostError, match="claude returned non-JSON stdout"):
        call_host("claude", None, "P", run=fake_run)


def test_call_host_claude_raises_when_reply_has_no_result():
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"is_error": True, "error": "rate_limited"}), stderr=""
        )

    with pytest.raises(HostError, match="claude reply has no result"):
        call_host("claude", None, "P", run=fake_run)


def test_format_table_lists_first_failure():
    rows = [
        EvalRow("extract", "ashby", [Check("valid_jd_data", True)]),
        EvalRow(
            "tailor",
            "jane-doe-backend",
            [Check("valid_output", True), Check("grounded", False, "ungrounded: ['70%']")],
        ),
        EvalRow(
            "extract",
            "greenhouse",
            [
                Check("valid_jd_data", True),
                Check(
                    "term_recall",
                    True,
                    "not evaluated: only 3 expected terms are still in the JD (content drift)",
                    skipped=True,
                ),
            ],
        ),
    ]

    actual = format_table(rows)

    expected = (
        "eval     fixture           score  result  first failing check / note\n"
        "extract  ashby             1/1    PASS    \n"
        "tailor   jane-doe-backend  1/2    FAIL    grounded: ungrounded: ['70%']\n"
        "extract  greenhouse        1/1    SKIP    not evaluated: only 3 expected terms are "
        "still in the JD (content drift)"
    )
    assert actual == expected


def test_eval_row_score_counts_only_non_skipped_checks():
    actual = {
        "passing": EvalRow("extract", "passing", [Check("valid", True)]).score,
        "failing": EvalRow("extract", "failing", [Check("valid", False)]).score,
        "mixed": EvalRow(
            "extract", "mixed", [Check("valid", True), Check("drift", True, skipped=True)]
        ).score,
        "all_skipped": EvalRow(
            "extract", "all-skipped", [Check("drift", True, skipped=True)]
        ).score,
    }

    expected = {"passing": "1/1", "failing": "0/1", "mixed": "1/1", "all_skipped": "—"}

    assert actual == expected


def test_run_extract_writes_host_file_and_checks(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    jd = "Engineer at Acme. Requirements: Python, Go."
    fixture_jd = {
        "title": "Engineer",
        "required": ["Python", "Go"],
        "preferred": [],
        "required_years": 0.0,
    }
    (extract_dir / "acme.md").write_text(jd, encoding="utf-8")
    (extract_dir / "acme.expected.json").write_text(json.dumps(fixture_jd), encoding="utf-8")
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    reply = json.dumps({"result": json.dumps(fixture_jd)})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    rows = run_extract("claude", None, ["acme"], checks_only=False, run=fake_run, commit="abc1234")

    actual = {
        "rows": [(r.eval_name, r.fixture, r.passed) for r in rows],
        "host_file": json.loads((extract_dir / "acme.host.json").read_text(encoding="utf-8")),
    }
    expected = {
        "rows": [("extract", "acme", True)],
        "host_file": {
            "host": "claude",
            "model": "default",
            "commit": "abc1234",
            "ran_at": "2026-09-06T00:00:00+00:00",
            "raw": json.dumps(fixture_jd),
            "output": fixture_jd,
        },
    }
    assert actual == expected


def test_run_extract_continues_after_host_failure(tmp_path, monkeypatch, caplog):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    fixture_jd = {
        "title": "Engineer",
        "required": ["Python"],
        "preferred": [],
        "required_years": 0.0,
    }
    for board in ("a", "b"):
        (extract_dir / f"{board}.md").write_text(
            "Engineer. Requirements: Python.", encoding="utf-8"
        )
        (extract_dir / f"{board}.expected.json").write_text(
            json.dumps(fixture_jd), encoding="utf-8"
        )
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    reply = json.dumps({"result": json.dumps(fixture_jd)})
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd, 900)
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    with caplog.at_level("WARNING", logger="callback.evals"):
        rows = run_extract(
            "claude", None, ["a", "b"], checks_only=False, run=fake_run, commit="abc1234"
        )

    actual = [(r.fixture, r.passed, (r.first_failure or "").split(":")[0]) for r in rows]
    expected = [("a", False, "host_call"), ("b", True, "")]
    assert actual == expected


def test_host_call_failure_discards_a_stale_host_file(tmp_path, monkeypatch):
    """A prior successful run's host.json must not survive a fresh host-call failure: an
    unnoticed stale output would let LangSmith/--checks-only replay it as if it were current."""
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    fixture_jd = {
        "title": "Engineer",
        "required": ["Python"],
        "preferred": [],
        "required_years": 0.0,
    }
    (extract_dir / "acme.md").write_text("Engineer. Requirements: Python.", encoding="utf-8")
    (extract_dir / "acme.expected.json").write_text(json.dumps(fixture_jd), encoding="utf-8")
    (extract_dir / "acme.host.json").write_text(
        json.dumps(
            {
                "host": "claude",
                "model": "default",
                "commit": "old0000",
                "ran_at": "2026-01-01T00:00:00+00:00",
                "raw": '{"title": "Stale"}',
                "output": {"title": "Stale"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in")

    run_extract("claude", None, ["acme"], checks_only=False, run=fake_run, commit="abc1234")

    actual = json.loads((extract_dir / "acme.host.json").read_text(encoding="utf-8"))
    expected = {
        "host": "claude",
        "model": "default",
        "commit": "abc1234",
        "ran_at": "2026-09-06T00:00:00+00:00",
        "raw": "HostError: claude exited 1: not logged in",
        "output": None,
    }
    assert actual == expected


def test_run_extract_checks_only_reads_existing_output(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    fixture_jd = {
        "title": "Engineer",
        "required": ["Python"],
        "preferred": [],
        "required_years": 0.0,
    }
    (extract_dir / "acme.md").write_text("Engineer. Requirements: Python.", encoding="utf-8")
    (extract_dir / "acme.expected.json").write_text(json.dumps(fixture_jd), encoding="utf-8")
    (extract_dir / "acme.host.json").write_text(
        json.dumps({"output": {"title": "Engineer", "required": ["Python"]}})
    )
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)

    def never(cmd, **kwargs):
        raise AssertionError("checks_only must not call the host")

    rows = run_extract("claude", None, ["acme"], checks_only=True, run=never, commit="abc1234")

    actual = [(r.fixture, r.passed, r.first_failure) for r in rows]

    expected = [("acme", True, None)]
    assert actual == expected


def test_run_extract_checks_only_without_output_is_a_failed_row(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    (extract_dir / "acme.md").write_text("x", encoding="utf-8")
    (extract_dir / "acme.expected.json").write_text(
        json.dumps({"required": ["x"]}), encoding="utf-8"
    )
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)

    rows = run_extract("claude", None, ["acme"], checks_only=True, run=None, commit="abc1234")

    actual = [(r.fixture, r.passed, r.first_failure) for r in rows]

    expected = [
        ("acme", False, "host_output_present: acme.host.json missing; run without --checks-only")
    ]
    assert actual == expected


def test_run_tailor_writes_host_file_and_checks(tmp_path, monkeypatch):
    case_dir = tmp_path / "tailor" / "jane"
    (case_dir / "wiki" / "experience").mkdir(parents=True)
    (case_dir / "sections.json").write_text(json.dumps(SECTIONS), encoding="utf-8")
    (case_dir / "keywords.json").write_text(json.dumps(KEYWORDS), encoding="utf-8")
    (case_dir / "constraints.json").write_text(
        json.dumps({"expect_no_coverage": True}), encoding="utf-8"
    )
    (case_dir / "wiki" / "index.md").write_text("# Profile Index\n", encoding="utf-8")
    (case_dir / "wiki" / "experience" / "story-001.md").write_text("story", encoding="utf-8")
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    host_output = {"edits": [], "no_coverage": True}
    reply = json.dumps({"result": json.dumps(host_output)})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    rows = run_tailor("claude", None, [case_dir], checks_only=False, run=fake_run, commit="abc1234")

    actual = {
        "rows": [(r.eval_name, r.fixture, r.passed) for r in rows],
        "host_file": json.loads((case_dir / "host.json").read_text(encoding="utf-8")),
    }
    expected = {
        "rows": [("tailor", "jane", True)],
        "host_file": {
            "host": "claude",
            "model": "default",
            "commit": "abc1234",
            "ran_at": "2026-09-06T00:00:00+00:00",
            "raw": json.dumps(host_output),
            "output": host_output,
        },
    }
    assert actual == expected


def _write_extract_fixture(extract_dir: Path, board: str, expected: dict) -> None:
    extract_dir.mkdir(exist_ok=True)
    (extract_dir / f"{board}.md").write_text("Engineer. Requirements: Python.", encoding="utf-8")
    (extract_dir / f"{board}.expected.json").write_text(json.dumps(expected), encoding="utf-8")
    (extract_dir / f"{board}.host.json").write_text(
        json.dumps({"output": expected}), encoding="utf-8"
    )
    sources = (
        json.loads((extract_dir / "sources.json").read_text(encoding="utf-8"))
        if (extract_dir / "sources.json").exists()
        else []
    )
    if board not in sources:
        sources.append(board)
    (extract_dir / "sources.json").write_text(json.dumps(sources), encoding="utf-8")


def test_main_fails_when_a_case_filter_matches_nothing(tmp_path, monkeypatch, capsys):
    extract_dir = tmp_path / "extract"
    fixture_jd = {
        "title": "Engineer",
        "required": ["Python"],
        "preferred": [],
        "required_years": 0.0,
    }
    _write_extract_fixture(extract_dir, "acme", fixture_jd)
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")

    actual = main(["--checks-only", "--no-langsmith", "--eval", "extract", "--case", "nope"])

    expected = 1
    assert actual == expected
    assert "no extract fixtures match --case ['nope']" in capsys.readouterr().err


def test_checks_only_never_records_a_langsmith_experiment(tmp_path, monkeypatch, caplog):
    extract_dir = tmp_path / "extract"
    expected = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    _write_extract_fixture(extract_dir, "acme", expected)
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")

    def sentinel(*args, **kwargs):
        raise AssertionError("record_extract must not be called during --checks-only")

    monkeypatch.setattr(runner.experiments, "record_extract", sentinel)

    with caplog.at_level("WARNING", logger="callback.evals"):
        exit_code = main(["--checks-only", "--eval", "extract"])

    assert exit_code == 0
    assert CHECKS_ONLY_SKIP_MESSAGE in caplog.messages


def test_langsmith_failure_is_logged_and_local_results_still_print(tmp_path, monkeypatch, caplog):
    extract_dir = tmp_path / "extract"
    expected = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    _write_extract_fixture(extract_dir, "acme", expected)
    reply = json.dumps({"result": json.dumps(expected)})
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr=""),
    )

    def raise_auth_error(*args, **kwargs):
        raise LangSmithError("auth")

    monkeypatch.setattr(runner.experiments, "record_extract", raise_auth_error)

    with caplog.at_level("WARNING", logger="callback.evals"):
        exit_code = main(["--eval", "extract"])

    assert exit_code == 0
    assert any(
        "extract: LangSmith recording failed (auth); local results kept; experiment not recorded"
        in m
        for m in caplog.messages
    )
