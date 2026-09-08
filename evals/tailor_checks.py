"""E2 deterministic checks: host tailoring edits against the source resume and wiki.

A tailoring output is honest when every edit applies cleanly, every skill it
adds is backed by a dated experience bullet, every skill it adds or replaces
already appears somewhere in the source resume or the supplied wiki pages
(case-insensitively, so a host can't invent a lowercase skill and then write
its own supporting bullet), every number and proper noun it introduces
already exists in the resume or the supplied wiki pages, it introduces no
banned filler that was not already in the source resume, and the ATS score
does not go down.
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
from evals.recall import golden_terms, term_present

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
_TOKEN_RE = re.compile(r"[A-Za-z0-9$%+#./!?:-]+")
_SENTENCE_END = (".", "!", "?", ":")
_CLAIM_STRIP = ".!?:"
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


def _malformed_edit_reason(edits: list) -> str | None:
    """None when every edit is a dict with a string `section`, a string `op`, a string
    `target` when present, and (when present) a `value` shaped for that section: a string
    everywhere except `projects`, which also allows a dict (a full project entry).
    Otherwise the reason naming the first bad entry's index, so a malformed batch fails
    the gate check instead of crashing later in `_apply_all`/`apply_edit` or downstream
    string joins over the applied section map."""
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            return f"edit {index} is not a JSON object"
        section = edit.get("section")
        if not isinstance(section, str):
            return f"edit {index} is missing a string 'section'"
        if not isinstance(edit.get("op"), str):
            return f"edit {index} is missing a string 'op'"
        if "target" in edit and not isinstance(edit["target"], str):
            return f"edit {index} has a non-string 'target'"
        allowed_value_types = (str, dict) if section == "projects" else (str,)
        if "value" in edit and not isinstance(edit["value"], allowed_value_types):
            return f"edit {index} has a non-string 'value'"
    return None


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
    # term_present()'s boundary class excludes "+"/"#", so it matches "C++"/"C#"/".NET"
    # correctly where a plain \b regex cannot.
    bullets = _dated_bullet_text(section_map).lower()
    uncovered = [s for s in _added_skills(edits) if not term_present(s.lower(), bullets)]
    return Check(
        "added_skills_in_dated_bullets",
        not uncovered,
        "" if not uncovered else f"not in a dated bullet: {uncovered}",
    )


def _source_text(case: TailorCase) -> str:
    return "\n".join(
        [json.dumps(case.sections, ensure_ascii=False), *case.wiki_pages.values()]
    ).lower()


def _skills_in_source_check(case: TailorCase, edits: list[dict]) -> Check:
    """Catches a host that invents a skill and writes its own supporting bullet:
    every added/replaced skill must already be present in the pre-edit resume or wiki,
    not merely in the post-edit bullet the host just wrote."""
    source_text = _source_text(case)
    missing = [s for s in _added_skills(edits) if not term_present(s.lower(), source_text)]
    return Check(
        "added_skills_in_source",
        not missing,
        "" if not missing else f"not in the resume or wiki: {missing}",
    )


def _introduced_keywords_in_source_check(case: TailorCase, edits: list[dict]) -> Check:
    """Catches a host that inserts a JD keyword in lowercase prose it wrote itself, with no
    separate skills edit to trip `_skills_in_source_check` (e.g. replacing a bullet with
    "built kubernetes clusters"). `_claim_tokens()` in `_grounding_check` skips lowercase
    words entirely, so this check is the only thing that would catch it. Scoped to JD
    keywords on purpose: the host only has an incentive to insert those, and grounding
    every lowercase word would false-positive on ordinary prose."""
    source_text = _source_text(case)
    terms = golden_terms(case.keywords)
    introduced: set[str] = set()
    for edit in edits:
        value = edit.get("value")
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        for term in terms:
            if term_present(term.lower(), lowered) and not term_present(term.lower(), source_text):
                introduced.add(term)
    missing = sorted(introduced)
    return Check(
        "introduced_keywords_in_source",
        not missing,
        "" if not missing else f"not in the resume or wiki: {missing}",
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
    raw = _TOKEN_RE.findall(text)
    claims: list[str] = []
    for index, token in enumerate(raw):
        stripped = token.strip(_CLAIM_STRIP)
        if not stripped:
            continue
        starts_sentence = index == 0 or raw[index - 1].endswith(_SENTENCE_END)
        if any(ch.isdigit() for ch in stripped) or (stripped[0].isupper() and not starts_sentence):
            claims.append(stripped)
    return claims


def _grounded(token: str, source_text: str, source_tokens: set[str], ratio_min: int) -> bool:
    lowered = token.lower()
    # Boundary-aware: a raw substring match would let "12" be grounded by "512", or "Go"
    # by "Golang". Only a word token gets a fuzzy fallback after the exact check.
    if term_present(lowered, source_text):
        return True
    if any(ch.isdigit() for ch in token):
        return False
    return any(_token_sort_ratio(lowered, s) >= ratio_min for s in source_tokens)


def _grounding_check(case: TailorCase, edits: list[dict]) -> Check:
    source_text = _source_text(case)
    source_tokens = {t.strip(_CLAIM_STRIP).lower() for t in _TOKEN_RE.findall(source_text)}
    ratio_min = int(case.constraints.get("grounding_ratio", DEFAULT_GROUNDING_RATIO))
    ungrounded: list[str] = []
    for text in _edit_texts(edits):
        for token in _claim_tokens(text):
            if token not in ungrounded and not _grounded(
                token, source_text, source_tokens, ratio_min
            ):
                ungrounded.append(token)
    return Check("grounded", not ungrounded, "" if not ungrounded else f"ungrounded: {ungrounded}")


def _word_in(term: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _banned_check(case: TailorCase, edits: list[dict]) -> Check:
    """Only flags a banned term the host introduced. A term already present in the source
    resume (e.g. inside an existing project name) is the host merely re-sending it, not
    keyword-stuffing, so it does not count as a hit."""
    source = json.dumps(case.sections, ensure_ascii=False).lower()
    joined = "\n".join(_edit_texts(edits)).lower()
    hits = [term for term in BANNED_TERMS if _word_in(term, joined) and not _word_in(term, source)]
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
    checks.append(_skills_in_source_check(case, host.edits))
    checks.append(_introduced_keywords_in_source_check(case, host.edits))
    checks.append(_grounding_check(case, host.edits))
    checks.append(_banned_check(case, host.edits))
    checks.append(_score_check(case, section_map))
    return checks


def run_checks(case: TailorCase, host_output: object) -> list[Check]:
    """Every E2 check in table order. Stops after the coverage check when the host declined."""
    host = HostTailor.from_output(host_output)
    if host is None:
        return [Check("valid_output", False, "host output is not a JSON object with an edits list")]
    malformed = _malformed_edit_reason(host.edits)
    if malformed is not None:
        return [Check("valid_output", False, malformed)]
    checks = [Check("valid_output", True), _coverage_check(case, host)]
    if host.no_coverage:
        return checks
    checks.extend(_edit_checks(case, host))
    return checks
