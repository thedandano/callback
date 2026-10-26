"""Guard: every E1 expected-data term follows the extraction protocol it grades against.

Without this, a hand-written *.expected.json can silently drift from
EXTRACTION_PROTOCOL - e.g. storing a whole clause ("speech, audio, or other
real-time/streaming ML domains") where the protocol demands atomic terms. That
drift is exactly what happened to the ashby and greenhouse fixtures: the model
followed the protocol correctly and was marked wrong by expected data that
followed a different rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from callback.scorer import normalize_for_match
from evals.recall import all_terms, term_present

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
SOURCES = json.loads((EXTRACT_DIR / "sources.json").read_text(encoding="utf-8"))
BOARDS = sorted(SOURCES)

# A handful of real terms run past 5-8 words describing one continuous, unsplittable
# competency (e.g. ashby's "ML models from research or prototype stage into production
# at scale" - no enumerable alternatives inside it, just a long noun phrase). Word count
# alone can't distinguish that from an unsplit "X, Y, or Z" clause, so this is a generous
# backstop against pasting a whole sentence, not a precise atomicity check.
MAX_TERM_WORDS = 12


@pytest.mark.parametrize("board", BOARDS)
def test_expected_terms_are_verbatim_jd_substrings(board):
    """Every term must appear in the JD text, except one already-documented as content
    drift in sources.json (the JD was reworded after the expected data was written -
    recorded there, not silently tolerated here)."""
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))
    jd_text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
    haystack = jd_text.lower()
    documented_drift = set(SOURCES[board]["recall"].get("missing", []))

    absent = [
        t
        for t in all_terms(expected)
        if t not in documented_drift and not term_present(t.lower(), haystack)
    ]

    assert absent == []


@pytest.mark.parametrize("board", BOARDS)
def test_expected_terms_are_not_full_sentences(board):
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))

    too_long = [t for t in all_terms(expected) if len(t.split()) > MAX_TERM_WORDS]

    assert too_long == []


def _responsibility_terms(expected: dict) -> list[str]:
    aliases = expected.get("key_responsibilities_aliases", {})
    return expected.get("key_responsibilities", []) + [
        alias for values in aliases.values() for alias in values
    ]


@pytest.mark.parametrize("board", BOARDS)
def test_expected_responsibilities_and_aliases_are_verbatim_jd_substrings(board):
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))
    haystack = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8").lower()

    actual = [
        term for term in _responsibility_terms(expected) if not term_present(term.lower(), haystack)
    ]
    expected_absent: list[str] = []
    assert actual == expected_absent


@pytest.mark.parametrize("board", BOARDS)
def test_expected_responsibilities_and_aliases_have_at_most_four_words(board):
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))

    actual = [term for term in _responsibility_terms(expected) if len(term.split()) > 4]
    expected_too_long: list[str] = []
    assert actual == expected_too_long


@pytest.mark.parametrize("board", BOARDS)
def test_responsibility_alias_keys_are_gold_terms(board):
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))
    gold_terms = set(expected.get("key_responsibilities", []))

    actual = [
        term for term in expected.get("key_responsibilities_aliases", {}) if term not in gold_terms
    ]
    expected_invalid_keys: list[str] = []
    assert actual == expected_invalid_keys


@pytest.mark.parametrize("board", BOARDS)
def test_responsibility_gold_terms_and_aliases_do_not_overlap(board):
    expected = json.loads((EXTRACT_DIR / f"{board}.expected.json").read_text(encoding="utf-8"))
    aliases = expected.get("key_responsibilities_aliases", {})
    owners: dict[str, list[str]] = {}
    for gold_term in expected.get("key_responsibilities", []):
        for term in [gold_term, *aliases.get(gold_term, [])]:
            owners.setdefault(normalize_for_match(term).lower(), []).append(gold_term)

    actual = {term: terms for term, terms in owners.items() if len(set(terms)) > 1}
    expected_duplicates: dict[str, list[str]] = {}
    assert actual == expected_duplicates
