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


class FakeClient:
    def __init__(self):
        self.datasets = {}
        self.examples = []

    def has_dataset(self, *, dataset_name):
        return dataset_name in self.datasets

    def create_dataset(self, dataset_name, *, description=""):
        self.datasets[dataset_name] = SimpleNamespace(id=f"id-{dataset_name}", name=dataset_name)
        return self.datasets[dataset_name]

    def read_dataset(self, *, dataset_name):
        return self.datasets[dataset_name]

    def create_example(self, *, inputs, outputs, dataset_id):
        self.examples.append(SimpleNamespace(inputs=inputs, outputs=outputs, dataset_id=dataset_id))

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
            [Check("valid_jd_data", True), Check("title_exact", False, "host 'a' != golden 'b'")],
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
                    {"key": "title_exact", "score": 0, "comment": "host 'a' != golden 'b'"},
                ]
            },
            "prefix": "abc1234-claude-default",
            "metadata": {"commit": "abc1234", "host": "claude", "model": "default"},
        },
    }
    assert actual == expected
