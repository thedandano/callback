"""JDData contract for host-owned keyword extraction."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from dataclass_wizard import JSONWizard

EXTRACTION_PROTOCOL = """Extract keywords from jd_text using this exact protocol:

1. Find sections labeled "Required", "Requirements", "Must Have", "Basic Qualifications", or similar. Extract every technical skill, tool, framework, platform, methodology, and credential as an ATOMIC term, never a whole sentence or clause - a requirement bullet is often a full sentence, so pull out only the individual skills/tools/tech/methodologies/credentials named inside it. Copy the EXACT string from the JD - do NOT paraphrase, generalize, or substitute synonyms (e.g. if JD says "k8s", use "k8s", not "Kubernetes").
2. Enumerable disjunctions - "one or more of", "any of", or otherwise interchangeable alternatives where only one is needed (e.g. "Java, C++, or Go") - go into a required_any GROUP: a list of the 2+ named alternatives, appended to the required_any list of groups. Do NOT dump these into preferred. For "X or some other Y" / "X or equivalent" phrasing that names only ONE concrete alternative, extract just X as a normal atomic required term - do NOT create a one-member group for it (a one-member group is scoring-identical to a scalar).
3. Find sections labeled "Preferred", "Nice to Have", "Bonus", "Preferred Qualifications", or similar. Extract genuine nice-to-haves the same way, as atomic terms. Enumerable disjunctions inside these sections (the same trigger as step 2) go into a preferred_any GROUP, appended to the preferred_any list of groups - the required_any rule applied on the preferred side.
4. If no labeled sections exist, extract all technical nouns from responsibilities and description paragraphs as atomic terms.
5. Include ALL explicitly stated terms - do not filter by perceived importance.
6. Do NOT deduplicate across required/preferred/required_any - keep each term in whichever section it appears.

Encode as compact JSON (no extra whitespace):
{"title":"<exact job title>","company":"<exact company name>","required":["<term1>","<term2>",...],"required_any":[["<altA>","<altB>",...],...],"preferred":["<term1>",...],"preferred_any":[["<altA>","<altB>",...],...],"location":"<city or Remote>","seniority":"junior|mid|senior|lead|director","required_years":<number>,"team":"<team name>","key_responsibilities":["<responsibility1>",...],"pay_range_min":<number>,"pay_range_max":<number>}
Omit optional fields entirely if not present. Do NOT invent values.

Examples:
  JD says: "Requirements: Go, Kubernetes, PostgreSQL, REST APIs. Preferred: GraphQL, Terraform."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["Go","Kubernetes","PostgreSQL","REST APIs"],"preferred":["GraphQL","Terraform"]}

  JD says: "Must have experience building distributed systems in Java, C++, or Go. 5+ years backend. Nice to have: familiarity with Datadog, Grafana, or Prometheus."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["distributed systems","backend"],"required_any":[["Java","C++","Go"]],"preferred_any":[["Datadog","Grafana","Prometheus"]],"required_years":5}"""  # noqa: E501

Seniority = Literal["junior", "mid", "senior", "lead", "director"]
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director", "unspecified"}


class JDDataError(Exception):
    """Validation failure for host-submitted JDData."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class JDData(JSONWizard):
    """JSON-compatible JDData contract."""

    title: str | None = None
    company: str | None = None
    required: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    required_any: list[list[str]] = field(default_factory=list)
    preferred_any: list[list[str]] = field(default_factory=list)
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
        list_fields = (
            "required",
            "preferred",
            "key_responsibilities",
            "required_any",
            "preferred_any",
        )
        for field_name in list_fields:
            if not isinstance(getattr(self, field_name), list):
                raise JDDataError("invalid_jd", f"{field_name} must be a list")
        self.required = self._clean_keywords("required")
        self.preferred = self._clean_keywords("preferred")
        self.required_any = self._clean_groups("required_any")
        self.preferred_any = self._clean_groups("preferred_any")
        if not self.required and not self.required_any:
            raise JDDataError("invalid_jd", "required or required_any must be non-empty")
        if self.seniority not in SUPPORTED_SENIORITIES:
            raise JDDataError("invalid_jd", f"unsupported seniority: {self.seniority}")

    def _clean_keywords(self, field_name: str) -> list[str]:
        return self._clean_strings(getattr(self, field_name), field_name)

    def _clean_groups(self, field_name: str) -> list[list[str]]:
        cleaned_groups: list[list[str]] = []
        for group in getattr(self, field_name):
            if not isinstance(group, list):
                raise JDDataError("invalid_jd", f"{field_name} entries must be lists")
            cleaned_group = self._clean_strings(group, field_name)
            if cleaned_group:
                cleaned_groups.append(cleaned_group)
        return cleaned_groups

    @staticmethod
    def _clean_strings(values: list, field_name: str) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise JDDataError("invalid_jd", f"{field_name} entries must be strings")
            if value.strip():
                cleaned.append(value.strip())
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
