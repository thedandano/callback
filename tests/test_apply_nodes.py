"""Tests for real parse_initial and score_initial node implementations."""

import pytest

from pi_apply.apply_nodes import parse_final, parse_initial, render, score_initial
from pi_apply.state import ApplyState, TailoredResume


def test_parse_initial_falls_back_to_text_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("EXPERIENCE\nAcme | Engineer\nBuilt REST API")
    state = ApplyState(
        session_id="s1",
        resume_path=str(resume),
        keywords={"required": ["Python"], "preferred": [], "required_years": 0.0},
    )
    result = parse_initial(state)
    expected = {
        "parsed_initial": "EXPERIENCE\nAcme | Engineer\nBuilt REST API",
        "resume_label": "resume",
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
    pdf_file = tmp_path / "s1.pdf"
    assert pdf_file.exists()
    assert pdf_file.read_bytes()[:4] == b"%PDF"


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
