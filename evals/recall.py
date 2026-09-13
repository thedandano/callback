"""Term recall scoring shared by the fetch-recall tests and fixture builder.

Terms are matched boundary-aware (not substring) so short terms like "C" or "SQL"
don't false-positive inside "code" or "PostgreSQL".
"""

from __future__ import annotations

import re

_BOUNDARY = r"(?<![a-z0-9+#]){}(?![a-z0-9+#])"


def all_terms(jd_data: dict) -> list[str]:
    """Every keyword in a JDData dict: required, preferred, and each OR-group member."""
    terms: list[str] = list(jd_data.get("required", [])) + list(jd_data.get("preferred", []))
    for group in jd_data.get("required_any", []) + jd_data.get("preferred_any", []):
        terms.extend(group)
    return sorted(set(terms))


def term_present(term: str, haystack: str) -> bool:
    return re.search(_BOUNDARY.format(re.escape(term.lower())), haystack) is not None


def recall(text: str, expected: dict) -> dict:
    haystack = text.lower()
    terms = all_terms(expected)
    missing = [t for t in terms if not term_present(t, haystack)]
    title = expected.get("title", "")
    return {
        "found": len(terms) - len(missing),
        "total": len(terms),
        "missing": missing,
        "title_found": term_present(title.lower(), haystack) if title else None,
    }
