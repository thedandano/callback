"""JDData contract for host-owned keyword extraction."""

from dataclasses import asdict, dataclass, field
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
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director", "unspecified"}


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
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    location: str | None = None
    seniority: Seniority | str = "unspecified"
    required_years: float = 0.0
    team: str | None = None
    key_responsibilities: list[str] = field(default_factory=list)
    pay_range_min: float | None = None
    pay_range_max: float | None = None

    def __post_init__(self) -> None:
        if self.seniority in (None, ""):
            self.seniority = "unspecified"
        for field_name in ("required", "preferred", "key_responsibilities"):
            if not isinstance(getattr(self, field_name), list):
                raise JDDataError("invalid_jd", f"{field_name} must be a list")
        self.required = self._clean_keywords("required")
        self.preferred = self._clean_keywords("preferred")
        if not self.required:
            raise JDDataError("invalid_jd", "required skills must not be empty")
        if self.seniority not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {self.seniority}")

    def _clean_keywords(self, field_name: str) -> list[str]:
        cleaned: list[str] = []
        for kw in getattr(self, field_name):
            if not isinstance(kw, str):
                raise JDDataError("invalid_jd", f"{field_name} entries must be strings")
            if kw.strip():
                cleaned.append(kw.strip())
        return cleaned

    def model_dump(self) -> dict:
        return asdict(self)


def parse_jd_json(jd_json: str) -> dict:
    """Parse and validate host-submitted JDData JSON."""

    jd_data = _load_jd_data(jd_json)
    return jd_data.model_dump()


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
