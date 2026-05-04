"""Tests for real parse_initial and score_initial node implementations."""

from pi_apply.apply_nodes import parse_initial, score_initial
from pi_apply.state import ApplyState


def test_parse_initial_falls_back_to_text_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    resume = tmp_path / "resume.txt"
    resume.write_text("EXPERIENCE\nAcme | Engineer\nBuilt REST API")
    state = ApplyState(session_id="s1", resume_path=str(resume), keywords={"required": ["Python"]})
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
        keywords={"required": ["Python", "Go"], "preferred": ["AWS"]},
    )
    result = score_initial(state)
    score = result["score_initial"]
    assert "req_unmatched" in score
    assert "Go" in score["req_unmatched"]
    assert "Python" not in score["req_unmatched"]


def test_score_initial_returns_stub_for_noop(tmp_path):
    state = ApplyState(session_id="s1", parsed_initial="<noop:parse:no-source>", keywords=None)
    result = score_initial(state)
    assert result["score_initial"].get("stub") is True
