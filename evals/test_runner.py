"""Runner: prompts mirror the real tool payloads, host replies are parsed, table is exact."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evals.checks import Check
from evals.runner import (
    EvalRow,
    HostError,
    call_host,
    extract_json_object,
    extract_prompt,
    format_table,
    run_extract,
    run_tailor,
    tailor_prompt,
)
from evals.tailor_checks import TailorCase

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
    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_text('codex says {"ok": 2}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    actual = call_host("codex", "gpt-5.6-terra", "P", run=fake_run)

    expected = 'codex says {"ok": 2}'
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
            "public:jane-doe-backend",
            [Check("valid_output", True), Check("grounded", False, "ungrounded: ['70%']")],
        ),
    ]

    actual = format_table(rows)

    expected = (
        "eval     fixture                  result  first failing check\n"
        "extract  ashby                    PASS    \n"
        "tailor   public:jane-doe-backend  FAIL    grounded: ungrounded: ['70%']"
    )
    assert actual == expected


def test_run_extract_writes_host_file_and_checks(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    jd = "Engineer at Acme. Requirements: Python, Go."
    golden = {
        "title": "Engineer",
        "required": ["Python", "Go"],
        "preferred": [],
        "required_years": 0.0,
    }
    (extract_dir / "acme.md").write_text(jd, encoding="utf-8")
    (extract_dir / "acme.golden.json").write_text(json.dumps(golden), encoding="utf-8")
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    reply = json.dumps({"result": json.dumps(golden)})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    rows = run_extract("claude", None, ["acme"], checks_only=False, run=fake_run)

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
            "raw": json.dumps(golden),
            "output": golden,
        },
    }
    assert actual == expected


def test_run_extract_continues_after_host_failure(tmp_path, monkeypatch, caplog):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    golden = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    for board in ("a", "b"):
        (extract_dir / f"{board}.md").write_text(
            "Engineer. Requirements: Python.", encoding="utf-8"
        )
        (extract_dir / f"{board}.golden.json").write_text(json.dumps(golden), encoding="utf-8")
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    reply = json.dumps({"result": json.dumps(golden)})
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd, 900)
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    with caplog.at_level("WARNING", logger="callback.evals"):
        rows = run_extract("claude", None, ["a", "b"], checks_only=False, run=fake_run)

    actual = [(r.fixture, r.passed, (r.first_failure or "").split(":")[0]) for r in rows]
    expected = [("a", False, "host_call"), ("b", True, "")]
    assert actual == expected


def test_run_extract_checks_only_reads_existing_output(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    golden = {"title": "Engineer", "required": ["Python"], "preferred": [], "required_years": 0.0}
    (extract_dir / "acme.md").write_text("Engineer. Requirements: Python.", encoding="utf-8")
    (extract_dir / "acme.golden.json").write_text(json.dumps(golden), encoding="utf-8")
    (extract_dir / "acme.host.json").write_text(
        json.dumps({"output": {"title": "Engineer", "required": ["Python"]}})
    )
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)

    def never(cmd, **kwargs):
        raise AssertionError("checks_only must not call the host")

    rows = run_extract("claude", None, ["acme"], checks_only=True, run=never)

    actual = [(r.fixture, r.passed, r.first_failure) for r in rows]

    expected = [("acme", True, None)]
    assert actual == expected


def test_run_extract_checks_only_without_output_is_a_failed_row(tmp_path, monkeypatch):
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    (extract_dir / "acme.md").write_text("x", encoding="utf-8")
    (extract_dir / "acme.golden.json").write_text(json.dumps({"required": ["x"]}), encoding="utf-8")
    monkeypatch.setattr("evals.runner.EXTRACT_DIR", extract_dir)

    rows = run_extract("claude", None, ["acme"], checks_only=True, run=None)

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
    monkeypatch.setattr("evals.runner._commit", lambda: "abc1234")
    monkeypatch.setattr("evals.runner._now", lambda: "2026-09-06T00:00:00+00:00")
    host_output = {"edits": [], "no_coverage": True}
    reply = json.dumps({"result": json.dumps(host_output)})

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=reply, stderr="")

    rows = run_tailor("claude", None, [case_dir], checks_only=False, run=fake_run)

    actual = {
        "rows": [(r.eval_name, r.fixture, r.passed) for r in rows],
        "host_file": json.loads((case_dir / "host.json").read_text(encoding="utf-8")),
    }
    expected = {
        "rows": [("tailor", "private:jane", True)],
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
