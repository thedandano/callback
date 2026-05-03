"""Tests for pi_apply.server MCP tool registration and routing (§4).

Tests the new four-tool MCP surface:
- apply: runs apply graph end-to-end, takes jd_url|jd_raw_text + resume_path
- onboard_user: enters profile graph at onboard node
- compile_profile: enters profile graph at compile_profile node
- create_story: enters profile graph at create_story node

Legacy tools (load_jd, submit_keywords, submit_tailor_t1, submit_tailor_t2,
finalize, etc.) must be absent.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_server_db(tmp_path, monkeypatch):
    """Redirect SQLite DBs to tmp dir before server import.

    server.py imports apply_graph and profile_graph at module level, which
    would otherwise open production DBs. Patch Path.home before re-importing.
    """
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    # Evict both graphs and server so module-level code re-evaluates
    for mod in ("pi_apply.server", "pi_apply.apply_graph", "pi_apply.profile_graph"):
        sys.modules.pop(mod, None)

    # Re-import server (triggers module-level graph builds with tmp paths)
    import pi_apply.server  # noqa: F401

    yield

    # Evict again for next test
    for mod in ("pi_apply.server", "pi_apply.apply_graph", "pi_apply.profile_graph"):
        sys.modules.pop(mod, None)


# ============================================================================
# 4.1 RED: Tool registration tests
# ============================================================================


def test_exactly_four_tools_registered():
    """Exactly four MCP tools must be registered: apply, onboard_user,
    compile_profile, create_story.
    """
    import pi_apply.server as server

    # FastMCP 3.x: synchronous access via local_provider._components
    components = server.mcp.local_provider._components
    tool_names = {
        v.name
        for k, v in components.items()
        if k.startswith("tool:")
    }

    expected = {
        "apply",
        "onboard_user",
        "compile_profile",
        "create_story",
    }
    assert tool_names == expected, f"Expected {expected}, got {tool_names}"


def test_legacy_tools_absent():
    """Legacy workflow tools must not be registered."""
    import pi_apply.server as server

    components = server.mcp.local_provider._components
    tool_names = {
        v.name
        for k, v in components.items()
        if k.startswith("tool:")
    }

    legacy = {
        "load_jd",
        "submit_keywords",
        "submit_tailor_t1",
        "submit_tailor_t2",
        "finalize",
        "preview_ats_extraction",
        "add_resume",
        "get_config",
        "update_config",
    }
    assert not tool_names.intersection(legacy), f"Legacy tools found: {tool_names & legacy}"


# ============================================================================
# 4.1 RED: apply tool tests
# ============================================================================


def test_apply_rejects_missing_jd_input():
    """Spec: apply without jd_url or jd_raw_text must reject."""
    from pi_apply.server import apply

    result = json.loads(apply())
    assert result["status"] == "error"
    assert result["error"]["code"] == "missing_input"


def test_apply_rejects_both_jd_inputs():
    """Spec: apply with both jd_url and jd_raw_text should reject."""
    from pi_apply.server import apply

    result = json.loads(apply(jd_url="https://example.com/job", jd_raw_text="Engineer role"))
    assert result["status"] == "error"


def test_apply_accepts_jd_raw_text_with_resume_path(tmp_path):
    """Spec: apply with jd_raw_text and resume_path runs to completion."""
    from pi_apply.server import apply

    # Create a dummy resume file
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")

    result = json.loads(apply(jd_raw_text="Python engineer needed", resume_path=str(resume_file)))
    assert result["status"] == "ok"
    assert "session_id" in result
    assert result.get("data", {}).get("pdf_path")
    assert result.get("data", {}).get("report") is not None


def test_apply_returns_envelope_structure():
    """Spec: apply returns proper JSON envelope with status and data."""
    from pi_apply.server import apply

    result = json.loads(apply(jd_raw_text="Test JD"))
    assert isinstance(result, dict)
    assert "status" in result
    assert "session_id" in result
    assert "data" in result or "error" in result


# ============================================================================
# 4.1 RED: Profile tool entry-point tests
# ============================================================================


def test_onboard_user_enters_onboard_node(monkeypatch):
    """Spec: onboard_user tool first node executed is onboard (not check_profile)."""
    from pi_apply.server import onboard_user
    import pi_apply.profile_nodes as pnodes

    # Monkeypatch onboard to record that it was called
    onboard_called = []

    def fake_onboard(state):
        onboard_called.append(True)
        return {"intake": {"stub": "onboard"}}

    monkeypatch.setattr(pnodes, "onboard", fake_onboard)

    # Also patch check_profile to raise if called (it shouldn't be)
    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by onboard_user tool")

    monkeypatch.setattr(pnodes, "check_profile", fake_check_profile)

    # Call onboard_user
    result = json.loads(onboard_user())
    assert onboard_called, "onboard node was not called"
    assert result["status"] == "ok"


def test_compile_profile_enters_compile_profile_node(monkeypatch):
    """Spec: compile_profile tool first node executed is compile_profile."""
    from pi_apply.server import compile_profile
    import pi_apply.profile_nodes as pnodes

    compile_called = []

    def fake_compile(state):
        compile_called.append(True)
        return {"compiled_profile": {"stub": True}, "orphaned_skills": []}

    monkeypatch.setattr(pnodes, "compile_profile", fake_compile)

    # Patch check_profile to ensure it's not called
    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by compile_profile tool")

    monkeypatch.setattr(pnodes, "check_profile", fake_check_profile)

    result = json.loads(compile_profile())
    assert compile_called, "compile_profile node was not called"
    assert result["status"] == "ok"


def test_create_story_enters_create_story_node(monkeypatch):
    """Spec: create_story tool first node executed is create_story."""
    from pi_apply.server import create_story
    import pi_apply.profile_nodes as pnodes

    create_called = []

    def fake_create(state):
        create_called.append(True)
        return {"orphaned_skills": [], "current_story_target": "test"}

    monkeypatch.setattr(pnodes, "create_story", fake_create)

    # Patch check_profile to ensure it's not called
    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by create_story tool")

    monkeypatch.setattr(pnodes, "check_profile", fake_check_profile)

    result = json.loads(
        create_story(
            skill="Python",
            story_type="project",
            job_title="Engineer",
            situation="test",
            behavior="test",
            impact="test",
        )
    )
    assert create_called, "create_story node was not called"
    assert result["status"] == "ok"


# ============================================================================
# Additional integration smoke tests
# ============================================================================


def test_apply_produces_archive_file(tmp_path, monkeypatch):
    """Spec: apply finalize writes archive JSON to apps dir."""
    from pi_apply.server import apply

    # Set apps dir to tmp
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Test resume")

    result = json.loads(apply(jd_raw_text="Test JD", resume_path=str(resume_file)))
    assert result["status"] == "ok"

    # Check that archive JSON was written
    session_id = result["session_id"]
    archive_path = tmp_path / f"{session_id}.json"
    assert archive_path.exists(), f"Archive not found at {archive_path}"

    with open(archive_path) as f:
        archive = json.load(f)
    assert archive["session_id"] == session_id
    assert "timestamp" in archive
    assert "jd_text" in archive
    assert "scores" in archive
