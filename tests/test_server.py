"""Tests for pi_apply.server MCP tool registration and routing."""

import json
import uuid
from unittest.mock import AsyncMock, patch

from pi_apply.jd_data import EXTRACTION_PROTOCOL

PARTIAL_JD_JSON = """
{
  "title": "Backend Engineer",
  "company": "ExampleCo",
  "required": ["Python"]
}
"""

EXPECTED_PARTIAL_KEYWORDS = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
    "preferred": None,
    "location": None,
    "seniority": "mid",
    "required_years": None,
    "team": None,
    "key_responsibilities": None,
    "pay_range_min": None,
    "pay_range_max": None,
}


def _tool_names(server) -> set[str]:
    components = server.mcp.local_provider._components
    return {component.name for key, component in components.items() if key.startswith("tool:")}


def test_apply_handoff_tools_registered():
    import pi_apply.server as server

    expected = {
        "load_jd",
        "submit_keywords",
        "submit_tailor",
        "get_wiki_pages",
        "onboard_user",
        "compile_profile",
        "create_story",
    }

    assert _tool_names(server) == expected


def test_legacy_apply_tool_absent():
    import pi_apply.server as server

    legacy = {
        "apply",
        "submit_tailor_t1",
        "submit_tailor_t2",
        "finalize",
        "preview_ats_extraction",
        "add_resume",
        "get_config",
        "update_config",
    }

    assert _tool_names(server).intersection(legacy) == set()


def test_load_jd_rejects_missing_jd_input():
    from pi_apply.server import load_jd

    result = json.loads(load_jd())
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "missing_input",
            "message": "neither jd_url nor jd_raw_text provided",
            "retriable": False,
        },
    }

    assert result == expected


def test_load_jd_returns_handoff_envelope(tmp_path):
    from pi_apply.server import load_jd

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    jd_text = "Python engineer needed"

    result = json.loads(load_jd(jd_raw_text=jd_text, resume_path=str(resume_file)))
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {
            "jd_text": jd_text,
            "extraction_protocol": EXTRACTION_PROTOCOL,
        },
    }

    assert result == expected


def test_load_jd_accepts_url_with_raw_text_fallback(tmp_path):
    from pi_apply.server import load_jd

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    jd_url = "https://example.test/job"
    jd_text = "# Python Engineer\n\nBuild Python services and own APIs."
    fetch_mock = AsyncMock(return_value=jd_text)

    with patch("pi_apply.apply_nodes.fetch_url_to_markdown", fetch_mock):
        result = json.loads(
            load_jd(
                jd_url=jd_url,
                jd_raw_text="Python engineer fallback text",
                resume_path=str(resume_file),
            )
        )
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {
            "jd_text": jd_text,
            "extraction_protocol": EXTRACTION_PROTOCOL,
        },
    }

    assert result == expected
    fetch_mock.assert_awaited_once_with(jd_url)


def test_submit_keywords_stores_jddata_and_stops_before_parsing(tmp_path):
    from pi_apply.server import load_jd, submit_keywords

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    loaded = json.loads(load_jd(jd_raw_text="Python engineer needed", resume_path=str(resume_file)))
    session_id = loaded["session_id"]

    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "parse_initial",
        "data": {
            "keywords": EXPECTED_PARTIAL_KEYWORDS,
            "score_gap": {
                "required_missing": result["data"]["score_gap"]["required_missing"],
                "preferred_missing": result["data"]["score_gap"]["preferred_missing"],
            },
        },
    }

    assert result == expected


def test_submit_keywords_rejects_invalid_jd_json():
    from pi_apply.server import submit_keywords

    session_id = "session-123"
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_jd",
            "message": "jd_json must encode an object",
            "retriable": True,
        },
        "session_id": session_id,
    }

    assert json.loads(submit_keywords(session_id=session_id, jd_json="[]")) == expected


def test_submit_keywords_rejects_empty_jd_json():
    from pi_apply.server import submit_keywords

    session_id = "session-123"
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "jd_empty",
            "message": (
                "jd_json contains no extractable keywords - provide at least title, "
                "company, or required skills"
            ),
            "retriable": True,
        },
        "session_id": session_id,
    }

    assert json.loads(submit_keywords(session_id=session_id, jd_json="{}")) == expected


def test_submit_keywords_rejects_unknown_session():
    from pi_apply.server import submit_keywords

    session_id = "missing-session"
    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_session",
            "message": "session_id was not found; call load_jd before submit_keywords",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_submit_keywords_rejects_blank_session_with_session_id():
    from pi_apply.server import submit_keywords

    session_id = ""
    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_session",
            "message": "session_id was not found; call load_jd before submit_keywords",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_submit_keywords_rejects_session_not_waiting_for_keywords(tmp_path):
    from pi_apply.server import load_jd, submit_keywords

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    loaded = json.loads(load_jd(jd_raw_text="Python engineer needed", resume_path=str(resume_file)))
    session_id = loaded["session_id"]
    submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON)

    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_state",
            "message": "session is not waiting for keyword submission",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_onboard_user_enters_onboard_node(monkeypatch):
    import pi_apply.profile_nodes as pnodes
    from pi_apply.server import onboard_user

    def fake_onboard(state):
        return {"intake": {"stub": "onboard"}}

    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by onboard_user tool")

    monkeypatch.setattr(pnodes, "onboard", fake_onboard)
    monkeypatch.setattr(pnodes, "check_profile", fake_check_profile)

    result = json.loads(onboard_user())
    session_id = result["session_id"]
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "compile_profile",
        "data": {"intake": {"stub": "onboard"}},
    }

    assert result == expected


def test_compile_profile_enters_compile_profile_node(monkeypatch):
    import pi_apply.profile_nodes as pnodes
    from pi_apply.server import compile_profile

    def fake_compile(state):
        return {"compiled_profile": {"stub": True}, "orphaned_skills": []}

    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by compile_profile tool")

    monkeypatch.setattr(pnodes, "compile_profile", fake_compile)
    monkeypatch.setattr(pnodes, "check_profile", fake_check_profile)

    result = json.loads(compile_profile())
    session_id = result["session_id"]
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "check_orphans",
        "data": {"compiled_profile": {"stub": True}, "orphaned_skills": []},
    }

    assert result == expected


def test_create_story_enters_create_story_node(monkeypatch):
    import pi_apply.profile_nodes as pnodes
    from pi_apply.server import create_story

    def fake_create(state):
        return {"orphaned_skills": [], "current_story_target": "test"}

    def fake_check_profile(state):
        raise AssertionError("check_profile should not be called by create_story tool")

    monkeypatch.setattr(pnodes, "create_story", fake_create)
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
    session_id = result["session_id"]
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "compile_profile",
        "data": {"orphaned_skills": [], "current_story_target": "test"},
    }

    assert result == expected
