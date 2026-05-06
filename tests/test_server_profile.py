"""Tests for server.py — profile MCP tool wrappers."""

import json

import pi_apply.profile_nodes as pnodes
import pi_apply.server as server_module
from pi_apply.server import compile_profile, create_story, onboard_user


def _fake_graph(state_values: dict):
    class _Snap:
        def __init__(self) -> None:
            self.values = state_values

    class _Graph:
        def invoke(self, state, config):
            pass

        def get_state(self, config):
            return _Snap()

    return _Graph()


_STORY_FIELDS = dict(
    primary_skill="Python",
    skills=["Python", "Docker"],
    story_type="STAR",
    job_title="Backend Engineer",
    situation="Legacy system.",
    behavior="Rewrote it.",
    impact="40% faster.",
)

_COMPILE_DELTA = {
    "compiled_profile": {
        "schema_version": "1",
        "skills_index": ["Docker", "Python"],
        "stories": [],
        "orphaned_skills": [],
    },
    "intake": {
        "skill_coverage_warnings": [],
        "skills_index": ["Docker", "Python"],
    },
}

_CREATE_DELTA = {
    "current_story_target": "Python",
    "intake": {"story_id": "story-001", "needs_compile": True, **_STORY_FIELDS},
}


# ---------------------------------------------------------------------------
# onboard_user
# ---------------------------------------------------------------------------


class TestOnboardUser:
    def test_missing_resume_returns_error(self):
        result = json.loads(onboard_user())
        assert result == {
            "session_id": result["session_id"],
            "status": "error",
            "error": {
                "stage": "onboard_user",
                "code": "missing_resume_path",
                "message": "resume_path is required",
                "retriable": False,
            },
        }

    def test_happy_path_returns_ok_with_intake_and_sections(self, tmp_path, monkeypatch):
        resume = tmp_path / "jane.txt"
        resume.write_text("Jane Doe\n", encoding="utf-8")
        skills = tmp_path / "skills.txt"
        skills.write_text("Python\n", encoding="utf-8")

        state_values = {
            "intake": {"status": "onboarded", "resume_label": "jane"},
            "resume_label": "jane",
            "sections": {"contact": {"name": "Jane Doe"}},
        }
        monkeypatch.setattr(server_module, "build_profile_graph", lambda: _fake_graph(state_values))

        result = json.loads(onboard_user(resume_path=str(resume), skills_path=str(skills)))

        assert result == {
            "session_id": result["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "intake": {"status": "onboarded", "resume_label": "jane"},
                "resume_label": "jane",
                "sections": {"contact": {"name": "Jane Doe"}},
            },
        }

    def test_warns_when_no_skills_path_or_accomplishments(self, tmp_path, monkeypatch):
        resume = tmp_path / "jane.txt"
        resume.write_text("Jane Doe\n", encoding="utf-8")

        state_values = {"intake": {}, "resume_label": "jane", "sections": {}}
        monkeypatch.setattr(server_module, "build_profile_graph", lambda: _fake_graph(state_values))

        result = json.loads(onboard_user(resume_path=str(resume)))

        assert result == {
            "session_id": result["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "intake": {},
                "resume_label": "jane",
                "sections": {},
                "warnings": [
                    {
                        "warning": "no_skills_path",
                        "message": (
                            "No skills file provided. Skills will be extracted from resume only."
                        ),
                    }
                ],
            },
        }

    def test_accomplishments_text_injected_as_onboard_text(self, tmp_path, monkeypatch):
        resume = tmp_path / "jane.txt"
        resume.write_text("Jane Doe\n", encoding="utf-8")
        acc = tmp_path / "acc.txt"
        acc.write_text("I built distributed systems.", encoding="utf-8")

        captured: dict = {}

        class _CapturingGraph:
            def invoke(self, state, config):
                captured["state"] = state

            def get_state(self, config):
                class _Snap:
                    values = {"intake": {}, "resume_label": "jane", "sections": {}}

                return _Snap()

        monkeypatch.setattr(server_module, "build_profile_graph", _CapturingGraph)

        onboard_user(resume_path=str(resume), accomplishments_path=str(acc))

        assert captured["state"].intake == {"onboard_text": "I built distributed systems."}


# ---------------------------------------------------------------------------
# compile_profile
# ---------------------------------------------------------------------------


class TestCompileProfile:
    def test_happy_path_returns_compiled_data(self, monkeypatch):
        monkeypatch.setattr(pnodes, "compile_profile", lambda state: _COMPILE_DELTA)

        result = json.loads(compile_profile())

        assert result == {
            "session_id": result["session_id"],
            "status": "ok",
            "data": {
                "compiled_profile": {
                    "schema_version": "1",
                    "skills_index": ["Docker", "Python"],
                    "stories": [],
                    "orphaned_skills": [],
                },
                "skill_coverage_warnings": [],
                "skills_index": ["Docker", "Python"],
            },
        }

    def test_invalid_story_tags_returns_error(self, monkeypatch):
        monkeypatch.setattr(pnodes, "compile_profile", lambda state: _COMPILE_DELTA)

        result = json.loads(compile_profile(story_tags="not-valid-json"))

        assert result == {
            "session_id": result["session_id"],
            "status": "error",
            "error": {
                "stage": "compile_profile",
                "code": "invalid_story_tags",
                "message": "story_tags must be a JSON dict or list",
                "retriable": True,
            },
        }

    def test_dict_story_tags_extracted_as_keys(self, monkeypatch):
        captured: dict = {}

        def fake_compile(state):
            captured["state"] = state
            return _COMPILE_DELTA

        monkeypatch.setattr(pnodes, "compile_profile", fake_compile)

        compile_profile(story_tags='{"Python": true, "Go": true}')

        host_tags = captured["state"].compiled_profile["host_tags"]
        assert set(host_tags) == {"Python", "Go"}

    def test_list_story_tags_passed_as_host_tags(self, monkeypatch):
        captured: dict = {}

        def fake_compile(state):
            captured["state"] = state
            return _COMPILE_DELTA

        monkeypatch.setattr(pnodes, "compile_profile", fake_compile)

        compile_profile(story_tags='["Rust", "Go"]')

        assert captured["state"].compiled_profile["host_tags"] == ["Rust", "Go"]


# ---------------------------------------------------------------------------
# create_story
# ---------------------------------------------------------------------------


class TestCreateStory:
    def test_returns_story_id_and_needs_compile(self, monkeypatch):
        monkeypatch.setattr(pnodes, "create_story", lambda state: _CREATE_DELTA)

        result = json.loads(
            create_story(
                primary_skill="Python",
                skills=["Python", "Docker"],
                story_type="STAR",
                job_title="Backend Engineer",
                situation="Legacy system.",
                behavior="Rewrote it.",
                impact="40% faster.",
            )
        )

        assert result == {
            "session_id": result["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "story_id": "story-001",
                "primary_skill": "Python",
                "needs_compile": True,
            },
        }

    def test_intake_forwarded_to_node(self, monkeypatch):
        captured: dict = {}

        def fake_create(state):
            captured["state"] = state
            return _CREATE_DELTA

        monkeypatch.setattr(pnodes, "create_story", fake_create)

        create_story(
            primary_skill="Python",
            skills=["Python", "Docker"],
            story_type="STAR",
            job_title="Backend Engineer",
            situation="Legacy system.",
            behavior="Rewrote it.",
            impact="40% faster.",
        )

        assert captured["state"].intake == _STORY_FIELDS
