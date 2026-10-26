"""E1: the host's keyword extraction for every board passes the deterministic checks.

Host outputs are written by scripts/run_evals.py; marked local (CI never calls
a model). A board with no host output is skipped with a reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from callback.jd_data import clean_responsibilities
from evals.checks import first_failure
from evals.extract_checks import run_checks
from evals.runner import merge_passes

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
BOARDS = sorted(json.loads((EXTRACT_DIR / "sources.json").read_text(encoding="utf-8")))


@pytest.mark.local
@pytest.mark.parametrize("board", BOARDS)
def test_host_extraction_passes_checks(board):
    host_path = EXTRACT_DIR / f"{board}.host.json"
    if not host_path.exists():
        pytest.skip(f"{host_path} missing; run scripts/run_evals.py --eval extract")
    host = json.loads(host_path.read_text(encoding="utf-8"))
    expected_jd = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))
    jd_text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
    response_path = EXTRACT_DIR / f"{board}.resp.host.json"
    grade_responsibilities = response_path.exists()
    output = host["output"]
    if grade_responsibilities:
        response = json.loads(response_path.read_text(encoding="utf-8"))["output"]
        output = merge_passes(
            output,
            {"key_responsibilities": clean_responsibilities(response.get("key_responsibilities"))},
        )
    checks = run_checks(
        json.dumps(output), expected_jd, jd_text, grade_responsibilities=grade_responsibilities
    )

    actual = first_failure(checks)

    expected = None
    assert actual == expected
