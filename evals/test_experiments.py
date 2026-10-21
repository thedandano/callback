"""LangSmith recording: skipped loudly without a key, otherwise dataset upsert + evaluate."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from evals import experiments
from evals.checks import Check
from evals.runner import EvalRow


def test_record_skips_with_warning_when_key_missing(monkeypatch, caplog):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    rows = [EvalRow("extract", "ashby", [Check("valid_jd_data", True)])]

    with caplog.at_level(logging.WARNING, logger="callback.evals"):
        actual = experiments.record(
            "extract", rows, {"ashby": {"jd_text": "x"}}, {"ashby": {"a": 1}}, {"commit": "abc"}
        )

    expected = None
    assert actual == expected
    assert caplog.messages == [
        "LangSmith recording skipped: LANGSMITH_API_KEY is not set in this shell "
        "(`callback config env list` shows the value stored for the MCP hosts); "
        "results were printed only"
    ]


def test_record_extract_includes_saved_pass2_output_when_present(tmp_path, monkeypatch):
    (tmp_path / "ashby.md").write_text("job description", encoding="utf-8")
    (tmp_path / "ashby.host.json").write_text('{"output":{"title":"Engineer"}}', encoding="utf-8")
    (tmp_path / "ashby.resp.host.json").write_text(
        '{"output":{"key_responsibilities":["agent loop"]}}', encoding="utf-8"
    )
    (tmp_path / "cedar.md").write_text("second job description", encoding="utf-8")
    (tmp_path / "cedar.host.json").write_text('{"output":{"title":"Developer"}}', encoding="utf-8")
    monkeypatch.setattr(experiments, "EXTRACT_DIR", tmp_path)
    captured = {}

    def fake_record(eval_name, rows, inputs, outputs, run_meta):
        captured.update(eval_name=eval_name, inputs=inputs, outputs=outputs, run_meta=run_meta)
        return "recorded"

    monkeypatch.setattr(experiments, "record", fake_record)
    rows = [
        EvalRow("extract", "ashby", [Check("valid_jd_data", True)]),
        EvalRow("extract", "cedar", [Check("valid_jd_data", True)]),
    ]

    actual = experiments.record_extract(rows, {"commit": "abc"})

    expected = "recorded"
    assert actual == expected
    assert captured == {
        "eval_name": "extract",
        "inputs": {
            "ashby": {"jd_text": "job description"},
            "cedar": {"jd_text": "second job description"},
        },
        "outputs": {
            "ashby": {
                "title": "Engineer",
                "pass2": {"key_responsibilities": ["agent loop"]},
            },
            "cedar": {"title": "Developer"},
        },
        "run_meta": {"commit": "abc"},
    }


class FakeClient:
    def __init__(self):
        self.datasets = {}
        self.examples = []
        self._next_id = 0

    def has_dataset(self, *, dataset_name):
        return dataset_name in self.datasets

    def create_dataset(self, dataset_name, *, description=""):
        self.datasets[dataset_name] = SimpleNamespace(id=f"id-{dataset_name}", name=dataset_name)
        return self.datasets[dataset_name]

    def read_dataset(self, *, dataset_name):
        return self.datasets[dataset_name]

    def create_example(self, *, inputs, outputs, dataset_id):
        self._next_id += 1
        self.examples.append(
            SimpleNamespace(
                id=f"ex-{self._next_id}", inputs=inputs, outputs=outputs, dataset_id=dataset_id
            )
        )

    def update_example(self, *, example_id, inputs):
        for example in self.examples:
            if example.id == example_id:
                example.inputs = inputs
                return

    def list_examples(self, *, dataset_id):
        return [e for e in self.examples if e.dataset_id == dataset_id]


def test_record_upserts_examples_and_evaluates(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    client = FakeClient()
    client.create_dataset("callback-evals-extract")
    client.create_example(
        inputs={"fixture": "ashby", "jd_text": "old"},
        outputs={},
        dataset_id="id-callback-evals-extract",
    )
    monkeypatch.setattr(experiments, "Client", lambda: client)
    seen = {}

    def fake_evaluate(target, *, data, evaluators, experiment_prefix, metadata, client):
        example = data[0]
        seen["fixtures"] = [e.inputs["fixture"] for e in data]
        seen["target"] = target(example.inputs)
        seen["eval"] = evaluators[0](SimpleNamespace(outputs=seen["target"]), example)
        seen["prefix"] = experiment_prefix
        seen["metadata"] = metadata
        return SimpleNamespace(experiment_name=f"{experiment_prefix}-1")

    monkeypatch.setattr(experiments, "evaluate", fake_evaluate)
    rows = [
        EvalRow(
            "extract",
            "ashby",
            [Check("valid_jd_data", True), Check("title_exact", False, "host 'a' != expected 'b'")],
        ),
        EvalRow("extract", "cedar", [Check("valid_jd_data", True)]),
    ]
    inputs = {"ashby": {"jd_text": "old"}, "cedar": {"jd_text": "new"}}
    outputs: dict[str, dict | None] = {"ashby": {"title": "a"}, "cedar": {"title": "c"}}

    name = experiments.record(
        "extract",
        rows,
        inputs,
        outputs,
        {"commit": "abc1234", "host": "claude", "model": "default"},
    )

    actual = {
        "name": name,
        "examples": [e.inputs["fixture"] for e in client.examples],
        "seen": seen,
    }
    expected = {
        "name": "abc1234-claude-default-1",
        "examples": ["ashby", "cedar"],
        "seen": {
            "fixtures": ["ashby", "cedar"],
            "target": {"title": "a"},
            "eval": {
                "results": [
                    {"key": "valid_jd_data", "score": 1, "comment": ""},
                    {"key": "title_exact", "score": 0, "comment": "host 'a' != expected 'b'"},
                ]
            },
            "prefix": "abc1234-claude-default",
            "metadata": {"commit": "abc1234", "host": "claude", "model": "default"},
        },
    }
    assert actual == expected


def _fake_evaluate(target, *, data, evaluators, experiment_prefix, metadata, client):
    return SimpleNamespace(experiment_name=f"{experiment_prefix}-1")


def test_upsert_examples_refreshes_a_stale_example(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    client = FakeClient()
    client.create_dataset("callback-evals-extract")
    client.create_example(
        inputs={"fixture": "ashby", "jd_text": "old"},
        outputs={},
        dataset_id="id-callback-evals-extract",
    )
    client.create_example(
        inputs={"fixture": "cedar", "jd_text": "same"},
        outputs={},
        dataset_id="id-callback-evals-extract",
    )
    monkeypatch.setattr(experiments, "Client", lambda: client)
    monkeypatch.setattr(experiments, "evaluate", _fake_evaluate)
    updated_fixtures: list[str] = []
    real_update_example = client.update_example

    def spy_update_example(*, example_id, inputs):
        updated_fixtures.append(inputs["fixture"])
        real_update_example(example_id=example_id, inputs=inputs)

    monkeypatch.setattr(client, "update_example", spy_update_example)
    rows = [
        EvalRow("extract", "ashby", [Check("valid_jd_data", True)]),
        EvalRow("extract", "cedar", [Check("valid_jd_data", True)]),
    ]
    inputs = {"ashby": {"jd_text": "new"}, "cedar": {"jd_text": "same"}}
    outputs: dict[str, dict | None] = {"ashby": {"title": "a"}, "cedar": {"title": "c"}}
    run_meta = {"commit": "abc1234", "host": "claude", "model": "default"}

    with caplog.at_level(logging.INFO, logger="callback.evals"):
        experiments.record("extract", rows, inputs, outputs, run_meta)

    actual = {
        "inputs": {e.inputs["fixture"]: e.inputs for e in client.examples},
        "updated_fixtures": updated_fixtures,
        "refresh_logged": "refreshed stale LangSmith example for fixture ashby" in caplog.messages,
    }
    expected = {
        "inputs": {
            "ashby": {"fixture": "ashby", "jd_text": "new"},
            "cedar": {"fixture": "cedar", "jd_text": "same"},
        },
        "updated_fixtures": ["ashby"],
        "refresh_logged": True,
    }
    assert actual == expected
