"""E1 fetch fixtures: does the fetcher return text that still contains the keywords?

The CI test reads the committed fixtures and asserts the recall recorded in
sources.json byte-for-byte, so a fixture refresh that loses terms is visible in
the diff. The `local` test re-fetches each URL live and must land within one
term of the recorded recall.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from evals.recall import recall

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
SOURCES = json.loads((EXTRACT_DIR / "sources.json").read_text())
LIVE_RECALL_TOLERANCE = 1


@pytest.mark.parametrize("board", sorted(SOURCES))
def test_fixture_recall_matches_recorded(board):
    text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
    golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text())

    actual = recall(text, golden)
    expected = SOURCES[board]["recall"]
    assert actual == expected


@pytest.mark.local
@pytest.mark.parametrize("board", sorted(SOURCES))
def test_live_fetch_recall_within_tolerance(board):
    from callback.jd_fetcher import fetch_url_to_markdown

    golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text())
    text = asyncio.run(fetch_url_to_markdown(SOURCES[board]["jd_url"]))

    live = recall(text, golden)
    recorded = SOURCES[board]["recall"]
    actual = {"within_tolerance": live["found"] >= recorded["found"] - LIVE_RECALL_TOLERANCE}
    expected = {"within_tolerance": True}
    assert actual == expected, f"live={live} recorded={recorded}"
