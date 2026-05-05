"""Tests for the submit_tailor MCP tool."""

import json


def test_submit_tailor_rejects_unknown_session():
    from pi_apply.server import submit_tailor

    result = json.loads(submit_tailor(session_id="no-such-session", edits=[]))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "session_not_found",
            "message": "session_id not found",
            "retriable": False,
        },
        "session_id": "no-such-session",
    }
    assert result == expected


def test_submit_tailor_rejects_session_not_at_tailor(tmp_path):
    from pi_apply.server import load_jd, submit_keywords, submit_tailor

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    loaded = json.loads(load_jd(jd_raw_text="Python engineer", resume_path=str(resume_file)))
    session_id = loaded["session_id"]
    submit_keywords(
        session_id=session_id,
        jd_json='{"title": "Eng", "company": "Co", "required": ["Python"]}',
    )

    result = json.loads(submit_tailor(session_id=session_id, edits=[]))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "invalid_state",
            "message": "session is not waiting for tailor edits",
            "retriable": False,
        },
        "session_id": session_id,
    }
    assert result == expected
