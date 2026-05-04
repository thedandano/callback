"""Unit tests for pi_apply.extractor."""

import pytest

from pi_apply.extractor import MAX_FILE_BYTES, extract


class TestTxtExtraction:
    def test_extracts_plain_text(self, tmp_path):
        f = tmp_path / "resume.txt"
        f.write_text("Python developer\nFastAPI experience", encoding="utf-8")
        assert extract(f) == "Python developer\nFastAPI experience"

    def test_strips_surrounding_whitespace(self, tmp_path):
        f = tmp_path / "resume.txt"
        f.write_text("  hello  \n", encoding="utf-8")
        assert extract(f) == "hello"


class TestUnsupportedFormat:
    def test_raises_value_error_for_unknown_extension(self, tmp_path):
        f = tmp_path / "resume.rtf"
        f.write_bytes(b"content")
        with pytest.raises(ValueError, match="unsupported format"):
            extract(f)


class TestFileSizeGuard:
    def test_raises_value_error_when_over_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with pytest.raises(ValueError, match="too large"):
            extract(f)


class TestMissingFile:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "nonexistent.txt")
