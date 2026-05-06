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
    "preferred": [],
    "location": None,
    "seniority": "mid",
    "required_years": 0.0,
    "team": None,
    "key_responsibilities": [],
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
            "orphaned_required": result["data"]["orphaned_required"],
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
            "code": "invalid_jd",
            "message": "required skills must not be empty",
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


class TestOrphanDetection:
    """Tests for _detect_orphaned_required orphan classification logic."""

    def test_orphan_detected_when_skill_in_sections_not_in_wiki(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Python", "Docker"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Docker\n- Built containers\n"

        result = _detect_orphaned_required(["Python", "Docker"], sections, wiki_index)

        assert result == ["Python"]

    def test_genuine_gap_not_flagged_as_orphan(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Docker"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Docker\n- Built containers\n"

        result = _detect_orphaned_required(["Kubernetes"], sections, wiki_index)

        assert result == []

    def test_skill_covered_in_wiki_not_flagged(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Python"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Python\n- Built services in python\n"

        result = _detect_orphaned_required(["Python"], sections, wiki_index)

        assert result == []


_NO_COVERAGE_JD_JSON = json.dumps(
    {
        "title": "Backend Engineer",
        "company": "ExampleCo",
        "required": ["Python"],
    }
)


class TestSubmitTailorNoCoverage:
    """Tests for submit_tailor with no_coverage=True."""

    def test_submit_tailor_no_coverage_sets_outcome(self, tmp_path, monkeypatch):
        """no_coverage=True skips edits, runs graph to finalize, and returns no_coverage outcome."""
        from pi_apply.server import load_jd, submit_keywords, submit_tailor

        monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path / "applications"))

        resume_file = tmp_path / "resume.txt"
        resume_file.write_text("Python developer")

        session_id = json.loads(
            load_jd(jd_raw_text="Python engineer needed", resume_path=str(resume_file))
        )["session_id"]
        json.loads(submit_keywords(session_id=session_id, jd_json=_NO_COVERAGE_JD_JSON))

        result = json.loads(submit_tailor(session_id=session_id, edits=[], no_coverage=True))

        actual = {
            "status": result["status"],
            "session_id": result["session_id"],
            "no_next_action": "next_action" not in result,
            "edits_applied": result["data"]["edits_applied"],
            "edits_rejected": result["data"]["edits_rejected"],
            "uncovered_skills": result["data"]["uncovered_skills"],
            "score_final_is_none_or_dict": result["data"]["score_final"] is None
            or isinstance(result["data"]["score_final"], dict),
            "report_no_coverage": (result["data"]["report"] or {}).get("no_coverage"),
            "outcome_no_coverage": result["data"]["outcome"]["no_coverage"],
        }
        assert actual == {
            "status": "ok",
            "session_id": session_id,
            "no_next_action": True,
            "edits_applied": [],
            "edits_rejected": [],
            "uncovered_skills": [],
            "score_final_is_none_or_dict": True,
            "report_no_coverage": True,
            "outcome_no_coverage": True,
        }
