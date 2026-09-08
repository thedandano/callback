"""E2: the host's tailoring output for every case passes the deterministic checks.

Host outputs are written by scripts/run_evals.py; this test only reads them, so it
is marked local (CI never calls a model). A case with no host.json is skipped
with a reason, never silently passed.
"""

from __future__ import annotations

import json

import pytest

from evals.cases import case_dirs, case_id
from evals.checks import first_failure
from evals.tailor_checks import TailorCase, run_checks

CASES = case_dirs("tailor")


@pytest.mark.local
@pytest.mark.parametrize("case_dir", CASES, ids=[case_id(c) for c in CASES])
def test_host_tailor_output_passes_checks(case_dir):
    host_path = case_dir / "host.json"
    if not host_path.exists():
        pytest.skip(f"{host_path} missing; run scripts/run_evals.py --eval tailor")
    host = json.loads(host_path.read_text(encoding="utf-8"))
    checks = run_checks(TailorCase.from_dir(case_dir), host["output"])

    actual = first_failure(checks)

    expected = None
    assert actual == expected
