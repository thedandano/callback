"""E2 checks: edits must apply, be grounded, avoid filler, and not lower the score."""

from __future__ import annotations

import json
from pathlib import Path

from callback.section_map import SectionMap
from evals.checks import Check, first_failure
from evals.tailor_checks import (
    HostTailor,
    TailorCase,
    _claim_tokens,
    _grounded,
    _skills_check,
    run_checks,
    score_total,
)

TAILOR_FIXTURES = Path(__file__).resolve().parent / "tailor"

SECTIONS = {
    "summary": "Backend engineer with 5 years building Python services on AWS.",
    "skills": {"flat": [], "categorized": {"Languages": ["Python"], "Cloud": ["AWS", "Docker"]}},
    "experience": [
        {
            "company": "Acme Corp",
            "role": "Backend Engineer",
            "start_date": "2021-03",
            "end_date": None,
            "context_line": None,
            "bullets": [
                "Rebuilt the checkout API on FastAPI, cutting p95 latency 40% for 2M monthly "
                "orders",
                "Wrote Terraform modules for the AWS ECS deployment",
            ],
        }
    ],
    "projects": [{"name": "Open Ledger", "description": "Bookkeeping API", "bullets": []}],
    "education": [{"institution": "State University", "degree": "B.S.", "field": "CS"}],
    "contact": {"name": "Jane Doe"},
    "certifications": [],
    "awards": [],
}
KEYWORDS = {
    "title": "Senior Backend Engineer",
    "required": ["Python", "FastAPI", "AWS", "Terraform"],
    "preferred": ["Redis", "Kubernetes"],
    "required_any": [],
    "preferred_any": [],
    "required_years": 4.0,
}
WIKI = {
    "index.md": "# Profile Index\n\n## Skills\n\n- [FastAPI](experience/story-001.md)\n",
    "experience/story-001.md": (
        "---\ntype: story\ntitle: FastAPI\ntags:\n- FastAPI\n- Redis\n---\n# FastAPI\n\n"
        "**Situation:** Checkout was slow.\n\n**Behavior:** Added Redis caching for cart reads.\n\n"
        "**Impact:** Database load dropped 30% during peak sales.\n"
    ),
}
CONSTRAINTS = {"expect_no_coverage": False, "grounding_ratio": 85}
CASE = TailorCase(sections=SECTIONS, keywords=KEYWORDS, wiki_pages=WIKI, constraints=CONSTRAINTS)

HONEST = {
    "edits": [
        {"section": "skills", "op": "add", "value": "FastAPI", "category": "Languages"},
        {"section": "skills", "op": "add", "value": "Terraform", "category": "Cloud"},
        {
            "section": "experience",
            "op": "replace",
            "target": "exp-0-b0",
            "value": "Rebuilt the checkout API on FastAPI with Redis caching, cutting p95 "
            "latency 40% for 2M monthly orders and database load 30%",
        },
    ],
    "no_coverage": False,
}


def _names(checks: list[Check]) -> dict[str, bool]:
    return {c.name: c.passed for c in checks}


def test_honest_edits_pass_every_check():
    actual = _names(run_checks(CASE, HONEST))

    expected = {
        "valid_output": True,
        "no_coverage_as_expected": True,
        "has_edits": True,
        "no_rejected_edits": True,
        "added_skills_in_dated_bullets": True,
        "added_skills_in_source": True,
        "grounded": True,
        "no_banned_terms": True,
        "score_not_lower": True,
    }
    assert actual == expected


def test_keyword_stuffed_output_fails():
    stuffed = {
        "edits": [
            {"section": "skills", "op": "add", "value": "Kubernetes", "category": "Cloud"},
            {"section": "skills", "op": "add", "value": "Redis", "category": "Cloud"},
            {
                "section": "experience",
                "op": "replace",
                "target": "exp-0-b1",
                "value": "Leveraged Kubernetes and Terraform to cut deploy time 70% across "
                "12 clusters",
            },
        ],
        "no_coverage": False,
    }

    actual = [c for c in run_checks(CASE, stuffed) if not c.passed]

    expected = [
        Check("added_skills_in_dated_bullets", False, "not in a dated bullet: ['Redis']"),
        Check("added_skills_in_source", False, "not in the resume or wiki: ['Kubernetes']"),
        Check("grounded", False, "ungrounded: ['Kubernetes', '70%', '12']"),
        Check("no_banned_terms", False, "banned: ['leveraged']"),
    ]
    assert actual == expected


def test_invented_lowercase_skill_with_self_supplied_bullet_fails():
    """A host can't invent a lowercase skill and then write its own bullet to back it up."""
    case = TailorCase.from_dir(TAILOR_FIXTURES / "jane-doe-backend")
    sneaky = {
        "edits": [
            {"section": "skills", "op": "add", "value": "distributed systems"},
            {
                "section": "experience",
                "op": "replace",
                "target": "exp-0-b0",
                "value": "Rebuilt the checkout API on FastAPI with PostgreSQL connection "
                "pooling, cutting p95 latency 40% for 2M monthly orders across distributed "
                "systems",
            },
        ],
        "no_coverage": False,
    }

    actual = [c for c in run_checks(case, sneaky) if not c.passed]

    expected = [
        Check(
            "added_skills_in_source",
            False,
            "not in the resume or wiki: ['distributed systems']",
        )
    ]
    assert actual == expected


def test_unparseable_output_is_the_only_check():
    checks = run_checks(CASE, None)

    actual = [(c.name, c.passed, c.detail) for c in checks]

    expected = [("valid_output", False, "host output is not a JSON object with an edits list")]
    assert actual == expected


def test_malformed_edit_entry_fails_valid_output_without_raising():
    """A non-object edit entry must gate on valid_output instead of reaching _apply_all(),
    which would call .get() on it and crash the batch."""
    actual = run_checks(CASE, {"edits": ["oops"], "no_coverage": False})

    expected = [Check("valid_output", False, "edit 0 is not a JSON object")]
    assert actual == expected


def test_rejected_edit_is_reported():
    bad = {
        "edits": [{"section": "experience", "op": "replace", "target": "exp-9-b0", "value": "x"}]
    }

    actual = first_failure(run_checks(CASE, bad))

    expected = (
        "no_rejected_edits: [{'index': 0, 'reason': 'experience index 9 out of bounds (have 1)'}]"
    )
    assert actual == expected


def test_no_coverage_expected_and_given_passes_and_stops():
    case = TailorCase(SECTIONS, KEYWORDS, WIKI, {"expect_no_coverage": True, "grounding_ratio": 85})

    actual = run_checks(case, {"edits": [], "no_coverage": True})

    expected = [Check("valid_output", True), Check("no_coverage_as_expected", True)]
    assert actual == expected


def test_no_coverage_expected_but_edits_given_fails():
    case = TailorCase(SECTIONS, KEYWORDS, WIKI, {"expect_no_coverage": True, "grounding_ratio": 85})

    actual = first_failure(run_checks(case, HONEST))

    expected = "no_coverage_as_expected: expected no_coverage=True, host gave no_coverage=False"
    assert actual == expected


def test_no_coverage_with_edits_is_contradictory():
    actual = first_failure(run_checks(CASE, {"edits": HONEST["edits"], "no_coverage": True}))

    expected = "no_coverage_as_expected: expected no_coverage=False, host gave no_coverage=True"
    assert actual == expected


def test_empty_edits_without_no_coverage_fails_has_edits():
    actual = first_failure(run_checks(CASE, {"edits": [], "no_coverage": False}))

    expected = "has_edits: host returned no edits and no_coverage=False"
    assert actual == expected


def test_score_drop_is_caught():
    dropping = {
        "edits": [
            {"section": "experience", "op": "remove", "target": "exp-0-b0"},
            {"section": "experience", "op": "remove", "target": "exp-0-b0"},
            {"section": "summary", "op": "replace", "value": "Backend engineer."},
        ],
        "no_coverage": False,
    }
    before = score_total(SECTIONS, KEYWORDS)
    after_sections = json.loads(json.dumps(SECTIONS))
    after_sections["summary"] = "Backend engineer."
    after_sections["experience"][0]["bullets"] = []
    after = score_total(after_sections, KEYWORDS)

    actual = [c for c in run_checks(CASE, dropping) if c.name == "score_not_lower"]

    expected = [Check("score_not_lower", False, f"final {after} < initial {before}")]
    assert actual == expected


def test_banned_word_already_in_resume_is_not_flagged():
    case = TailorCase(
        sections={**SECTIONS, "projects": [{"name": "Results-Driven Ledger", "bullets": []}]},
        keywords=KEYWORDS,
        wiki_pages=WIKI,
        constraints=CONSTRAINTS,
    )
    edit = {
        "section": "projects",
        "op": "add",
        "target": "proj-end",
        "value": {"name": "Results-Driven Ledger", "description": "", "bullets": []},
    }

    actual = _names(run_checks(case, {"edits": [edit], "no_coverage": False}))["no_banned_terms"]

    expected = True
    assert actual == expected


def test_project_edit_values_are_grounded_and_fuzzy_matched():
    edit = {
        "section": "projects",
        "op": "replace",
        "target": "proj-0",
        "value": {"name": "Open Ledger", "description": "Bookkeeping API in Python", "bullets": []},
    }

    actual = _names(run_checks(CASE, {"edits": [edit], "no_coverage": False}))["grounded"]

    expected = True
    assert actual == expected


def test_multi_sentence_summary_is_grounded():
    edit = {
        "section": "summary",
        "op": "replace",
        "value": "Backend engineer with 5 years on AWS. Cut checkout p95 latency 40% at Acme Corp.",
    }

    actual = _names(run_checks(CASE, {"edits": [edit], "no_coverage": False}))["grounded"]

    expected = True
    assert actual == expected


def test_small_number_is_not_grounded_by_a_larger_one():
    sections = {**SECTIONS, "summary": SECTIONS["summary"] + " Handles 512 requests per second."}
    case = TailorCase(sections, KEYWORDS, WIKI, CONSTRAINTS)
    edit = {"section": "summary", "op": "replace", "value": "Scaled to 12 clusters."}

    actual = [
        c for c in run_checks(case, {"edits": [edit], "no_coverage": False}) if c.name == "grounded"
    ]

    expected = [Check("grounded", False, "ungrounded: ['12']")]
    assert actual == expected


def test_claim_tokens_respects_sentence_boundaries():
    actual = _claim_tokens("Rebuilt something great. Handled onboarding for Acme Corp.")

    expected = ["Acme", "Corp"]
    assert actual == expected


def test_from_dir_reads_every_file(tmp_path):
    case = tmp_path / "case"
    (case / "wiki" / "experience").mkdir(parents=True)
    (case / "sections.json").write_text(json.dumps(SECTIONS))
    (case / "keywords.json").write_text(json.dumps(KEYWORDS))
    (case / "constraints.json").write_text(json.dumps(CONSTRAINTS))
    (case / "wiki" / "index.md").write_text(WIKI["index.md"])
    (case / "wiki" / "experience" / "story-001.md").write_text(WIKI["experience/story-001.md"])

    actual = TailorCase.from_dir(case)

    expected = CASE
    assert actual == expected


def test_host_tailor_from_output_defaults_no_coverage():
    actual = HostTailor.from_output(
        {"edits": [{"section": "summary", "op": "replace", "value": "x"}]}
    )

    expected = HostTailor(
        edits=[{"section": "summary", "op": "replace", "value": "x"}], no_coverage=False
    )
    assert actual == expected


def test_added_skill_matches_a_dated_bullet_ending_in_punctuation():
    """A raw \\b regex can't match the boundary after "C++" or "C#"; term_present() can."""
    sections = {
        **SECTIONS,
        "experience": [
            {**SECTIONS["experience"][0], "bullets": ["Wrote services in C++ for telemetry"]}
        ],
    }
    section_map = SectionMap.model_validate(sections)
    edits = [{"section": "skills", "op": "add", "value": "C++"}]

    actual = _skills_check(section_map, edits)

    expected = Check("added_skills_in_dated_bullets", True)
    assert actual == expected


def test_grounded_word_tokens_are_exact_matched_before_the_fuzzy_fallback():
    """A raw `in` substring check let "Go" pass against "golang" and "Rust" against "trust";
    term_present() is boundary-aware and rejects both. Fuzzy fallback is disabled here
    (empty source_tokens) so only the exact-match fix is under test."""
    actual = {
        "go_in_golang": _grounded("Go", "golang", set(), 85),
        "rust_in_trust": _grounded("Rust", "trust", set(), 85),
        "golang_in_golang": _grounded("Golang", "golang", set(), 85),
    }

    expected = {"go_in_golang": False, "rust_in_trust": False, "golang_in_golang": True}
    assert actual == expected
