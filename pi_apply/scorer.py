"""ATS scoring engine — pure function, no I/O, no LLM calls.

Ported from go-apply internal/service/scorer/scorer.go.
Weights and thresholds match internal/config/defaults.json exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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

# ATS section detection patterns
ATS_SECTION_PATTERNS = [
    re.compile(r"(?i)^\s*(?:work\s+|professional\s+)?experience\s*:?\s*$"),
    re.compile(r"(?i)^\s*(?:academic\s+)?education\s*:?\s*$"),
    re.compile(r"(?i)^\s*(?:technical\s+|core\s+)?skills?\s*:?\s*$"),
]


# ── Configuration and output types ─────────────────────────────────────────────


@dataclass
class ScoringWeights:
    keyword_match: float = 45.0
    experience_fit: float = 25.0
    impact_evidence: float = 10.0
    ats_format: float = 10.0
    readability: float = 10.0


@dataclass
class ScoringConfig:
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    keyword_required_weight: float = 0.7
    keyword_preferred_weight: float = 0.3
    experience_seniority_weight: float = 0.6
    experience_years_weight: float = 0.4
    seniority_multipliers: dict[str, float] = field(
        default_factory=lambda: {
            "exact": 1.0,
            "one_off": 0.8,
            "two_or_more_off": 0.5,
        }
    )
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


@dataclass
class ScoreBreakdown:
    keyword_match: float
    experience_fit: float
    impact_evidence: float
    ats_format: float
    readability: float

    def total(self) -> float:
        return (
            self.keyword_match
            + self.experience_fit
            + self.impact_evidence
            + self.ats_format
            + self.readability
        )


@dataclass
class KeywordResult:
    req_matched: list[str]
    req_unmatched: list[str]
    pref_matched: list[str]
    pref_unmatched: list[str]
    req_pct: float
    pref_pct: float


PASS_THRESHOLD = 70.0


@dataclass
class ScoreResult:
    breakdown: ScoreBreakdown
    keywords: KeywordResult
    metric_bullets: list[str]
    filler_phrases: list[str]

    def passes(self) -> bool:
        return self.breakdown.total() >= PASS_THRESHOLD


# ── Public entry point ────────────────────────────────────────────────────────


def score(
    resume_text: str,
    required: list[str],
    preferred: list[str],
    candidate_years: float = 0.0,
    required_years: float = 0.0,
    seniority_match: str = "exact",
    cfg: ScoringConfig | None = None,
) -> ScoreResult:
    """Score resume_text against LLM-extracted JD keywords.

    All inputs are caller-supplied; this function has no I/O or side effects.
    seniority_match must be one of "exact", "one_off", "two_or_more_off".
    If required_years is 0, the years component defaults to full credit.
    """
    if cfg is None:
        cfg = ScoringConfig()

    kw_result, kw_score = _score_keywords(resume_text, required, preferred, cfg)
    exp_score = _score_experience(candidate_years, required_years, seniority_match, cfg)
    impact_score, metric_bullets = _score_impact(resume_text, cfg)
    ats_score = _score_ats(resume_text, cfg)
    read_score, detected_fillers = _score_readability(resume_text, cfg)

    return ScoreResult(
        breakdown=ScoreBreakdown(
            keyword_match=kw_score,
            experience_fit=exp_score,
            impact_evidence=impact_score,
            ats_format=ats_score,
            readability=read_score,
        ),
        keywords=kw_result,
        metric_bullets=metric_bullets,
        filler_phrases=detected_fillers,
    )


# ── Scoring dimensions ────────────────────────────────────────────────────────


def _is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _compile_keyword_pattern(kw: str) -> re.Pattern:
    quoted = re.escape(kw)
    prefix = r"\b" if kw and _is_word_char(kw[0]) else ""
    suffix = r"\b" if kw and _is_word_char(kw[-1]) else ""
    return re.compile(f"(?i){prefix}{quoted}{suffix}")


def _score_keywords(
    resume_text: str,
    required: list[str],
    preferred: list[str],
    cfg: ScoringConfig,
) -> tuple[KeywordResult, float]:
    if not required and not preferred:
        return KeywordResult([], [], [], [], 0.0, 0.0), 0.0

    req_w = cfg.keyword_required_weight
    pref_w = cfg.keyword_preferred_weight
    if not required:
        req_w, pref_w = 0.0, 1.0
    elif not preferred:
        req_w, pref_w = 1.0, 0.0

    def classify(keywords: list[str]) -> tuple[list[str], list[str], float]:
        if not keywords:
            return [], [], 0.0
        matched, unmatched = [], []
        for kw in keywords:
            (matched if _compile_keyword_pattern(kw).search(resume_text) else unmatched).append(kw)
        return matched, unmatched, len(matched) / len(keywords)

    req_matched, req_unmatched, req_pct = classify(required)
    pref_matched, pref_unmatched, pref_pct = classify(preferred)
    kw_score = (req_pct * req_w + pref_pct * pref_w) * cfg.weights.keyword_match

    return (
        KeywordResult(req_matched, req_unmatched, pref_matched, pref_unmatched, req_pct, pref_pct),
        kw_score,
    )


def _score_experience(
    candidate_years: float,
    required_years: float,
    seniority_match: str,
    cfg: ScoringConfig,
) -> float:
    years_score = 1.0
    if required_years > 0:
        years_score = min(candidate_years / required_years, 1.0)
        if candidate_years > required_years * cfg.overqualification_threshold_mult:
            years_score *= cfg.overqualification_penalty

    seniority_score = cfg.seniority_multipliers.get(seniority_match, 1.0)
    return (
        years_score * cfg.experience_years_weight
        + seniority_score * cfg.experience_seniority_weight
    ) * cfg.weights.experience_fit


def _score_impact(resume_text: str, cfg: ScoringConfig) -> tuple[float, list[str]]:
    bullets = []
    for line in resume_text.splitlines():
        line = line.strip()
        if not line:
            continue
        stripped = VERSION_RE.sub("", line)
        stripped = YEAR_RE.sub("", stripped)
        if METRIC_RE.search(stripped):
            bullets.append(line)
    impact_score = min(len(bullets) / cfg.impact_bullet_target, 1.0) * cfg.weights.impact_evidence
    return impact_score, bullets


def _score_ats(resume_text: str, cfg: ScoringConfig) -> float:
    lines = resume_text.splitlines()
    found = sum(1 for pat in ATS_SECTION_PATTERNS if any(pat.match(line) for line in lines))
    return found / len(ATS_SECTION_PATTERNS) * cfg.weights.ats_format


def _score_readability(resume_text: str, cfg: ScoringConfig) -> tuple[float, list[str]]:
    detected = [
        phrase
        for phrase in cfg.filler_phrases
        if re.search(r"(?i)\b" + re.escape(phrase) + r"\b", resume_text)
    ]
    read_score = max(
        cfg.weights.readability - len(detected) * cfg.readability_penalty_per_filler,
        0.0,
    )
    return read_score, detected
