"""Unit tests for callback.repository.preferences."""

import json

from callback.preferences import ScanSource, SearchPreferences, WorkType
from callback.repository.preferences import PreferencesStore


def _make_prefs(**overrides) -> SearchPreferences:
    defaults = dict(
        home_location="Anytown, USA",
        work_types=[WorkType.remote],
        target_titles=["Software Engineer"],
        updated_at="2026-06-22T00:00:00+00:00",
    )
    return SearchPreferences(**{**defaults, **overrides})


def test_save_then_load_round_trip(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    prefs = _make_prefs()

    store.save(prefs)
    loaded = store.load()

    assert loaded == prefs


def test_load_missing_returns_none(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)

    assert store.load() is None


def test_save_overwrites_in_place(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    store.save(_make_prefs(home_location="Anytown, USA"))
    store.save(_make_prefs(home_location="Remote, US"))

    loaded = store.load()

    assert loaded == _make_prefs(home_location="Remote, US")


def test_file_is_valid_json_after_save(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    store.save(_make_prefs())

    with open(tmp_path / "preferences.json") as f:
        data = json.load(f)

    assert data["schema_version"] == "1"
    assert data["home_location"] == "Anytown, USA"


def test_roundtrip_with_scan_source_and_pii(tmp_path):
    store = PreferencesStore(base_dir=tmp_path)
    prefs = _make_prefs(
        scan_sources=[
            ScanSource(
                name="gmail",
                kind="email",
                instructions="Search is:unread job alerts.",
            )
        ],
        needs_sponsorship=True,
        work_authorization="US Citizen",
        yoe_actual=4.3,
    )

    store.save(prefs)

    assert store.load() == prefs
    raw = json.loads((tmp_path / "preferences.json").read_text())
    assert {k: raw[k] for k in ("scan_sources", "needs_sponsorship")} == {
        "scan_sources": [
            {
                "name": "gmail",
                "kind": "email",
                "instructions": "Search is:unread job alerts.",
                "enabled": True,
                "recency_days": None,
            }
        ],
        "needs_sponsorship": True,
    }
