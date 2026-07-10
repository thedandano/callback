"""ATS scoring engine — pure function, no I/O, no LLM calls.

Each dimension proxies a real ATS gate mechanism: recruiter keyword search
(KeywordMatch), years knockout filters (ExperienceFit), parse failures
(ATSFormat), and the recruiter skim (ImpactEvidence, Readability).
Deterministic: identical inputs always produce identical outputs.
Weights and thresholds live in ScoringConfig below — callback-owned, not
inherited from any external system.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

SCORING_ENGINE_VERSION = "v2"

# ── Regex patterns used for scoring ────────────────────────────────────────────

# Compiled once at module load; used for impact scoring
METRIC_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"\d+\.?\d*\s*%"  # percentage: 40%, 3.5%
    r"|\$\s*\d[\d,.]*"  # dollar: $1.2M, $50k
    r"|\d[\d,.]*\s*[kKmMbB]\b"  # magnitude: 50k, 1.2M
    r"|\d+x\b"  # multiplier: 2x, 10x
    r"|\d{3,}"  # large int ≥ 100 (years stripped first)
    r")"
)

VERSION_RE = re.compile(r"(?i)\b[A-Za-z][A-Za-z0-9]*\s+\d+(?:\.\d+)+\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# Lines that are contact/header info, not accomplishment bullets — excluded
# from impact-metric detection so phone numbers and ZIP codes don't score.
CONTACT_LINE_RE = re.compile(
    r"(?i)(?:"
    r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"  # phone: 555-867-5309, (415) 555-0100
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"  # email
    r"|\bhttps?://|\bwww\."  # URLs
    r"|\b(?:linkedin|github)\.com/"  # profile links
    r"|(?-i:\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b)"  # state + ZIP: TX 78701
    r")"
)

# ATS section detection patterns
ATS_SECTION_PATTERNS = [
    re.compile(r"(?i)^\s*(?:work\s+|professional\s+)?experience\s*:?\s*$"),
    re.compile(r"(?i)^\s*(?:academic\s+)?education\s*:?\s*$"),
    re.compile(r"(?i)^\s*(?:technical\s+|core\s+)?skills?(?:\s*&\s*abilities)?\s*:?\s*$"),
]


# ── Configuration and output types ─────────────────────────────────────────────


@dataclass
class ScoringWeights:
    keyword_match: float = 55.0
    experience_fit: float = 15.0
    impact_evidence: float = 10.0
    ats_format: float = 10.0
    readability: float = 10.0


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    keyword_required_weight: float = 0.7
    keyword_preferred_weight: float = 0.3
    overqualification_threshold_mult: float = 2.0
    overqualification_penalty: float = 0.85
    impact_bullet_target: int = 5
    filler_phrases: list[str] = field(
        default_factory=lambda: [
            "responsible for",
            "worked on",
            "helped with",
            "assisted in",
            "involved in",
            "participated in",
            "contributed to",
            "familiar with",
            "exposure to",
            "knowledge of",
        ]
    )
    readability_penalty_per_filler: float = 2.0
    pass_threshold: float = 70.0


# Shared default config — treat as frozen; construct a new ScoringConfig to customize.
DEFAULT_SCORING_CONFIG = ScoringConfig()


@dataclass
class ATSHeaderDiagnostic:
    expected: str
    observed: str | None
    matched: bool
    closeable_by: Literal["tailor", "render", "source_pdf"]


@dataclass
class ScoreBreakdown:
    keyword_match: float
    experience_fit: float | None
    impact_evidence: float
    ats_format: float
    readability: float
    renorm_factor: float = 1.0  # > 1.0 only when experience_fit is not evaluated
    ats_diagnostics: list[ATSHeaderDiagnostic] = field(default_factory=list)

    def total(self) -> float:
        base = self.keyword_match + self.impact_evidence + self.ats_format + self.readability
        if self.experience_fit is None:
            return base * self.renorm_factor
        return base + self.experience_fit


@dataclass
class KeywordResult:
    req_matched: list[str]
    req_unmatched: list[str]
    pref_matched: list[str]
    pref_unmatched: list[str]
    req_pct: float
    pref_pct: float
    req_group_unmatched: list[list[str]] = field(default_factory=list)
    pref_group_unmatched: list[list[str]] = field(default_factory=list)


@dataclass
class ScoreResult:
    breakdown: ScoreBreakdown
    keywords: KeywordResult
    metric_bullets: list[str]
    filler_phrases: list[str]
    pass_threshold: float = 70.0

    def passes(self) -> bool:
        return self.breakdown.total() >= self.pass_threshold


# ── Public entry point ────────────────────────────────────────────────────────


def score(
    resume_text: str,
    required: list[str],
    preferred: list[str],
    required_any: list[list[str]] | None = None,
    preferred_any: list[list[str]] | None = None,
    candidate_years: float | None = None,
    required_years: float = 0.0,
    cfg: ScoringConfig | None = None,
    closeable_by: Literal["tailor", "render", "source_pdf"] = "source_pdf",
) -> ScoreResult:
    """Score resume_text against LLM-extracted JD keywords.

    All inputs are caller-supplied; this function has no I/O or side effects.
    required_any / preferred_any are lists of OR-groups: each group is a list of
    interchangeable alternatives that scores as one unit, matched iff any member
    matches — at required weight for required_any, preferred weight for preferred_any.
    ExperienceFit is years-only: evaluated when required_years > 0 and
    candidate_years is known, otherwise None — the total then renormalizes
    over the remaining dimensions so the scale stays 0–100.
    closeable_by is forwarded to _score_ats() to tag ATS diagnostics.
    """
    if cfg is None:
        cfg = DEFAULT_SCORING_CONFIG

    kw_result, kw_score = _score_keywords(
        resume_text, required, preferred, required_any or [], preferred_any or [], cfg
    )
    exp_score = _score_experience(candidate_years, required_years, cfg)
    w = cfg.weights
    full_max = w.keyword_match + w.experience_fit + w.impact_evidence + w.ats_format + w.readability
    renorm = full_max / (full_max - w.experience_fit) if exp_score is None else 1.0
    impact_score, metric_bullets = _score_impact(resume_text, cfg)
    ats_score, ats_diagnostics = _score_ats(resume_text, cfg, closeable_by=closeable_by)
    read_score, detected_fillers = _score_readability(resume_text, cfg)

    return ScoreResult(
        breakdown=ScoreBreakdown(
            keyword_match=kw_score,
            experience_fit=exp_score,
            impact_evidence=impact_score,
            ats_format=ats_score,
            readability=read_score,
            renorm_factor=renorm,
            ats_diagnostics=ats_diagnostics,
        ),
        keywords=kw_result,
        metric_bullets=metric_bullets,
        filler_phrases=detected_fillers,
        pass_threshold=cfg.pass_threshold,
    )


# ── Scoring dimensions ────────────────────────────────────────────────────────


_DASH_RE = re.compile(r"[-‐–—­‑​]")
_SLASH_WS_RE = re.compile(r"\s*/\s*")
_WS_RE = re.compile(r"\s+")


def _normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _DASH_RE.sub(" ", text)
    text = _SLASH_WS_RE.sub("/", text)
    return _WS_RE.sub(" ", text).strip()


def _is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


_PLURAL_MIN_STEM = 4


def _plural_tolerant(token: str) -> str:
    """Regex fragment matching token with optional trailing s/es.

    Conservative by design: alpha-only tokens with a stem of >= 4 chars.
    Honest-signal rule — a recruiter's literal search for the JD term must
    still retrieve the resume; no synonym or abbreviation expansion.
    """
    if not token.isalpha() or len(token) < _PLURAL_MIN_STEM:
        return re.escape(token)
    stem = token[:-1] if token.endswith("s") and not token.endswith("ss") else token
    if len(stem) < _PLURAL_MIN_STEM:
        return re.escape(token)
    return re.escape(stem) + r"(?:e?s)?"


def _compile_keyword_pattern(kw: str) -> re.Pattern:
    prefix = r"\b" if kw and _is_word_char(kw[0]) else ""
    suffix = r"\b" if kw and _is_word_char(kw[-1]) else ""
    head, sep, last = kw.rpartition(" ")
    body = re.escape(head + sep) + _plural_tolerant(last)
    return re.compile(f"(?i){prefix}{body}{suffix}")


def _keyword_hit(kw: str, normalized_resume: str) -> bool:
    norm_kw = _normalize_for_match(kw)
    # An empty normalized keyword would match anything — never credit it.
    return bool(norm_kw) and bool(_compile_keyword_pattern(norm_kw).search(normalized_resume))


def _group_matches(group: list[str], normalized_resume: str) -> bool:
    """A group is matched iff any member's compiled pattern hits the resume."""
    return any(_keyword_hit(member, normalized_resume) for member in group)


def _classify_groups(
    groups: list[list[str]], normalized_resume: str
) -> tuple[list[list[str]], int]:
    """Split OR-groups into unmatched groups and a count of matched groups."""
    unmatched = [group for group in groups if not _group_matches(group, normalized_resume)]
    return unmatched, len(groups) - len(unmatched)


def _classify_keywords(
    keywords: list[str], normalized_resume: str
) -> tuple[list[str], list[str], float]:
    if not keywords:
        return [], [], 0.0
    matched, unmatched = [], []
    for kw in keywords:
        (matched if _keyword_hit(kw, normalized_resume) else unmatched).append(kw)
    return matched, unmatched, len(matched) / len(keywords)


def _score_keywords(
    resume_text: str,
    required: list[str],
    preferred: list[str],
    required_any: list[list[str]],
    preferred_any: list[list[str]],
    cfg: ScoringConfig,
) -> tuple[KeywordResult, float]:
    if not required and not preferred and not required_any and not preferred_any:
        return KeywordResult([], [], [], [], 0.0, 0.0), 0.0

    req_w = cfg.keyword_required_weight
    pref_w = cfg.keyword_preferred_weight
    if not required and not required_any:
        req_w, pref_w = 0.0, 1.0
    elif not preferred and not preferred_any:
        req_w, pref_w = 1.0, 0.0

    normalized_resume = _normalize_for_match(resume_text)

    req_matched, req_unmatched, _ = _classify_keywords(required, normalized_resume)
    pref_matched, pref_unmatched, _ = _classify_keywords(preferred, normalized_resume)

    req_group_unmatched, req_group_matched = _classify_groups(required_any, normalized_resume)
    pref_group_unmatched, pref_group_matched = _classify_groups(preferred_any, normalized_resume)

    req_total = len(required) + len(required_any)
    req_pct = (len(req_matched) + req_group_matched) / req_total if req_total else 0.0
    pref_total = len(preferred) + len(preferred_any)
    pref_pct = (len(pref_matched) + pref_group_matched) / pref_total if pref_total else 0.0

    kw_score = (req_pct * req_w + pref_pct * pref_w) * cfg.weights.keyword_match

    return (
        KeywordResult(
            req_matched,
            req_unmatched,
            pref_matched,
            pref_unmatched,
            req_pct,
            pref_pct,
            req_group_unmatched,
            pref_group_unmatched,
        ),
        kw_score,
    )


def _score_experience(
    candidate_years: float | None,
    required_years: float,
    cfg: ScoringConfig,
) -> float | None:
    """Return experience-fit points, or None when the dimension cannot be evaluated."""
    if required_years <= 0 or candidate_years is None:
        return None
    years = max(candidate_years, 0.0)
    years_score = min(years / required_years, 1.0)
    if years > required_years * cfg.overqualification_threshold_mult:
        years_score *= cfg.overqualification_penalty
    return years_score * cfg.weights.experience_fit


def _score_impact(resume_text: str, cfg: ScoringConfig) -> tuple[float, list[str]]:
    bullets = []
    for line in resume_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip contact/version/year noise so a real metric still counts even when
        # the line also holds a phone- or ZIP-shaped digit run; a pure contact line
        # has nothing left to match.
        stripped = CONTACT_LINE_RE.sub("", line)
        stripped = VERSION_RE.sub("", stripped)
        stripped = YEAR_RE.sub("", stripped)
        if METRIC_RE.search(stripped):
            bullets.append(line)
    impact_score = min(len(bullets) / cfg.impact_bullet_target, 1.0) * cfg.weights.impact_evidence
    return impact_score, bullets


_ATS_SECTION_KEYWORDS = ["experience", "education", "skills"]
_ATS_SECTION_EXPECTED = ["Experience", "Education", "Skills"]


def _score_ats(
    resume_text: str,
    cfg: ScoringConfig,
    closeable_by: Literal["tailor", "render", "source_pdf"] = "source_pdf",
) -> tuple[float, list[ATSHeaderDiagnostic]]:
    lines = resume_text.splitlines()
    diagnostics: list[ATSHeaderDiagnostic] = []
    found = 0
    for pat, keyword, expected in zip(
        ATS_SECTION_PATTERNS,
        _ATS_SECTION_KEYWORDS,
        _ATS_SECTION_EXPECTED,
        strict=True,
    ):
        matched_line = next((line for line in lines if pat.match(line)), None)
        if matched_line is not None:
            diagnostics.append(
                ATSHeaderDiagnostic(
                    expected=expected,
                    observed=matched_line,
                    matched=True,
                    closeable_by=closeable_by,
                )
            )
            found += 1
        else:
            observed = next((line for line in lines if keyword.lower() in line.lower()), None)
            diagnostics.append(
                ATSHeaderDiagnostic(
                    expected=expected,
                    observed=observed,
                    matched=False,
                    closeable_by=closeable_by,
                )
            )
    scalar_score = found / len(ATS_SECTION_PATTERNS) * cfg.weights.ats_format
    return scalar_score, diagnostics


def _score_readability(resume_text: str, cfg: ScoringConfig) -> tuple[float, list[str]]:
    normalized_resume = _normalize_for_match(resume_text)
    detected = [
        phrase
        for phrase in cfg.filler_phrases
        if re.search(r"(?i)\b" + re.escape(_normalize_for_match(phrase)) + r"\b", normalized_resume)
    ]
    read_score = max(
        cfg.weights.readability - len(detected) * cfg.readability_penalty_per_filler,
        0.0,
    )
    return read_score, detected
