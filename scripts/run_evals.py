#!/usr/bin/env python3
"""Run callback's LLM evals (E1 extract, E2 tailor) against a host model and print one table.

Usage:
  uv run python scripts/run_evals.py                      # claude, default model, both evals
  uv run python scripts/run_evals.py --host codex --model gpt-5.6-terra --eval tailor
  uv run python scripts/run_evals.py --checks-only        # re-check saved outputs, no model call
  uv run python scripts/run_evals.py --case reddit --case jane-doe-backend

Host outputs land next to their fixtures (evals/extract/<board>.host.json,
<case>/host.json). Then: uv run pytest -m local evals/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
