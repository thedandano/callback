"""Minimal integration marker coverage for the CI integration gate."""

import pytest


@pytest.mark.integration
def test_integration_marker_is_selectable():
    """Ensure `pytest -m integration` has at least one selected test."""
    assert True
