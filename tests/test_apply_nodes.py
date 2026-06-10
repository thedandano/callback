"""Tests for real parse_initial and score_initial node implementations."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pi_apply.apply_nodes import parse_final, parse_initial, render, score_initial, tailor
from pi_apply.state import ApplyState, TailoredResume


def test_parse_initial_falls_back_to_text_extraction(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("EXPERIENCE\nAcme | Engineer\nBuilt REST API")
    state = ApplyState(
        session_id="s1",
        resume_label="resume",
        keywords={"required": ["Python"], "preferred": [], "required_years": 0.0},
    )
    with patch("pi_apply.apply_nodes.get_resume", return_value=str(resume)):
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


def test_render_produces_pdf_from_tailored_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="s1",
        tailored=TailoredResume(name="Jane Doe", summary="Experienced engineer"),
    )
    result = render(state)
    assert "pdf_path" in result
    assert "error" not in result
    pdf_file = tmp_path / "Jane_Doe_Company_Resume.pdf"
    assert pdf_file.exists()
    assert pdf_file.read_bytes()[:4] == b"%PDF"


def test_render_names_pdf_from_candidate_and_company(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    calls: list[str] = []

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        calls.append(output_path)
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("pi_apply.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="legacy-session-id",
        keywords={"company": "Brain Corp / Robotics"},
        tailored=TailoredResume(name="Dan Sedano", summary="Experienced engineer"),
    )

    expected_path = str(tmp_path / "Dan_Sedano_Brain_Corp_Robotics_Resume.pdf")
    result = render(state)

    assert calls == [expected_path]
    assert result == {"pdf_path": expected_path, "render_page_count": 1, "render_warnings": []}


def test_render_proper_cases_uppercase_name_and_company(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("pi_apply.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="caps-session",
        keywords={"company": "GOOGLE"},
        tailored=TailoredResume(name="DAN SEDANO", summary="Engineer"),
    )

    expected_path = str(tmp_path / "Dan_Sedano_Google_Resume.pdf")
    result = render(state)

    assert result == {"pdf_path": expected_path, "render_page_count": 1, "render_warnings": []}


def test_render_redirects_to_output_dir(tmp_path, monkeypatch):
    apps_dir = tmp_path / "apps"
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(apps_dir))
    output_dir = tmp_path / "sandbox_out"

    def fake_render_resume(_tailored: dict, output_path: str) -> dict:
        Path(output_path).write_bytes(b"%PDF fake")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    monkeypatch.setattr("pi_apply.apply_nodes.render_resume", fake_render_resume)
    state = ApplyState(
        session_id="redirect-session",
        keywords={"company": "Acme Corp"},
        tailored=TailoredResume(name="Jane Doe", summary="Engineer"),
        output_dir=str(output_dir),
    )

    expected_path = str(output_dir / "Jane_Doe_Acme_Corp_Resume.pdf")
    result = render(state)

    assert result == {"pdf_path": expected_path, "render_page_count": 1, "render_warnings": []}
    assert Path(expected_path).exists()
    assert not apps_dir.exists()


def test_render_halts_when_tailored_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(session_id="s3")
    result = render(state)
    assert "error" in result
    assert "pdf_path" not in result


def test_parse_final_returns_error_when_no_pdf_path(tmp_path):
    state = ApplyState(session_id="s3", pdf_path=None)
    result = parse_final(state)
    assert "error" in result
    assert "parsed_final" not in result


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

    def test_tailor_no_coverage_returns_empty(self):
        state = ApplyState(session_id="s", no_coverage=True)
        result = tailor(state)
        assert result == {}

    def test_tailor_missing_tailored_sections_returns_error(self):
        state = ApplyState(session_id="s")
        assert tailor(state) == {"error": "tailor: no tailored_sections and no_coverage not set"}
