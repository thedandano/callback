"""Golden-term recall scoring shared by the fetch-recall tests and fixture builder.

Terms are matched boundary-aware (not substring) so short terms like "C" or "SQL"
don't false-positive inside "code" or "PostgreSQL".
"""

from __future__ import annotations

import re

_BOUNDARY = r"(?<![a-z0-9+#]){}(?![a-z0-9+#])"


def golden_terms(golden: dict) -> list[str]:
    """Every keyword the host extracted: required, preferred, and each OR-group member."""
    terms: list[str] = list(golden.get("required", [])) + list(golden.get("preferred", []))
    for group in golden.get("required_any", []) + golden.get("preferred_any", []):
        terms.extend(group)
    return sorted(set(terms))


def _present(term: str, haystack: str) -> bool:
    return re.search(_BOUNDARY.format(re.escape(term.lower())), haystack) is not None


def recall(text: str, golden: dict) -> dict:
    haystack = text.lower()
    terms = golden_terms(golden)
    missing = [t for t in terms if not _present(t, haystack)]
    title = golden.get("title", "")
    return {
        "found": len(terms) - len(missing),
        "total": len(terms),
        "missing": missing,
        "title_found": _present(title.lower(), haystack) if title else None,
    }
