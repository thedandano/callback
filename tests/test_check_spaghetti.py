"""Tests for check_spaghetti.py wrapper."""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.local


@pytest.fixture
def fixtures_dir():
    """Return the ai-slop-score fixtures directory."""
    return Path("~/.claude/skills/ai-slop-score/assets/fixtures")


@pytest.fixture
def check_script():
    """Return the path to check_spaghetti.py."""
    return Path(__file__).parent.parent / "scripts" / "check_spaghetti.py"


def run_check(script_path, repo_path, threshold=None):
    """Run the check_spaghetti.py script as a subprocess."""
    cmd = ["python3", str(script_path)]
    if threshold is not None:
        cmd.extend(["--threshold", str(threshold)])
    cmd.append(str(repo_path))

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result


def test_clean_python_low_band_exits_zero(fixtures_dir, check_script):
    """clean-python fixture scores low (6), so wrapper should exit 0."""
    repo = fixtures_dir / "clean-python"
    result = run_check(check_script, repo)
    assert result.returncode == 0
    assert "score=6 band=low" in result.stdout


def test_legacy_monolith_extreme_band_exits_nonzero(fixtures_dir, check_script):
    """legacy-monolith fixture scores extreme (64), so wrapper should exit 1."""
    repo = fixtures_dir / "legacy-monolith"
    result = run_check(check_script, repo)
    assert result.returncode != 0
    assert "score=64 band=extreme" in result.stdout


def test_mixed_service_high_band_exits_nonzero(fixtures_dir, check_script):
    """mixed-service fixture scores moderate (36), so wrapper should exit 1."""
    repo = fixtures_dir / "mixed-service"
    result = run_check(check_script, repo)
    assert result.returncode != 0
    assert "score=36 band=moderate" in result.stdout


def test_threshold_override_permits_higher_score(fixtures_dir, check_script):
    """Override threshold to 50; mixed-service score 36 should exit 0."""
    repo = fixtures_dir / "mixed-service"
    result = run_check(check_script, repo, threshold=50)
    assert result.returncode == 0
    assert "score=36 band=moderate" in result.stdout


def test_threshold_at_boundary_blocks_exactly(fixtures_dir, check_script):
    """At threshold=36, score 36 should exit non-zero (not >=)."""
    repo = fixtures_dir / "mixed-service"
    result = run_check(check_script, repo, threshold=36)
    assert result.returncode != 0
    assert "score=36 band=moderate" in result.stdout


def test_threshold_at_boundary_permits_below(fixtures_dir, check_script):
    """At threshold=37, score 36 should exit 0."""
    repo = fixtures_dir / "mixed-service"
    result = run_check(check_script, repo, threshold=37)
    assert result.returncode == 0
    assert "score=36 band=moderate" in result.stdout
