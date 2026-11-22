"""The profile front door, exercised against a real graph on the per-test temp DB."""

from datetime import UTC, datetime

import pytest

from callback.graphs.profile import api
from callback.graphs.profile.api import ProfileSession
from callback.models.profile import CompiledProfile
from callback.models.state import ProfileState
from callback.repositories.compiled_profile import save_compiled_profile
from callback.repositories.resumes import save_resume

_STORY = {
    "primary_skill": "Python",
    "skills": ["Python"],
    "story_type": "STAR",
    "job_title": "Backend Engineer",
    "situation": "Legacy system.",
    "behavior": "Rewrote it.",
    "impact": "40% faster.",
}


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    resume = tmp_path / "backend.txt"
    resume.write_text("Jane Doe\njane@example.com\n\nSkills\nPython\n", encoding="utf-8")
    save_resume("backend", str(resume))

    profile = CompiledProfile(
        schema_version="1",
        skills_index=["Python"],
        stories=[],
        orphaned_skills=[],
        compiled_at=datetime.now(UTC).isoformat(),
    )
    save_compiled_profile(profile, base_dir=tmp_path / "callback")


def test_read_unknown_session_is_empty():
    assert api.read("nope", tool_name="compile_profile") == ProfileSession({}, None)


def test_run_thread_saves_a_pending_story_in_one_call(profile_dir):
    state = ProfileState(session_id="s1", resume_label="backend", intake=_STORY)

    session = api.run_thread("s1", state, tool_name="create_story")

    actual = (session.values["intake"]["story_id"], session.waiting_for)
    expected = ("story-001", None)
    assert actual == expected


def test_run_thread_with_orphans_waits_for_create_story(profile_dir):
    state = ProfileState(session_id="s2", resume_label="backend", host_tags=["Docker"])

    session = api.run_thread("s2", state, tool_name="compile_profile")

    actual = (session.waiting_for, session.values["orphaned_skills"], api.read("s2", tool_name="x"))
    expected = ("create_story", ["Docker"], session)
    assert actual == expected
