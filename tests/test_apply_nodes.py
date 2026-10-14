"""Tests for real parse_initial and score_initial node implementations."""

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from callback import apply_nodes
from callback.apply_nodes import (
    _candidate_experience_years,
    finalize,
    parse_final,
    parse_initial,
    render,
    score_final,
    score_initial,
    tailor,
)
from callback.repository import stories
from callback.section_map import ExperienceEntry
from callback.state import ApplyState, CreatedStory, TailoredResume
from callback.wiki import WikiStore


def test_parse_initial_falls_back_to_text_extraction(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("EXPERIENCE\nAcme | Engineer\nBuilt REST API")
    state = ApplyState(
        session_id="s1",
        resume_label="resume",
        keywords={"required": ["Python"], "preferred": [], "required_years": 0.0},
    )
    with patch("callback.apply_nodes.get_resume", return_value=str(resume)):
        result = parse_initial(state)
    expected = {
        "parsed_initial": "EXPERIENCE\nAcme | Engineer\nBuilt REST API",
    }
    assert result == expected


def test_score_initial_produces_score_gap(tmp_path):
    state = ApplyState(
        session_id="s1",
        parsed_initial="Python developer with AWS experience",
        keywords={"required": ["Python", "Go"], "preferred": ["AWS"], "required_years": 0.0},
    )
    result = score_initial(state)
    score = result["score_initial"]
    assert "req_unmatched" in score
    assert "Go" in score["req_unmatched"]
    assert "Python" not in score["req_unmatched"]


def test_score_initial_raises_on_missing_keywords(tmp_path):
    state = ApplyState(session_id="s1", parsed_initial="some resume text", keywords=None)
    with pytest.raises(ValueError, match="keywords"):
        score_initial(state)


def test_score_initial_succeeds_with_only_preferred_keywords(tmp_path):
    """A posting with no stated hard requirements (real example: a Qualcomm req whose
    Minimum Qualifications section ships empty) has nothing for 'required', but
    genuinely extracted preferred/preferred_any is still scoreable."""
    state = ApplyState(
        session_id="s1",
        parsed_initial="Experienced with Python and Git",
        keywords={
            "required": [],
            "required_any": [],
            "preferred": ["Python"],
            "preferred_any": [["Git", "Perforce"]],
            "required_years": 0.0,
        },
    )
    result = score_initial(state)
    actual = {
        "required_coverage": result["score_initial"]["required_coverage"],
        "preferred_coverage": result["score_initial"]["preferred_coverage"],
    }
    expected = {"required_coverage": None, "preferred_coverage": 100.0}
    assert actual == expected


def test_render_produces_pdf_from_tailored_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))
    state = ApplyState(
        session_id="s1",
        tailored=TailoredResume(name="Jane Doe", summary="Experienced engineer"),
    )
    result = render(state)
    assert "pdf_path" in result
    assert "error" not in result
    pdf_file = tmp_path / "2026-10-12" / "job" / "Jane_Doe_Company_Resume.pdf"
    assert pdf_file.exists()
    assert pdf_file.read_bytes()[:4] == b"%PDF"


def test_render_names_pdf_from_candidate_and_company(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))
    calls: list[str] = []

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        calls.append(output_path)
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("callback.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="legacy-session-id",
        keywords={"company": "Brain Corp Robotics"},
        tailored=TailoredResume(name="Jane Doe", summary="Experienced engineer"),
    )

    folder = tmp_path / "2026-10-12" / "brain-corp-robotics"
    expected_path = str(folder / "Jane_Doe_Brain_Corp_Robotics_Resume.pdf")
    result = render(state)

    assert calls == [expected_path]
    assert result == {
        "pdf_path": expected_path,
        "render_page_count": 1,
        "render_warnings": [],
        "artifact_dir": str(folder),
    }


def test_render_proper_cases_uppercase_name_and_company(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("callback.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="caps-session",
        keywords={"company": "GOOGLE"},
        tailored=TailoredResume(name="JANE DOE", summary="Engineer"),
    )

    folder = tmp_path / "2026-10-12" / "google"
    expected_path = str(folder / "Jane_Doe_Google_Resume.pdf")
    result = render(state)

    assert result == {
        "pdf_path": expected_path,
        "render_page_count": 1,
        "render_warnings": [],
        "artifact_dir": str(folder),
    }


def test_render_redirects_to_output_dir(tmp_path, monkeypatch):
    apps_dir = tmp_path / "apps"
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(apps_dir))
    output_dir = tmp_path / "sandbox_out"

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("callback.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="redirect-session",
        keywords={"company": "Acme Corp"},
        tailored=TailoredResume(name="Jane Doe", summary="Engineer"),
        output_dir=str(output_dir),
    )

    expected_path = str(output_dir / "Jane_Doe_Acme_Corp_Resume.pdf")
    result = render(state)

    assert result == {
        "pdf_path": expected_path,
        "render_page_count": 1,
        "render_warnings": [],
    }
    assert Path(expected_path).exists()
    assert not apps_dir.exists()


def test_retry_without_output_dir_uses_the_dated_default_not_the_earlier_explicit_dir(
    tmp_path, monkeypatch
):
    apps_dir = tmp_path / "apps"
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(apps_dir))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("callback.apply_nodes.render_resume", fake_render_resume)
    fields: dict[str, Any] = {
        "session_id": "retry-session",
        "keywords": {"company": "Acme Corp"},
        "tailored": TailoredResume(name="Jane Doe", summary="Engineer"),
    }
    explicit = tmp_path / "sandbox_out"

    first = render(ApplyState(**fields, output_dir=str(explicit)))
    retry = render(ApplyState(**fields, artifact_dir=first.get("artifact_dir")))

    dated = apps_dir / "2026-10-12" / "acme-corp"
    assert {
        "first_stored_dir": first.get("artifact_dir"),
        "retry_dir": retry["artifact_dir"],
        "retry_pdf": retry["pdf_path"],
    } == {
        "first_stored_dir": None,
        "retry_dir": str(dated),
        "retry_pdf": str(dated / "Jane_Doe_Acme_Corp_Resume.pdf"),
    }


def test_render_halts_when_tailored_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    state = ApplyState(session_id="s3")
    result = render(state)
    assert "error" in result
    assert "pdf_path" not in result


def test_parse_final_returns_error_when_no_pdf_path(tmp_path):
    state = ApplyState(session_id="s3", pdf_path=None)
    result = parse_final(state)
    assert "error" in result
    assert "parsed_final" not in result


def test_parse_final_returns_error_when_extract_raises(tmp_path, monkeypatch):
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"not empty")

    def raising_extract(path):
        raise RuntimeError("corrupt pdf")

    monkeypatch.setattr("callback.apply_nodes.resume_extractor.extract", raising_extract)

    state = ApplyState(session_id="s3", pdf_path=str(pdf_path))
    actual = parse_final(state)
    expected = {"error": "parse_final: extract failed: corrupt pdf"}
    assert actual == expected


def test_parse_final_returns_error_when_stat_raises(tmp_path, monkeypatch):
    """A PDF that vanishes between exists() and stat() must land in the retriable
    error path, not escape as an unhandled OSError."""
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"not empty")

    def raising_stat(self, *args, **kwargs):
        raise OSError("stale file handle")

    monkeypatch.setattr(Path, "stat", raising_stat)

    state = ApplyState(session_id="s3", pdf_path=str(pdf_path))
    actual = parse_final(state)
    expected = {"error": "parse_final: extract failed: stale file handle"}
    assert actual == expected


def test_finalize_returns_error_when_archive_write_raises_oserror(tmp_path, monkeypatch):
    import callback.apply_nodes as apply_nodes_module

    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))

    def raising_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(apply_nodes_module, "open", raising_open, raising=False)

    state = ApplyState(session_id="s3")
    actual = finalize(state)
    expected = {
        "error": "finalize: cannot write archive: disk full",
        "artifact_dir": str(tmp_path / "2026-10-12" / "job"),
    }
    assert actual == expected


def test_finalize_returns_error_when_apps_dir_unwritable(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    unwritable_apps_dir = blocker / "apps"
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(unwritable_apps_dir))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))
    unwritable_folder = unwritable_apps_dir / "2026-10-12" / "job"

    try:
        unwritable_folder.mkdir(parents=True, exist_ok=True)
        raise AssertionError("expected mkdir under a regular file to raise OSError")
    except OSError as exc:
        expected_reason = exc

    state = ApplyState(session_id="s3")
    actual = finalize(state)
    expected_message = f"finalize: cannot create apps dir {unwritable_folder}: {expected_reason}"
    expected = {"error": expected_message, "artifact_dir": str(unwritable_folder)}
    assert actual == expected


def test_render_failure_still_pins_the_dated_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr("callback.apply_nodes._today", lambda: date(2026, 10, 12))
    monkeypatch.setattr(
        "callback.apply_nodes.render_resume",
        lambda _tailored, _output_path: {"success": False, "error": "chromium crashed"},
    )
    state = ApplyState(
        session_id="s4",
        keywords={"company": "Acme", "title": "Engineer"},
        tailored=TailoredResume(name="Jane Doe", summary="Experienced engineer"),
    )

    actual = render(state)

    assert actual == {
        "error": "render: chromium crashed",
        "artifact_dir": str(tmp_path / "2026-10-12" / "acme-engineer"),
    }


def test_render_failure_with_explicit_output_dir_stores_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "callback.apply_nodes.render_resume",
        lambda _tailored, _output_path: {"success": False, "error": "chromium crashed"},
    )
    state = ApplyState(
        session_id="s5",
        output_dir=str(tmp_path / "out"),
        tailored=TailoredResume(name="Jane Doe", summary="Experienced engineer"),
    )

    assert render(state) == {"error": "render: chromium crashed"}


def test_finalize_writes_archive_to_output_dir(tmp_path, monkeypatch):
    """finalize writes the JSON archive under output_dir when set, not the default apps dir."""
    apps_dir = tmp_path / "apps"
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(apps_dir))
    output_dir = tmp_path / "sandbox_out"
    output_dir.mkdir()

    state = ApplyState(session_id="redirect-session", output_dir=str(output_dir))
    result = finalize(state)

    expected_archive = output_dir / "redirect-session.json"
    actual = {
        "has_error": "error" in result,
        "archive_in_output_dir": expected_archive.exists(),
        "no_archive_in_apps_dir": not (apps_dir / "redirect-session.json").exists(),
    }
    assert actual == {
        "has_error": False,
        "archive_in_output_dir": True,
        "no_archive_in_apps_dir": True,
    }


class TestTailorNode:
    def test_tailor_with_tailored_sections_converts_section_map(self):
        state = ApplyState(
            session_id="s",
            tailored_sections={
                "contact": {"name": "Jane Doe"},
                "skills": {"flat": ["Python"], "categorized": {}},
                "experience": [
                    {
                        "company": "Acme",
                        "role": "Engineer",
                        "start_date": "2020-01",
                        "end_date": "2023-06",
                        "bullets": ["Built REST API"],
                    }
                ],
            },
        )
        result = tailor(state)
        tailored = result["tailored"]
        assert tailored.candidate_experience_years == pytest.approx(3.49, abs=0.02)
        assert tailored.model_copy(update={"candidate_experience_years": None}) == TailoredResume(
            name="Jane Doe",
            skills_raw="Additional: Python",
            experience_raw="Acme\nEngineer | 2020-01 – 2023-06\n• Built REST API",
            max_pages=1,
        )

    def test_tailor_uses_jd_title_when_summary_has_no_title_line(self):
        state = ApplyState(
            session_id="s",
            keywords={"title": "Staff Software Engineer, Applied AI"},
            tailored_sections={
                "contact": {"name": "Jane Doe"},
                "summary": "Backend engineer with applied AI experience.",
                "skills": {"flat": ["Python"], "categorized": {}},
                "experience": [],
            },
        )

        result = tailor(state)

        actual = {
            "title": result["tailored"].title,
            "summary": result["tailored"].summary,
        }
        expected = {
            "title": "STAFF SOFTWARE ENGINEER, APPLIED AI",
            "summary": "Backend engineer with applied AI experience.",
        }

        assert actual == expected

    def test_tailor_no_coverage_returns_empty(self):
        state = ApplyState(session_id="s", no_coverage=True)
        result = tailor(state)
        assert result == {}

    def test_tailor_missing_tailored_sections_returns_error(self):
        state = ApplyState(session_id="s")
        assert tailor(state) == {"error": "tailor: no tailored_sections and no_coverage not set"}


class TestCandidateExperienceYears:
    def test_overlapping_roles_do_not_double_count(self):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12"),
            ExperienceEntry(company="B", role="Eng", start_date="2020-06", end_date="2021-12"),
        ]
        # merged Jan 2020 – Dec 2021 = 24 months, not 12 + 19 = 31
        assert _candidate_experience_years(experience) == 2.0

    def test_disjoint_roles_sum(self):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-06"),
            ExperienceEntry(company="B", role="Eng", start_date="2022-01", end_date="2022-06"),
        ]
        assert _candidate_experience_years(experience) == 1.0

    def test_all_unparseable_returns_none(self):
        experience = [ExperienceEntry(company="A", role="Eng", start_date="??", end_date=None)]
        assert _candidate_experience_years(experience) is None


def test_parse_initial_migrates_legacy_stories_before_reading_the_wiki(tmp_path, monkeypatch):

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path / "wiki")
    monkeypatch.setattr("callback.repository.stories.list_resumes", lambda: ["primary"])
    data_dir = tmp_path / "callback"
    data_dir.mkdir(parents=True, exist_ok=True)
    legacy = {
        "id": "story-001",
        "primary_skill": "Python",
        "skills": ["Python"],
        "story_type": "SBI",
        "job_title": "Project",
        "situation": "s",
        "behavior": "b",
        "impact": "i",
    }
    (data_dir / "accomplishments.json").write_text(
        json.dumps({"schema_version": "1", "onboard_text": "", "created_stories": [legacy]})
    )
    WikiStore().write_page("primary", "experience/story-001.md", "# Python — Sbi\n\nold render\n")

    parse_initial(ApplyState(session_id="s", resume_label="primary"))

    listed, warnings = stories.list_stories("primary")
    actual = {"stories": listed, "warnings": warnings}
    expected = {"stories": [CreatedStory(**legacy)], "warnings": []}
    assert actual == expected


class TestDecisionLabels:
    def test_experience_years_computed(self, decisions):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12")
        ]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "computed"}

    def test_experience_years_partial_when_an_entry_is_skipped(self, decisions):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12"),
            ExperienceEntry(company="B", role="Eng", start_date="??", end_date=None),
        ]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "partial"}

    def test_experience_years_unavailable(self, decisions):
        experience = [ExperienceEntry(company="A", role="Eng", start_date="??", end_date=None)]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "unavailable"}

    def test_experience_years_partial_when_an_entry_ends_before_it_starts(self, decisions):
        experience = [
            ExperienceEntry(company="A", role="Eng", start_date="2020-01", end_date="2020-12"),
            ExperienceEntry(company="B", role="Eng", start_date="2022-05", end_date="2021-01"),
        ]

        _candidate_experience_years(experience)

        assert decisions == {"experience_years": "partial"}

    def test_score_nodes_label_experience_as_not_scored_without_a_years_requirement(
        self, decisions
    ):
        keywords = {"required": ["Python"], "preferred": [], "required_years": 0}

        score_initial(
            ApplyState(session_id="s", parsed_initial="Python engineer", keywords=keywords)
        )
        after_initial = dict(decisions)
        decisions.clear()
        score_final(ApplyState(session_id="s", parsed_final="Python engineer", keywords=keywords))

        actual = {"initial": after_initial, "final": decisions}
        expected = {
            "initial": {"experience_evaluated": False, "no_section_headers": True},
            "final": {"experience_evaluated": False},
        }
        assert actual == expected

    def test_score_nodes_label_experience_as_scored_with_a_years_requirement(self, decisions):
        keywords = {"required": ["Python"], "preferred": [], "required_years": 3}

        score_initial(
            ApplyState(
                session_id="s",
                parsed_initial="Python engineer",
                keywords=keywords,
                candidate_years=5.0,
            )
        )

        assert decisions == {"experience_evaluated": True, "no_section_headers": True}

    def test_score_initial_labels_a_resume_with_section_headers(self, decisions):
        keywords = {"required": ["Python"], "preferred": [], "required_years": 0}
        resume = "Experience\nPython engineer\n\nEducation\nBS\n\nSkills\nPython\n"

        score_initial(ApplyState(session_id="s", parsed_initial=resume, keywords=keywords))

        assert decisions == {"experience_evaluated": False, "no_section_headers": False}


@pytest.mark.parametrize(
    ("fields", "expected_suffix"),
    [
        ({}, "apps/2026-10-12/expertvoice-frontend-ai-engineer"),
        ({"output_dir": "OUT"}, "OUT"),
        ({"output_dir": "OUT", "artifact_dir": "STORED"}, "OUT"),
        ({"artifact_dir": "STORED"}, "STORED"),
    ],
)
def test_artifact_dir_prefers_output_dir_then_stored_then_dated_default(
    fields, expected_suffix, tmp_path, monkeypatch
):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path / "apps"))
    monkeypatch.setattr(apply_nodes, "_today", lambda: date(2026, 10, 12))
    absolute: dict[str, Any] = {k: str(tmp_path / v) for k, v in fields.items()}
    state = ApplyState(
        session_id="s1",
        keywords={"company": "ExpertVoice", "title": "Frontend AI Engineer"},
        **absolute,
    )
    assert apply_nodes._artifact_dir(state) == tmp_path / expected_suffix


def test_render_stores_the_folder_it_used(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACK_APPS_DIR", str(tmp_path))
    monkeypatch.setattr(apply_nodes, "_today", lambda: date(2026, 10, 12))
    monkeypatch.setattr(
        apply_nodes, "render_resume", lambda data, path: {"success": True, "page_count": 1}
    )
    state = ApplyState(
        session_id="s1",
        keywords={"company": "Acme", "title": "Engineer"},
        tailored=TailoredResume(name="Jane Doe"),
    )
    folder = tmp_path / "2026-10-12" / "acme-engineer"
    assert apply_nodes.render(state) == {
        "pdf_path": str(folder / "Jane_Doe_Acme_Resume.pdf"),
        "render_page_count": 1,
        "render_warnings": [],
        "artifact_dir": str(folder),
    }
