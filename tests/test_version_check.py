"""Tests for callback.version_check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import callback.version_check as vc


def _reset_cache():
    vc._cached = None


def test_update_available():
    _reset_cache()

    mock_response = MagicMock()
    mock_response.json.return_value = {"tag_name": "v9.9.9"}

    with (
        patch.object(vc, "fetch_latest_tag", return_value="v9.9.9"),
        patch.object(vc, "_current_version", return_value="0.2.0"),
    ):
        result = vc.check_update()

    assert result == {
        "checked": True,
        "current": "0.2.0",
        "latest": "v9.9.9",
        "update_available": True,
    }


def test_already_current():
    _reset_cache()

    with (
        patch.object(vc, "fetch_latest_tag", return_value="v0.2.0"),
        patch.object(vc, "_current_version", return_value="0.2.0"),
    ):
        result = vc.check_update()

    assert result == {
        "checked": True,
        "current": "0.2.0",
        "latest": "v0.2.0",
        "update_available": False,
    }


def test_network_error_returns_unchecked():
    _reset_cache()

    with patch.object(vc, "fetch_latest_tag", return_value=None):
        result = vc.check_update()

    assert result == {"checked": False}


def test_cached_result_no_second_network_call():
    _reset_cache()

    with (
        patch.object(vc, "fetch_latest_tag", return_value="v1.0.0") as mock_fetch,
        patch.object(vc, "_current_version", return_value="0.2.0"),
    ):
        first = vc.check_update()
        second = vc.check_update()

    assert first is second
    mock_fetch.assert_called_once()
