"""JDData contract for host-owned keyword extraction."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Seniority = Literal["junior", "mid", "senior", "lead", "director"]
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director", "unspecified"}


class JDDataError(Exception):
    """Validation failure for host-submitted JDData."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_LIST_FIELDS = ("required", "preferred", "key_responsibilities", "required_any", "preferred_any")


def clean_strings(values: object, field_name: str) -> list[str]:
    if not isinstance(values, list):
        raise JDDataError("invalid_jd", f"{field_name} must be a list")
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise JDDataError("invalid_jd", f"{field_name} entries must be strings")
        if value.strip():
            cleaned.append(value.strip())
    return cleaned


def _clean_groups(groups: object, field_name: str) -> list[list[str]]:
    if not isinstance(groups, list):
        raise JDDataError("invalid_jd", f"{field_name} must be a list")
    cleaned_groups: list[list[str]] = []
    for group in groups:
        if not isinstance(group, list):
            raise JDDataError("invalid_jd", f"{field_name} entries must be lists")
        cleaned_group = clean_strings(group, field_name)
        if cleaned_group:
            cleaned_groups.append(cleaned_group)
    return cleaned_groups


class JDData(BaseModel):
    """JSON-compatible JDData contract."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    company: str | None = None
    required: list[str] = []
    preferred: list[str] = []
    required_any: list[list[str]] = []
    preferred_any: list[list[str]] = []
    location: str | None = None
    seniority: Seniority | str = "unspecified"
    required_years: float = 0.0
    team: str | None = None
    key_responsibilities: list[str] = []
    pay_range_min: float | None = None
    pay_range_max: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _clean(cls, data: object) -> object:
        if not isinstance(data, dict):
            raise JDDataError("invalid_jd", "jd_json must encode an object")
        cleaned = dict(data)
        if cleaned.get("seniority") in (None, ""):
            cleaned["seniority"] = "unspecified"
        for field_name in _LIST_FIELDS:
            if not isinstance(cleaned.get(field_name, []), list):
                raise JDDataError("invalid_jd", f"{field_name} must be a list")
        cleaned["required"] = clean_strings(cleaned.get("required", []), "required")
        cleaned["preferred"] = clean_strings(cleaned.get("preferred", []), "preferred")
        cleaned["required_any"] = _clean_groups(cleaned.get("required_any", []), "required_any")
        cleaned["preferred_any"] = _clean_groups(cleaned.get("preferred_any", []), "preferred_any")
        if not any(
            (
                cleaned["required"],
                cleaned["required_any"],
                cleaned["preferred"],
                cleaned["preferred_any"],
            )
        ):
            raise JDDataError("invalid_jd", "no keywords extracted")
        seniority = cleaned["seniority"]
        if not isinstance(seniority, str) or seniority not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {seniority!r}")
        return cleaned
