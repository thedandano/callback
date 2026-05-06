"""Unit tests for pi_apply.extractor."""

import pytest

from pi_apply.extractor import MAX_FILE_BYTES, _parse_contact_info, extract, extract_sections
from pi_apply.section_map import ContactInfo


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


class TestContactInfoParsing:
    def test_email_extracted(self):
        lines = [
            "Jane Smith",
            "jane.smith@example.com",
            "San Francisco, CA",
        ]
        contact = _parse_contact_info(lines)
        assert contact.email == "jane.smith@example.com"

    def test_phone_extracted(self):
        lines = [
            "Jane Smith",
            "+1 (415) 555-1234",
            "San Francisco, CA",
        ]
        assert _parse_contact_info(lines) == ContactInfo(
            name="Jane Smith",
            phone="+1 (415) 555-1234",
            location="San Francisco, CA",
        )

    def test_name_extracted(self):
        lines = [
            "Jane Smith",
            "jane.smith@example.com",
            "+1 (415) 555-1234",
        ]
        contact = _parse_contact_info(lines)
        assert contact.name == "Jane Smith"

    def test_name_not_found_raises(self, tmp_path):
        # All lines are email/phone/URL — no candidate name line
        resume_text = (
            "jane.smith@example.com\n+1 (415) 555-1234\nhttps://linkedin.com/in/janesmith\n"
        )
        f = tmp_path / "resume.txt"
        f.write_text(resume_text, encoding="utf-8")
        with pytest.raises(ValueError, match="could not determine candidate name"):
            extract_sections(resume_text)
