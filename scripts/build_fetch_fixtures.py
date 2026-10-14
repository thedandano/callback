#!/usr/bin/env python3
"""Build (or refresh) the E1 fetch fixtures under evals/extract/.

For each entry in evals/extract/sources.json: fetch the URL with the production
fetcher, write <board>.md, and record the recall of the committed expected terms
against the fetched text back into sources.json so the CI test can assert it
byte-for-byte. A board with no <board>.expected.json yet is seeded from the
archived application named by archived_session (a private local file).
This reads pre-ledger <session>.json run files only; runs after the ledger change are in
the ledger instead.

Usage: uv run python scripts/build_fetch_fixtures.py [board ...]
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callback import paths  # noqa: E402
from callback.jd_fetcher import CHARS_PER_TOKEN, fetch_url_to_markdown  # noqa: E402
from evals.recall import recall  # noqa: E402

EXTRACT_DIR = Path(__file__).resolve().parent.parent / "evals" / "extract"


def _expected_keywords(board: str, source: dict) -> dict:
    """The committed expected data is the source of truth; the private archive only seeds
    a new board."""
    expected_path = EXTRACT_DIR / f"{board}.expected.json"
    if expected_path.exists():
        return json.loads(expected_path.read_text(encoding="utf-8"))
    session = source["archived_session"]
    archive = next(paths.apps_dir().rglob(f"{session}.json"), None)
    if archive is None:
        raise FileNotFoundError(f"no archive for session {session} under {paths.apps_dir()}")
    expected = json.loads(archive.read_text())["keywords"]
    expected_path.write_text(
        json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{board:11s} seeded expected data from {archive}")
    return expected


def build(board: str, source: dict) -> dict:
    expected = _expected_keywords(board, source)
    markdown = asyncio.run(fetch_url_to_markdown(source["jd_url"]))
    (EXTRACT_DIR / f"{board}.md").write_text(markdown, encoding="utf-8")
    return {
        **source,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fetched_chars": len(markdown),
        "fetched_tokens_est": len(markdown) // CHARS_PER_TOKEN,
        "recall": recall(markdown, expected),
    }


def main(argv: list[str]) -> int:
    sources_path = EXTRACT_DIR / "sources.json"
    sources = json.loads(sources_path.read_text())
    boards = argv or sorted(sources)
    for board in boards:
        sources[board] = build(board, sources[board])
        r = sources[board]["recall"]
        print(f"{board:11s} {r['found']}/{r['total']} found, missing={r['missing']}")
    sources_path.write_text(
        json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
