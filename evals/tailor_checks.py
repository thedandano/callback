"""E2 deterministic checks: host tailoring edits against the source resume and wiki.

A tailoring output is honest when every edit applies cleanly, every skill it
adds is backed by a dated experience bullet, every number and proper noun it
introduces already exists in the resume or the supplied wiki pages, it uses no
banned filler, and the ATS score does not go down.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from callback import scorer
from callback.apply_nodes import _sections_to_text
from callback.profilecompiler import _token_sort_ratio
from callback.section_map import SectionMap, apply_edit
from evals.checks import Check

BANNED_TERMS = (
    "spearheaded",
    "orchestrated",
    "championed",
    "leveraged",
    "utilized",
    "streamlined",
    "passionate",
    "driven",
    "results-oriented",
    "proven track record",
)
DEFAULT_GROUNDING_RATIO = 85
_TOKEN_RE = re.compile(r"[A-Za-z0-9$%+#./-]+")
_SENTENCE_END = (".", "!", "?", ":")
_PROJECT_TEXT_KEYS = ("name", "description")


@dataclass(frozen=True)
class TailorCase:
    sections: dict
    keywords: dict
    wiki_pages: dict[str, str]
    constraints: dict = field(default_factory=dict)

    @classmethod
    def from_dir(cls, case_dir: Path) -> TailorCase:
        wiki_root = case_dir / "wiki"
        pages = {
            str(p.relative_to(wiki_root)): p.read_text(encoding="utf-8")
            for p in sorted(wiki_root.rglob("*.md"))
        }
        return cls(
            sections=json.loads((case_dir / "sections.json").read_text(encoding="utf-8")),
            keywords=json.loads((case_dir / "keywords.json").read_text(encoding="utf-8")),
            wiki_pages=pages,
            constraints=json.loads((case_dir / "constraints.json").read_text(encoding="utf-8")),
        )


@dataclass(frozen=True)
class HostTailor:
    edits: list[dict]
    no_coverage: bool = False

    @classmethod
    def from_output(cls, output: object) -> HostTailor | None:
        if not isinstance(output, dict) or not isinstance(output.get("edits"), list):
            return None
        return cls(edits=list(output["edits"]), no_coverage=bool(output.get("no_coverage", False)))


def _score(sections: dict, keywords: dict) -> scorer.ScoreResult:
    text = _sections_to_text(SectionMap.model_validate(sections))
    return scorer.score(
        text,
        keywords.get("required", []),
        keywords.get("preferred", []),
        required_any=keywords.get("required_any", []),
        preferred_any=keywords.get("preferred_any", []),
        required_years=float(keywords.get("required_years", 0.0)),
    )


def score_total(sections: dict, keywords: dict) -> float:
    return round(_score(sections, keywords).breakdown.total(), 2)


def missing_keywords(sections: dict, keywords: dict) -> dict[str, list[str] | list[list[str]]]:
    """What submit_keywords would report as gaps for this resume."""
    result = _score(sections, keywords)
    return {
        "required_missing": result.keywords.req_unmatched,
        "preferred_missing": result.keywords.pref_unmatched,
        "required_groups_missing": result.keywords.req_group_unmatched,
    }


def _apply_all(sections: dict, edits: list[dict]) -> tuple[SectionMap, list[dict]]:
    section_map = SectionMap.model_validate(sections)
    rejected = []
    for index, edit in enumerate(edits):
        result = apply_edit(section_map, edit)
        if not result.applied:
            rejected.append({"index": index, "reason": result.rejection_reason})
    return section_map, rejected


def _added_skills(edits: list[dict]) -> list[str]:
    return [
        e["value"]
        for e in edits
        if e.get("section") == "skills"
        and e.get("op") in ("add", "replace")
        and isinstance(e.get("value"), str)
    ]


def _dated_bullet_text(section_map: SectionMap) -> str:
    return " ".join(b for exp in section_map.experience if exp.start_date for b in exp.bullets)


def _skills_check(section_map: SectionMap, edits: list[dict]) -> Check:
    bullets = _dated_bullet_text(section_map)
    uncovered = [
        s
        for s in _added_skills(edits)
        if not re.search(rf"\b{re.escape(s)}\b", bullets, re.IGNORECASE)
    ]
    return Check(
        "added_skills_in_dated_bullets",
        not uncovered,
        "" if not uncovered else f"not in a dated bullet: {uncovered}",
    )


def _edit_texts(edits: list[dict]) -> list[str]:
    texts: list[str] = []
    for edit in edits:
        value = edit.get("value")
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            texts.extend(str(value.get(k) or "") for k in _PROJECT_TEXT_KEYS)
            texts.extend(str(b) for b in value.get("bullets", []))
    return texts


def _claim_tokens(text: str) -> list[str]:
    """Numbers and capitalized words that don't start a sentence: the parts that can be invented."""
    tokens = [t.strip(".") for t in _TOKEN_RE.findall(text)]
    claims: list[str] = []
    for index, token in enumerate(tokens):
        if not token:
            continue
        starts_sentence = index == 0 or tokens[index - 1].endswith(_SENTENCE_END)
        if any(ch.isdigit() for ch in token) or (token[0].isupper() and not starts_sentence):
            claims.append(token)
    return claims


def _grounded(token: str, source_text: str, source_tokens: set[str], ratio_min: int) -> bool:
    lowered = token.lower()
    if lowered in source_text:
        return True
    if any(ch.isdigit() for ch in token):
        return False
    return any(_token_sort_ratio(lowered, s) >= ratio_min for s in source_tokens)


def _grounding_check(case: TailorCase, edits: list[dict]) -> Check:
    source_text = "\n".join(
        [json.dumps(case.sections, ensure_ascii=False), *case.wiki_pages.values()]
    ).lower()
    source_tokens = {t.strip(".").lower() for t in _TOKEN_RE.findall(source_text)}
    ratio_min = int(case.constraints.get("grounding_ratio", DEFAULT_GROUNDING_RATIO))
    ungrounded: list[str] = []
    for text in _edit_texts(edits):
        for token in _claim_tokens(text):
            if token not in ungrounded and not _grounded(
                token, source_text, source_tokens, ratio_min
            ):
                ungrounded.append(token)
    return Check("grounded", not ungrounded, "" if not ungrounded else f"ungrounded: {ungrounded}")


def _banned_check(edits: list[dict]) -> Check:
    joined = "\n".join(_edit_texts(edits)).lower()
    hits = [term for term in BANNED_TERMS if re.search(rf"\b{re.escape(term)}\b", joined)]
    return Check("no_banned_terms", not hits, "" if not hits else f"banned: {hits}")


def _score_check(case: TailorCase, section_map: SectionMap) -> Check:
    before = score_total(case.sections, case.keywords)
    after = score_total(section_map.model_dump(), case.keywords)
    ok = after >= before
    return Check("score_not_lower", ok, "" if ok else f"final {after} < initial {before}")


def _coverage_check(case: TailorCase, host: HostTailor) -> Check:
    expected = bool(case.constraints.get("expect_no_coverage", False))
    ok = host.no_coverage == expected and not (host.no_coverage and host.edits)
    if host.no_coverage != expected:
        detail = f"expected no_coverage={expected}, host gave no_coverage={host.no_coverage}"
    elif host.no_coverage and host.edits:
        detail = f"no_coverage=True but {len(host.edits)} edits were returned"
    else:
        detail = ""
    return Check("no_coverage_as_expected", ok, detail)


def _edit_checks(case: TailorCase, host: HostTailor) -> list[Check]:
    checks: list[Check] = []
    has_edits = bool(host.edits)
    checks.append(
        Check(
            "has_edits",
            has_edits,
            "" if has_edits else "host returned no edits and no_coverage=False",
        )
    )
    section_map, rejected = _apply_all(case.sections, host.edits)
    checks.append(Check("no_rejected_edits", not rejected, "" if not rejected else str(rejected)))
    checks.append(_skills_check(section_map, host.edits))
    checks.append(_grounding_check(case, host.edits))
    checks.append(_banned_check(host.edits))
    checks.append(_score_check(case, section_map))
    return checks


def run_checks(case: TailorCase, host_output: object) -> list[Check]:
    """Every E2 check in table order. Stops after the coverage check when the host declined."""
    host = HostTailor.from_output(host_output)
    if host is None:
        return [Check("valid_output", False, "host output is not a JSON object with an edits list")]
    checks = [Check("valid_output", True), _coverage_check(case, host)]
    if host.no_coverage:
        return checks
    checks.extend(_edit_checks(case, host))
    return checks
