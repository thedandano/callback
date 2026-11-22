"""Keyword matching and orphaned-skill detection."""

import re

import callback.services.scorer as scorer
from callback.models.section_map import SkillsSection


def detect_orphaned_required(
    required_missing: list[str], sections: dict, wiki_index: str
) -> list[str]:
    """Return required_missing keywords that are orphans.

    An orphan is a keyword that IS in the candidate's SectionMap skills but is
    NOT yet covered by any wiki story. Skills membership uses case-insensitive
    exact match; wiki_index uses case-insensitive substring search (the index is
    unstructured markdown text).
    """
    skills = sections.get("skills") or {}
    all_skills = SkillsSection(
        flat=skills.get("flat") or [], categorized=skills.get("categorized") or {}
    ).all_skills()
    all_skills_lower = [s.lower() for s in all_skills]
    orphans: list[str] = []
    for kw in required_missing:
        in_skills = kw.lower() in all_skills_lower
        in_wiki = bool(re.search(rf"\b{re.escape(kw)}\b", wiki_index, re.IGNORECASE))
        if in_skills and not in_wiki:
            orphans.append(kw)
    return orphans


def keyword_matches_text(keyword: str, text: str) -> bool:
    normalized_keyword = scorer.normalize_for_match(keyword)
    if not normalized_keyword:
        return False
    normalized_text = scorer.normalize_for_match(text)
    return bool(scorer.compile_keyword_pattern(normalized_keyword).search(normalized_text))


def matched_keywords(keywords: list[str], text: str) -> list[str]:
    return [keyword for keyword in keywords if keyword_matches_text(keyword, text)]
