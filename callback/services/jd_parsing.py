"""JDData contract for host-owned keyword extraction."""

from pydantic import ValidationError

from callback.models.jd_data import JDData, JDDataError, clean_strings

_MAX_ATOMIC_WORDS = 6


def parse_jd_json(jd_json: str) -> dict:
    """Parse and validate host-submitted JDData JSON."""
    try:
        return JDData.model_validate_json(jd_json).model_dump()
    except ValidationError as exc:
        raise JDDataError("invalid_jd", f"jd_json parse failed: {exc}") from exc


def _norm(term: str) -> str:
    return " ".join(term.lower().split())


def drop_scored_duplicates(keywords: dict) -> tuple[dict, list[str]]:
    """Drop key_responsibilities terms already in a scored list, plus repeats.

    Returns a new dict and the dropped terms in input order. Scored lists are untouched.
    """
    groups = [*keywords.get("required_any", []), *keywords.get("preferred_any", [])]
    seen = {
        _norm(t)
        for t in [*keywords.get("required", []), *keywords.get("preferred", [])]
        + [t for g in groups for t in g]
    }
    kept: list[str] = []
    dropped: list[str] = []
    for term in keywords.get("key_responsibilities", []):
        key = _norm(term)
        (dropped if key in seen else kept).append(term)
        seen.add(key)
    return {**keywords, "key_responsibilities": kept}, dropped


def non_atomic_responsibilities(terms: list[str]) -> list[str]:
    """Entries that read like sentences: more than 6 words, or a comma."""
    return [t for t in terms if len(t.split()) > _MAX_ATOMIC_WORDS or "," in t]


def clean_responsibilities(values: object) -> list[str]:
    """Validate a pass-2 key_responsibilities list: strings only, blanks dropped."""
    return clean_strings(values, "key_responsibilities")
