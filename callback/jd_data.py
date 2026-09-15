"""JDData contract for host-owned keyword extraction."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

EXTRACTION_PROTOCOL = """Extract keywords from jd_text using this exact protocol:

1. Find sections labeled "Required", "Requirements", "Must Have", "Basic Qualifications", or similar. Extract every technical skill, tool, framework, platform, methodology, and credential as an ATOMIC term, never a whole sentence or clause - a requirement bullet is often a full sentence, so pull out only the individual skills/tools/tech/methodologies/credentials named inside it. Copy the EXACT string from the JD - do NOT paraphrase, generalize, or substitute synonyms (e.g. if JD says "k8s", use "k8s", not "Kubernetes").
2. A disjunction - two or more NAMED alternatives where satisfying ANY ONE fulfills the whole requirement - goes into a required_any GROUP: a list of the named alternatives, appended to the required_any list of groups. Do NOT dump these into preferred. A disjunction must actually mean "any one is enough" - decide that from what the requirement is asking for, not from the connector word alone:
   - "X or Y" is a disjunction (exactly two alternatives is still a group, not two separate flat terms).
   - A slash is a disjunction ONLY when splitting it passes this test: could a candidate have JUST ONE of the slash-joined words and still fully satisfy this requirement? "AWS/GCP" passes (either cloud alone is enough) -> ["AWS","GCP"]. If instead the slash-joined words are normally used together as one practice, system, or job function, it is a compound term, not alternatives - keep it as one atomic string (fails the test: "CI/CD", "I/O", and a compound job-function name like "personalization / recommendation / ranking algorithms" all describe one combined thing, not options - never split these).
   - "such as X, Y, Z" / "like X, Y, Z" / "(e.g., X, Y, Z)" is a disjunction ONLY when the requirement names a single role or category that any one item satisfies (e.g. "a programming language such as C, C++, Java" - proficiency in just one language is enough; "SQL & NoSQL datastores (e.g., PostgreSQL, Cassandra, DynamoDB, MySQL)" - experience with just one datastore from the list is enough). When the sentence instead plausibly wants several of the named items together as a toolset or stack (e.g. "security tools such as Snyk, SonarQube, and Dependabot"), it is NOT a disjunction - extract the named items as separate flat atomic terms instead.
   - "one or more of X, Y, Z" is always a disjunction.
   The opposite case: a list joined by "and", where the posting expects ALL of the named items together, is NOT a disjunction - keep those as separate flat atomic terms, one per item. For "X or some other Y" / "X or equivalent" phrasing that names only ONE concrete alternative, extract just X as a normal atomic required term - do NOT create a one-member group for it (a one-member group is scoring-identical to a scalar).
3. Find sections labeled "Preferred", "Nice to Have", "Bonus", "Preferred Qualifications", or similar. Extract genuine nice-to-haves the same way, as atomic terms. Disjunctions inside these sections (the same signals as step 2) go into a preferred_any GROUP, appended to the preferred_any list of groups - the required_any rule applied on the preferred side.
4. If no labeled sections exist, extract all technical nouns from responsibilities and description paragraphs as atomic terms. Do NOT mine keywords from: the interview process or hiring-steps section, benefits/compensation/equity text, EEO/legal/accommodation boilerplate, staffing-agency notices, or company awards/marketing copy - these describe the process or the company, not the job's requirements.
5. A keyword is a NAMED technology, tool, framework, platform, language, credential, or named methodology or domain, explicitly stated in an eligible JD section (per rule 4's exclusions above) - include every one that meets this definition, do not filter by perceived importance. Bare activity words a reader could guess from the job title alone are NOT keywords - e.g. "training", "evaluating", "tooling", "cloud", "analytics", "data processing", "software engineering fundamentals".
6. Do NOT deduplicate across required/preferred/required_any - keep each term in whichever section it appears.

Encode as compact JSON (no extra whitespace):
{"title":"<exact job title>","company":"<exact company name>","required":["<term1>","<term2>",...],"required_any":[["<altA>","<altB>",...],...],"preferred":["<term1>",...],"preferred_any":[["<altA>","<altB>",...],...],"location":"<city or Remote>","seniority":"junior|mid|senior|lead|director","required_years":<number>,"team":"<team name>","key_responsibilities":["<responsibility1>",...],"pay_range_min":<number>,"pay_range_max":<number>}
Omit optional fields entirely if not present. Do NOT invent values.

Examples:
  JD says: "Requirements: Go, Kubernetes, PostgreSQL, REST APIs. Preferred: GraphQL, Terraform."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["Go","Kubernetes","PostgreSQL","REST APIs"],"preferred":["GraphQL","Terraform"]}

  JD says: "Must have experience building distributed systems in Java, C++, or Go. 5+ years backend. Nice to have: familiarity with Datadog, Grafana, or Prometheus."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["distributed systems","backend"],"required_any":[["Java","C++","Go"]],"preferred_any":[["Datadog","Grafana","Prometheus"]],"required_years":5}

  JD says: "Experience with cloud infrastructure (AWS or GCP). Nice to have: exposure to Kubernetes and Terraform."
  -> {"title":"Software Engineer","company":"Acme Corp","required_any":[["AWS","GCP"]],"preferred":["Kubernetes","Terraform"]}

  JD says: "Experience with CI/CD pipelines and AWS/GCP infrastructure. Nice to have: familiarity with security tools such as Snyk, SonarQube, and Dependabot."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["CI/CD pipelines"],"required_any":[["AWS","GCP"]],"preferred":["Snyk","SonarQube","Dependabot"]}

  JD says (no labeled Required/Preferred sections - rule 4 applies): "Some of the problems you'll work on: **Data Pipeline Performance:** we push the limits of what our warehouse can handle, exploring query optimization and pre-computed state using dbt. **Real-time Sync:** as sources adopt CDC, we're building real-time computation with Kafka."
  -> {"title":"Software Engineer","company":"Acme Corp","required":["query optimization","pre-computed state","dbt","CDC","Kafka"]}"""  # noqa: E501

Seniority = Literal["junior", "mid", "senior", "lead", "director"]
SUPPORTED_SENIORITIES = {"junior", "mid", "senior", "lead", "director", "unspecified"}


class JDDataError(Exception):
    """Validation failure for host-submitted JDData."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_LIST_FIELDS = ("required", "preferred", "key_responsibilities", "required_any", "preferred_any")


def _clean_strings(values: object, field_name: str) -> list[str]:
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
        cleaned_group = _clean_strings(group, field_name)
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
        cleaned["required"] = _clean_strings(cleaned.get("required", []), "required")
        cleaned["preferred"] = _clean_strings(cleaned.get("preferred", []), "preferred")
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


def parse_jd_json(jd_json: str) -> dict:
    """Parse and validate host-submitted JDData JSON."""
    try:
        return JDData.model_validate_json(jd_json).model_dump()
    except ValidationError as exc:
        raise JDDataError("invalid_jd", f"jd_json parse failed: {exc}") from exc
