"""Unit tests for callback.preferences domain model."""

import pytest
from pydantic import ValidationError

from callback.preferences import CompanyPref, SearchPreferences, WorkType


def _valid_kwargs(**overrides) -> dict:
    defaults = dict(
        home_location="Anytown, USA",
        work_types=[WorkType.hybrid_local, WorkType.remote],
        updated_at="2026-06-22T00:00:00+00:00",
    )
    return {**defaults, **overrides}


def test_minimal_valid_preferences_apply_defaults():
    prefs = SearchPreferences(**_valid_kwargs())

    assert prefs.model_dump() == {
        "schema_version": "1",
        "home_location": "Anytown, USA",
        "work_types": ["hybrid_local", "remote"],
        "target_titles": [],
        "seniority_bands": [],
        "seniority_blockers": [],
        "target_companies": [],
        "core_domains": [],
        "skip_domains": [],
        "comp_currency": "USD",
        "comp_annual_target": None,
        "updated_at": "2026-06-22T00:00:00+00:00",
    }


def test_company_pref_nested_serialization():
    prefs = SearchPreferences(
        **_valid_kwargs(
            target_companies=[
                {"name": "Acme", "level_mapping": "L4 == mid"},
                {"name": "Stripe"},
            ]
        )
    )

    assert prefs.model_dump()["target_companies"] == [
        {"name": "Acme", "level_mapping": "L4 == mid"},
        {"name": "Stripe", "level_mapping": None},
    ]


def test_missing_home_location_rejected():
    kwargs = _valid_kwargs()
    del kwargs["home_location"]
    with pytest.raises(ValidationError):
        SearchPreferences(**kwargs)


def test_invalid_work_type_rejected():
    with pytest.raises(ValidationError):
        SearchPreferences(**_valid_kwargs(work_types=["from_mars"]))


def test_company_pref_defaults_level_mapping_none():
    assert CompanyPref(name="Acme").model_dump() == {"name": "Acme", "level_mapping": None}
