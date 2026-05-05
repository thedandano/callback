"""Tests for pi_apply.render (typst-based)."""

import tempfile
from pathlib import Path

import pi_apply.render
from pi_apply.render import render_resume


def test_render_importable():
    assert pi_apply.render is not None


def test_render_resume_importable():
    assert render_resume is not None


def test_no_tex_builder():
    assert getattr(pi_apply.render, "CanonicalTeXBuilder", None) is None


def test_render_resume_produces_pdf():
    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "test.pdf")
        result = render_resume({"name": "Test User"}, out)
        assert result["success"] is True
        assert Path(out).exists()
        assert Path(out).read_bytes()[:4] == b"%PDF"


def test_render_resume_returns_error_on_bad_template(monkeypatch):
    import pi_apply.render.typst_builder as tb

    monkeypatch.setattr(tb, "TEMPLATE_PATH", Path("/nonexistent/template.typ"))
    result = render_resume({"name": "Test"}, "/tmp/out.pdf")
    assert result["success"] is False
    assert "error" in result
