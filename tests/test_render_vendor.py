"""Tests for callback.render (HTML + Playwright)."""

import tempfile
from pathlib import Path

import callback.render
from callback.render import render_resume


def test_render_importable():
    assert callback.render is not None


def test_render_resume_importable():
    assert render_resume is not None


def test_no_tex_builder():
    assert getattr(callback.render, "CanonicalTeXBuilder", None) is None


def test_render_resume_produces_pdf():
    with tempfile.TemporaryDirectory() as tmp:
        out = str(Path(tmp) / "test.pdf")
        result = render_resume({"name": "Test User"}, out)
        assert result["success"] is True
        assert Path(out).exists()
        assert Path(out).read_bytes()[:4] == b"%PDF"


def test_render_resume_returns_error_on_missing_output_parent(tmp_path):
    out = tmp_path / "missing-parent" / "out.pdf"
    result = render_resume({"name": "Test"}, str(out))
    assert result["success"] is False
    assert "error" in result
    assert not out.exists()
