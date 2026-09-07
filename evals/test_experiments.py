"""LangSmith recording: skipped loudly without a key, otherwise dataset upsert + evaluate."""

from __future__ import annotations

import json
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


def _fake_evaluate(target, *, data, evaluators, experiment_prefix, metadata, client):
    return SimpleNamespace(experiment_name=f"{experiment_prefix}-1")


def test_private_inputs_are_withheld_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    monkeypatch.setattr(experiments, "evaluate", _fake_evaluate)
    public_dir, private_dir = tmp_path / "x", tmp_path / "y"
    public_dir.mkdir()
    private_dir.mkdir()
    monkeypatch.setattr(experiments, "case_dirs", lambda kind: [public_dir, private_dir])
    monkeypatch.setattr(
        experiments, "case_id", lambda d: "public:x" if d is public_dir else "private:y"
    )
    fake_case = SimpleNamespace(
        sections={"s": 1}, keywords={"k": 1}, wiki_pages={"w": "1"}, constraints={"c": 1}
    )
    monkeypatch.setattr(experiments.TailorCase, "from_dir", staticmethod(lambda d: fake_case))
    rows = [
        EvalRow("tailor", "public:x", [Check("valid_output", True)]),
        EvalRow("tailor", "private:y", [Check("valid_output", True)]),
    ]
    run_meta = {"commit": "abc1234", "host": "claude", "model": "default"}

    withheld_client = FakeClient()
    monkeypatch.setattr(experiments, "Client", lambda: withheld_client)
    experiments.record_tailor(rows, run_meta)

    uploaded_client = FakeClient()
    monkeypatch.setattr(experiments, "Client", lambda: uploaded_client)
    experiments.record_tailor(rows, run_meta, upload_private=True)

    actual = {
        "withheld_by_default": {e.inputs["fixture"]: e.inputs for e in withheld_client.examples},
        "uploaded_when_requested": {
            e.inputs["fixture"]: e.inputs for e in uploaded_client.examples
        },
    }
    expected = {
        "withheld_by_default": {
            "public:x": {
                "fixture": "public:x",
                "sections": {"s": 1},
                "keywords": {"k": 1},
                "wiki_pages": {"w": "1"},
                "constraints": {"c": 1},
            },
            "private:y": {"fixture": "private:y", "scope": "private"},
        },
        "uploaded_when_requested": {
            "public:x": {
                "fixture": "public:x",
                "sections": {"s": 1},
                "keywords": {"k": 1},
                "wiki_pages": {"w": "1"},
                "constraints": {"c": 1},
            },
            "private:y": {
                "fixture": "private:y",
                "sections": {"s": 1},
                "keywords": {"k": 1},
                "wiki_pages": {"w": "1"},
                "constraints": {"c": 1},
            },
        },
    }
    assert actual == expected


def test_record_tailor_withholds_private_host_outputs(monkeypatch, tmp_path):
    """A withheld fixture's target output must also be redacted: the evaluators replay the
    already-computed checks, so they never need the real host output."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "k")
    public_dir, private_dir = tmp_path / "x", tmp_path / "y"
    public_dir.mkdir()
    private_dir.mkdir()
    (public_dir / "host.json").write_text(json.dumps({"output": {"edits": ["public"]}}))
    (private_dir / "host.json").write_text(json.dumps({"output": {"edits": ["private"]}}))
    monkeypatch.setattr(experiments, "case_dirs", lambda kind: [public_dir, private_dir])
    monkeypatch.setattr(
        experiments, "case_id", lambda d: "public:x" if d is public_dir else "private:y"
    )
    fake_case = SimpleNamespace(sections={}, keywords={}, wiki_pages={}, constraints={})
    monkeypatch.setattr(experiments.TailorCase, "from_dir", staticmethod(lambda d: fake_case))
    rows = [
        EvalRow("tailor", "public:x", [Check("valid_output", True)]),
        EvalRow("tailor", "private:y", [Check("valid_output", True)]),
    ]
    run_meta = {"commit": "abc1234", "host": "claude", "model": "default"}
    monkeypatch.setattr(experiments, "Client", lambda: FakeClient())
    seen = {}

    def fake_evaluate(target, *, data, evaluators, experiment_prefix, metadata, client):
        seen["outputs"] = {e.inputs["fixture"]: target(e.inputs) for e in data}
        return SimpleNamespace(experiment_name="x")

    monkeypatch.setattr(experiments, "evaluate", fake_evaluate)

    experiments.record_tailor(rows, run_meta)

    actual = seen["outputs"]
    expected = {"public:x": {"edits": ["public"]}, "private:y": {"scope": "private"}}
    assert actual == expected


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
