"""Tests for wired render and parse_final nodes."""

from pi_apply import extractor as resume_extractor
from pi_apply.apply_nodes import parse_final, render
from pi_apply.render.typst_builder import render_resume
from pi_apply.state import ApplyState, TailoredResume


def test_render_produces_real_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="s1",
        tailored=TailoredResume(name="Jane Doe", summary="Python engineer"),
    )
    result = render(state)
    expected_path = str(tmp_path / "s1.pdf")
    assert result == {"pdf_path": expected_path}
    with open(expected_path, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_render_keyword_round_trip(tmp_path, monkeypatch):
    """skills_raw keyword survives render → extract round-trip."""
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="s2",
        tailored=TailoredResume(name="Jane Doe", skills_raw="Tools: Apache Kafka"),
    )
    render_result = render(state)
    assert render_result == {"pdf_path": str(tmp_path / "s2.pdf")}

    pdf_path = render_result["pdf_path"]
    parse_state = ApplyState(session_id="s2", pdf_path=pdf_path)
    parse_result = parse_final(parse_state)
    expected_text = resume_extractor.extract(pdf_path)
    assert parse_result == {"parsed_final": expected_text}
    assert "Apache Kafka" in parse_result["parsed_final"]


def test_render_halts_when_tailored_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(session_id="s3")
    result = render(state)
    assert result == {"error": "render: state.tailored is None — tailor node must run first"}


def test_render_resume_inter_font_produces_valid_pdf(tmp_path):
    """render_resume() with bundled Inter font produces a valid PDF."""
    output_path = str(tmp_path / "inter_test.pdf")
    result = render_resume({"name": "Inter Test"}, output_path)
    assert result == {"success": True, "pdf_path": output_path}
    with open(output_path, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_parse_final_halts_on_missing_pdf_path():
    state = ApplyState(session_id="s4", pdf_path=None)
    result = parse_final(state)
    assert result == {"error": "parse_final: no pdf_path in state"}


def test_parse_final_halts_on_missing_file(tmp_path):
    path = str(tmp_path / "nonexistent.pdf")
    state = ApplyState(session_id="s5", pdf_path=path)
    assert parse_final(state) == {"error": f"parse_final: pdf file not found: {path}"}
