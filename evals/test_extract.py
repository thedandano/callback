"""E1: the host's keyword extraction for every board passes the deterministic checks.

Host outputs are written by scripts/run_evals.py; marked local (CI never calls
a model). A board with no host output is skipped with a reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.checks import first_failure
from evals.extract_checks import run_checks

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
BOARDS = sorted(json.loads((EXTRACT_DIR / "sources.json").read_text(encoding="utf-8")))


@pytest.mark.local
@pytest.mark.parametrize("board", BOARDS)
def test_host_extraction_passes_checks(board):
    host_path = EXTRACT_DIR / f"{board}.host.json"
    if not host_path.exists():
        pytest.skip(f"{host_path} missing; run scripts/run_evals.py --eval extract")
    host = json.loads(host_path.read_text(encoding="utf-8"))
    golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text(encoding="utf-8"))
    jd_text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
    checks = run_checks(json.dumps(host["output"]), golden, jd_text)

    actual = first_failure(checks)

    expected = None
    assert actual == expected
