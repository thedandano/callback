"""Unit tests for callback.bridge module."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


def test_resolution_failure_raises_environment_error(monkeypatch):
    """Test that missing binary raises EnvironmentError at import time."""
    # Remove GO_APPLY_BIN from environment
    monkeypatch.delenv("GO_APPLY_BIN", raising=False)

    # Patch shutil.which to return None
    monkeypatch.setattr("shutil.which", lambda _: None)

    # Remove the module from sys.modules to force reimport
    sys.modules.pop("callback.bridge", None)

    # Attempt to import should raise EnvironmentError
    with pytest.raises(EnvironmentError, match="GO_APPLY_BIN"):
        importlib.import_module("callback.bridge")

    # Clean up for other tests
    sys.modules.pop("callback.bridge", None)


def test_resolution_from_env_var(monkeypatch, tmp_path):
    """Test that GO_APPLY_BIN env var is used when valid."""
    # Create a fake binary file
    fake_bin = tmp_path / "go-apply"
    fake_bin.touch()

    # Set env var
    monkeypatch.setenv("GO_APPLY_BIN", str(fake_bin))

    # Remove the module to force reimport
    sys.modules.pop("callback.bridge", None)

    # Import should succeed
    bridge = importlib.import_module("callback.bridge")
    assert str(fake_bin) == bridge._BIN

    # Clean up
    sys.modules.pop("callback.bridge", None)


def test_resolution_from_path(monkeypatch):
    """Test that shutil.which is used as fallback."""
    fake_bin_path = "/fake/path/go-apply"

    # Remove GO_APPLY_BIN from environment
    monkeypatch.delenv("GO_APPLY_BIN", raising=False)

    # Patch shutil.which to return a valid path
    monkeypatch.setattr("shutil.which", lambda _: fake_bin_path)

    # Remove the module to force reimport
    sys.modules.pop("callback.bridge", None)

    # Import should succeed
    bridge = importlib.import_module("callback.bridge")
    assert fake_bin_path == bridge._BIN

    # Clean up
    sys.modules.pop("callback.bridge", None)


def test_run_pdfrender_success():
    """Test successful run_pdfrender execution."""
    import callback.bridge as bridge

    expected_output = b"pdf-bytes"

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = expected_output
        mock_result.stderr = b""
        mock_run.return_value = mock_result

        result = bridge.run_pdfrender(["pdfrender", "test.pdf"])

        assert result == expected_output
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][0] == bridge._BIN
        assert call_args[0][0][1:] == ["pdfrender", "test.pdf"]
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["check"] is False


def test_run_pdfrender_failure():
    """Test run_pdfrender raises SubprocessError on failure."""
    import callback.bridge as bridge

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = b""
        mock_result.stderr = b"error detail"
        mock_run.return_value = mock_result

        with pytest.raises(bridge.SubprocessError) as exc_info:
            bridge.run_pdfrender(["pdfrender", "test.pdf"])

        error = exc_info.value
        assert error.returncode == 1
        assert error.stderr == "error detail"
        assert "pdfrender" in str(error.cmd)


def test_run_survival_success():
    """Test successful run_survival execution."""
    import callback.bridge as bridge

    expected_output = "test output"

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = expected_output.encode()
        mock_result.stderr = b""
        mock_run.return_value = mock_result

        result = bridge.run_survival(["survival", "test"])

        assert result == expected_output
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0][0] == bridge._BIN
        assert call_args[0][0][1:] == ["survival", "test"]
        assert call_args[1]["capture_output"] is True
        assert call_args[1]["check"] is False


def test_run_survival_failure():
    """Test run_survival raises SubprocessError on failure."""
    import callback.bridge as bridge

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = b""
        mock_result.stderr = b"survival error"
        mock_run.return_value = mock_result

        with pytest.raises(bridge.SubprocessError) as exc_info:
            bridge.run_survival(["survival", "test"])

        error = exc_info.value
        assert error.returncode == 2
        assert error.stderr == "survival error"
        assert "survival" in str(error.cmd)


def test_subprocess_error_attributes():
    """Test SubprocessError has correct attributes."""
    import callback.bridge as bridge

    cmd = ["test", "command"]
    returncode = 42
    stderr = "test error"

    error = bridge.SubprocessError(cmd=cmd, returncode=returncode, stderr=stderr)

    assert error.cmd == cmd
    assert error.returncode == returncode
    assert error.stderr == stderr
    assert "test" in str(error)
    assert "command" in str(error)
    assert "42" in str(error)
    assert "test error" in str(error)
