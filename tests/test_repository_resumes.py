"""Unit tests for callback.repository.resumes."""

from pathlib import Path

import pytest

from callback.repository.resumes import (
    ResumeNotFoundError,
    clear_resumes,
    data_dir,
    get_resume,
    list_resumes,
    save_resume,
)


class TestSaveGetRoundTrip:
    def test_save_and_get_txt_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        source_file = tmp_path / "my_resume.txt"
        source_file.write_text("Python developer with FastAPI experience")

        returned_path = save_resume("backend", str(source_file))

        retrieved_path = get_resume("backend")

        assert retrieved_path == returned_path
        assert Path(retrieved_path).exists()
        assert Path(retrieved_path).read_text() == "Python developer with FastAPI experience"

    def test_save_and_get_pdf_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        source_file = tmp_path / "resume.pdf"
        source_file.write_bytes(b"%PDF-1.4 fake pdf content")

        save_resume("fullstack", str(source_file))

        retrieved_path = get_resume("fullstack")

        assert Path(retrieved_path).exists()
        assert Path(retrieved_path).read_bytes() == b"%PDF-1.4 fake pdf content"


class TestOverwriteBehaviour:
    def test_save_twice_overwrites_silently(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        source_v1 = tmp_path / "resume_v1.txt"
        source_v1.write_text("Version 1 content")

        save_resume("dev", str(source_v1))

        source_v2 = tmp_path / "resume_v2.txt"
        source_v2.write_text("Version 2 content")

        save_resume("dev", str(source_v2))

        retrieved_path = get_resume("dev")
        assert Path(retrieved_path).read_text() == "Version 2 content"


class TestListEmptyDir:
    def test_list_resumes_returns_empty_list_when_dir_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        result = list_resumes()

        assert result == []


class TestGetMissingRaises:
    def test_get_resume_nonexistent_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        with pytest.raises(ResumeNotFoundError, match="Resume 'nonexistent' not found"):
            get_resume("nonexistent")

    def test_get_resume_after_dir_created_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        data_dir().mkdir(parents=True, exist_ok=True)

        with pytest.raises(ResumeNotFoundError, match="Resume 'missing' not found"):
            get_resume("missing")


class TestXDGOverride:
    def test_xdg_data_home_override(self, tmp_path, monkeypatch):
        xdg_custom = tmp_path / "custom_xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_custom))

        source_file = tmp_path / "source.txt"
        source_file.write_text("Test content")

        returned_path = save_resume("test", str(source_file))

        assert xdg_custom in Path(returned_path).parents
        assert Path(returned_path).exists()
        assert Path(returned_path).read_text() == "Test content"

    def test_data_dir_respects_xdg_data_home(self, tmp_path, monkeypatch):
        xdg_custom = tmp_path / "my_xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_custom))

        result = data_dir()

        assert result == xdg_custom / "callback" / "inputs"


class TestMultipleFormats:
    def test_list_resumes_multiple_extensions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        source_txt = tmp_path / "resume.txt"
        source_txt.write_text("txt content")
        save_resume("alice", str(source_txt))

        source_md = tmp_path / "resume.md"
        source_md.write_text("md content")
        save_resume("bob", str(source_md))

        result = list_resumes()

        assert set(result) == {"alice", "bob"}

    def test_get_resume_finds_any_supported_extension(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        source_file = tmp_path / "resume.docx"
        source_file.write_bytes(b"docx fake content")

        returned_path = save_resume("manager", str(source_file))
        retrieved_path = get_resume("manager")

        assert returned_path == retrieved_path


class TestClearResumes:
    def test_clears_all_resume_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        src = tmp_path / "resume.txt"
        src.write_text("content")
        save_resume("primary", str(src))

        src2 = tmp_path / "old.pdf"
        src2.write_bytes(b"old")
        save_resume("old_label", str(src2))

        clear_resumes()

        assert list_resumes() == []

    def test_no_op_when_dir_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        clear_resumes()  # must not raise
