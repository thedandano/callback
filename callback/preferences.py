"""Search-preferences domain model.

Per-user job-search criteria captured at onboard and read as a slim slice by the
scan/review skills. Pure schema — no I/O. Persistence lives in
callback.repository.preferences.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class WorkType(StrEnum):
    onsite_local = "onsite_local"
    hybrid_local = "hybrid_local"
    remote = "remote"


class CompanyPref(BaseModel):
    name: str
    level_mapping: str | None = None


class ReferralCompany(BaseModel):
    name: str
    note: str | None = None


class SearchPreferences(BaseModel):
    schema_version: str = "1"
    # Group 1 — hard gate
    home_location: str = Field(min_length=1)
    work_types: list[WorkType] = Field(min_length=1)
    # Group 2 — bias + blockers
    target_titles: list[str] = Field(default_factory=list)
    seniority_bands: list[str] = Field(default_factory=list)
    seniority_blockers: list[str] = Field(default_factory=list)
    target_companies: list[CompanyPref] = Field(default_factory=list)
    # Group 3 — domain gate
    core_domains: list[str] = Field(default_factory=list)
    skip_domains: list[str] = Field(default_factory=list)
    # Group 4 — advisory only
    comp_currency: str = "USD"
    comp_annual_target: float | None = None
    # Group 5 — discovery + referral (skills read these; nothing hardcoded)
    referral_companies: list[ReferralCompany] = Field(default_factory=list)
    scan_sources: list[str] = Field(default_factory=list)
    lead_recency_days: int = 3
    input_paths: list[str] = Field(default_factory=list)
    updated_at: str
