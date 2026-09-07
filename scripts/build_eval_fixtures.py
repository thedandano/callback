#!/usr/bin/env python3
"""Build the private E2/E3 eval cases from a copy of the real callback data dir.

Never modifies existing files under the data dir; all output goes under --dest
(default ~/.local/share/callback/evals). Writes one compile case
(`compile/primary`) and one tailor case per board in evals/extract/sources.json.
An existing constraints.json is kept so you can tune a case by hand.

Usage: uv run python scripts/build_eval_fixtures.py [--source DATA_DIR] [--dest EVALS_DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callback import paths  # noqa: E402
from evals.cases import private_root  # noqa: E402
from evals.private_fixtures import EXTRACT_DIR, build  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=paths.data_dir())
    parser.add_argument("--dest", type=Path, default=private_root())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    boards = sorted(json.loads((EXTRACT_DIR / "sources.json").read_text(encoding="utf-8")))
    written = build(args.source, args.dest, boards)
    for path in written:
        print(path)
    print(f"wrote {len(written)} files under {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
