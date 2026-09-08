"""Record one runner invocation as a LangSmith experiment.

Fixtures in git stay the source of truth; LangSmith only keeps the history so two
commits or two models can be compared side by side. The dataset holds one example
per fixture (uploaded once, matched by `fixture`), the evaluators replay the
deterministic checks already computed by the runner, and the target is a lookup
of the saved host output. No model is called here.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from langsmith import Client, evaluate

from evals.cases import case_dirs, case_id
from evals.tailor_checks import TailorCase

if TYPE_CHECKING:
    from evals.runner import EvalRow

logger = logging.getLogger("callback.evals")

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
DATASET_PREFIX = "callback-evals-"
MISSING_KEY_MESSAGE = (
    "LangSmith recording skipped: LANGSMITH_API_KEY is not set in this shell "
    "(`callback config env list` shows the value stored for the MCP hosts); "
    "results were printed only"
)


def _dataset(client, name: str):
    if client.has_dataset(dataset_name=name):
        return client.read_dataset(dataset_name=name)
    logger.info("creating LangSmith dataset %s", name)
    return client.create_dataset(name, description="callback eval fixtures (source of truth: git)")


def _upsert_examples(client, dataset, inputs: dict[str, dict]) -> list:
    existing = {e.inputs.get("fixture"): e for e in client.list_examples(dataset_id=dataset.id)}
    for fixture, fixture_inputs in inputs.items():
        new_inputs = {"fixture": fixture, **fixture_inputs}
        example = existing.get(fixture)
        if example is None:
            client.create_example(inputs=new_inputs, outputs={}, dataset_id=dataset.id)
        elif {k: v for k, v in example.inputs.items() if k != "fixture"} != fixture_inputs:
            client.update_example(example_id=example.id, inputs=new_inputs)
            logger.info("refreshed stale LangSmith example for fixture %s", fixture)
    return [
        e for e in client.list_examples(dataset_id=dataset.id) if e.inputs.get("fixture") in inputs
    ]


def record(
    eval_name: str,
    rows: list[EvalRow],
    inputs: dict[str, dict],
    outputs: dict[str, dict | None],
    run_meta: dict,
) -> str | None:
    """Upload missing fixtures, replay the checks as evaluators, return the experiment name."""
    if not os.environ.get("LANGSMITH_API_KEY"):
        logger.warning(MISSING_KEY_MESSAGE)
        return None
    client = Client()
    dataset = _dataset(client, f"{DATASET_PREFIX}{eval_name}")
    logger.info(
        "uploading %d fixture inputs to LangSmith dataset %s: %s",
        len(inputs),
        dataset.name,
        sorted(inputs),
    )
    examples = _upsert_examples(client, dataset, inputs)
    checks_by_fixture = {row.fixture: row.checks for row in rows}

    def target(example_inputs: dict) -> dict | None:
        return outputs[example_inputs["fixture"]]

    def replay_checks(run, example) -> dict:
        checks = checks_by_fixture[example.inputs["fixture"]]
        return {
            "results": [
                {"key": c.name, "score": int(c.passed), "comment": c.detail} for c in checks
            ]
        }

    prefix = f"{run_meta['commit']}-{run_meta['host']}-{run_meta['model']}"
    # langsmith types evaluate()'s target as returning dict, not dict | None, and matches
    # target's Callable against its Union[target, ..., tuple[...]] overloads too strictly;
    # both work at runtime (a missing output is a real possibility, replayed as a failed check).
    result = evaluate(  # pyright: ignore[reportCallIssue]
        target,  # pyright: ignore[reportArgumentType]
        data=examples,
        evaluators=[replay_checks],
        experiment_prefix=prefix,
        metadata=run_meta,
        client=client,
    )
    logger.info("LangSmith experiment %s recorded", result.experiment_name)
    return result.experiment_name


def _saved_output(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("output")


def record_extract(rows: list[EvalRow], run_meta: dict) -> str | None:
    inputs = {}
    outputs = {}
    for r in rows:
        inputs[r.fixture] = {
            "jd_text": (EXTRACT_DIR / f"{r.fixture}.md").read_text(encoding="utf-8")
        }
        outputs[r.fixture] = _saved_output(EXTRACT_DIR / f"{r.fixture}.host.json")
    return record("extract", rows, inputs, outputs, run_meta)


def record_tailor(rows: list[EvalRow], run_meta: dict) -> str | None:
    dirs = {case_id(d): d for d in case_dirs("tailor")}
    inputs = {}
    outputs = {}
    for row in rows:
        case = TailorCase.from_dir(dirs[row.fixture])
        inputs[row.fixture] = {
            "sections": case.sections,
            "keywords": case.keywords,
            "wiki_pages": case.wiki_pages,
            "constraints": case.constraints,
        }
        outputs[row.fixture] = _saved_output(dirs[row.fixture] / "host.json")
    return record("tailor", rows, inputs, outputs, run_meta)
