"""JDData contract for host-owned keyword extraction."""

from dataclasses import asdict, dataclass
from typing import Literal

from dataclass_wizard import JSONWizard

EXTRACTION_PROTOCOL = """Extract keywords from jd_text using this exact protocol:

1. Find sections labeled "Required", "Requirements", "Must Have", "Basic Qualifications", or similar. Extract every technical skill, tool, framework, platform, methodology, and credential. Copy the EXACT string from the JD - do NOT paraphrase, generalize, or substitute synonyms (e.g. if JD says "k8s", use "k8s", not "Kubernetes").
2. Find sections labeled "Preferred", "Nice to Have", "Bonus", "Preferred Qualifications", or similar. Extract the same way.
3. If no labeled sections exist, extract all technical nouns from responsibilities and description paragraphs.
4. Include ALL explicitly stated terms - do not filter by perceived importance.
5. Do NOT deduplicate across required/preferred - keep each term in whichever section it appears.

Encode as compact JSON (no extra whitespace):
{"title":"<exact job title>","company":"<exact company name>","required":["<term1>","<term2>",...],"preferred":["<term1>",...],"location":"<city or Remote>","seniority":"junior|mid|senior|lead|director","required_years":<number>,"team":"<team name>","key_responsibilities":["<responsibility1>",...],"pay_range_min":<number>,"pay_range_max":<number>}
Omit optional fields entirely if not present. Do NOT invent values.

Example:
  JD says: "Requirements: Go, Kubernetes, PostgreSQL, REST APIs. Preferred: GraphQL, Terraform."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["Go","Kubernetes","PostgreSQL","REST APIs"],"preferred":["GraphQL","Terraform"]}"""  # noqa: E501

Seniority = Literal["junior", "mid", "senior", "lead", "director"]
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director"}


class JDDataError(Exception):
    """Validation failure for host-submitted JDData."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class JDData(JSONWizard):
    """JSON-compatible JDData contract matching go-apply."""

    title: str | None = None
    company: str | None = None
    required: list[str] | None = None
    preferred: list[str] | None = None
    location: str | None = None
    seniority: Seniority | str = "mid"
    required_years: float | None = None
    team: str | None = None
    key_responsibilities: list[str] | None = None
    pay_range_min: float | None = None
    pay_range_max: float | None = None

    def __post_init__(self) -> None:
        if self.seniority in (None, ""):
            self.seniority = "mid"
        _validate_list_field("required", self.required)
        _validate_list_field("preferred", self.preferred)
        _validate_list_field("key_responsibilities", self.key_responsibilities)
        if self.seniority not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {self.seniority}")

    def model_dump(self) -> dict:
        return asdict(self)


def parse_jd_json(jd_json: str) -> dict:
    """Parse and validate host-submitted JDData JSON."""

    jd_data = _load_jd_data(jd_json)
    data = jd_data.model_dump()
    if _is_empty_jd(data):
        raise JDDataError(
            "jd_empty",
            "jd_json contains no extractable keywords - provide at least title, "
            "company, or required skills",
        )

    return data


def _load_jd_data(jd_json: str) -> JDData:
    try:
        jd_data = JDData.from_json(jd_json)
    except ValueError as exc:
        raise JDDataError("invalid_jd", f"jd_json parse failed: {exc}") from exc
    except TypeError as exc:
        raise JDDataError("invalid_jd", str(exc)) from exc

    if not isinstance(jd_data, JDData):
        raise JDDataError("invalid_jd", "jd_json must encode an object")

    return jd_data


def _is_empty_jd(data: dict) -> bool:
    return (
        not str(data.get("title") or "").strip()
        and not str(data.get("company") or "").strip()
        and not data.get("required")
        and not data.get("preferred")
    )


def _validate_list_field(name: str, value: object) -> None:
    if value is not None and not isinstance(value, list):
        raise JDDataError("invalid_jd", f"{name} must be a list")
