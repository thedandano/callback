"""Unit tests for callback.preferences domain model."""

import pytest
from pydantic import ValidationError

from callback.preferences import CompanyPref, ScanSource, SearchPreferences, WorkType


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
        "referral_companies": [],
        "scan_sources": [],
        "lead_recency_days": 3,
        "input_paths": [],
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


def test_empty_home_location_rejected():
    with pytest.raises(ValidationError):
        SearchPreferences(**_valid_kwargs(home_location=""))


def test_empty_work_types_rejected():
    with pytest.raises(ValidationError):
        SearchPreferences(**_valid_kwargs(work_types=[]))


def test_new_fields_default_empty():
    prefs = SearchPreferences(**_valid_kwargs())
    dumped = prefs.model_dump()
    assert dumped["referral_companies"] == []
    assert dumped["scan_sources"] == []
    assert dumped["lead_recency_days"] == 3
    assert dumped["input_paths"] == []


def test_referral_company_nested_serialization():
    from callback.preferences import ReferralCompany  # noqa: F401

    prefs = SearchPreferences(
        **_valid_kwargs(
            referral_companies=[{"name": "Acme", "note": "ask Sam"}, {"name": "Globex"}],
            lead_recency_days=7,
            input_paths=["~/resumes", "~/Documents/jobs"],
        )
    )
    dumped = prefs.model_dump()
    assert dumped["referral_companies"] == [
        {"name": "Acme", "note": "ask Sam"},
        {"name": "Globex", "note": None},
    ]
    assert dumped["lead_recency_days"] == 7
    assert dumped["input_paths"] == ["~/resumes", "~/Documents/jobs"]


def test_scan_source_nested_serialization():
    prefs = SearchPreferences(
        **_valid_kwargs(
            scan_sources=[
                ScanSource(
                    name="gmail",
                    kind="email",
                    instructions="Search is:unread newer_than:3d job alerts.",
                ),
            ]
        )
    )
    assert prefs.model_dump()["scan_sources"] == [
        {
            "name": "gmail",
            "kind": "email",
            "instructions": "Search is:unread newer_than:3d job alerts.",
            "enabled": True,
            "recency_days": None,
        },
    ]
