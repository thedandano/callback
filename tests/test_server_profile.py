"""Tests for server.py — profile MCP tool wrappers."""

import json
from datetime import UTC, datetime
from pathlib import Path

import callback.profile_nodes as pnodes
import callback.server as server_module
import callback.wiki as wiki_module
from callback.profilecompiler import save_compiled_profile
from callback.repository.resumes import save_resume
from callback.server import compile_profile, create_story, onboard_user
from callback.state import CompiledProfile, OrphanedSkill


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


def _isolate_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")


def _resume_txt(tmp_path: Path) -> Path:
    f = tmp_path / "backend.txt"
    f.write_text("Jane Doe\njane@example.com\n\nSkills\nPython\n", encoding="utf-8")
    return f


def _save_profile_with_resumes(tmp_path: Path, orphans: list[str] | None = None) -> None:
    profile = CompiledProfile(
        schema_version="1",
        skills_index=["Python"],
        stories=[],
        orphaned_skills=[OrphanedSkill(skill=s) for s in (orphans or [])],
        compiled_at=datetime.now(UTC).isoformat(),
    )
    save_compiled_profile(profile, base_dir=tmp_path / "callback")
    resume = _resume_txt(tmp_path)
    save_resume("backend", str(resume))


_STORY_FIELDS = {
    "story_type": "STAR",
    "job_title": "Backend Engineer",
    "situation": "Legacy system.",
    "behavior": "Rewrote it.",
    "impact": "40% faster.",
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
        monkeypatch.setattr(server_module, "get_profile_graph", lambda: _fake_graph(state_values))

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
        monkeypatch.setattr(server_module, "get_profile_graph", lambda: _fake_graph(state_values))

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

        monkeypatch.setattr(server_module, "get_profile_graph", _CapturingGraph)

        onboard_user(resume_path=str(resume), accomplishments_path=str(acc))

        assert captured["state"].intake == {"onboard_text": "I built distributed systems."}


# ---------------------------------------------------------------------------
# compile_profile
# ---------------------------------------------------------------------------


class TestCompileProfile:
    def test_new_thread_compiles_and_reports_no_orphans(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        result = json.loads(compile_profile())

        assert {
            "status": result["status"],
            "next_action": result.get("next_action"),
            "orphaned_skills": result["data"]["orphaned_skills"],
            "has_compiled_profile": bool(result["data"]["compiled_profile"]),
            "keys": sorted(result["data"]),
        } == {
            "status": "ok",
            "next_action": None,
            "orphaned_skills": [],
            "has_compiled_profile": True,
            "keys": [
                "compiled_profile",
                "orphaned_skills",
                "skill_coverage_warnings",
                "skills_index",
            ],
        }

    def test_resumes_onboard_thread(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        resume = _resume_txt(tmp_path)
        onboarded = json.loads(onboard_user(resume_path=str(resume)))

        result = json.loads(compile_profile(session_id=onboarded["session_id"]))

        assert {"status": result["status"], "session_id": result["session_id"]} == {
            "status": "ok",
            "session_id": onboarded["session_id"],
        }

    def test_resumes_onboard_thread_with_story_tags_reaches_check_orphans(
        self, tmp_path, monkeypatch
    ):
        # Regression guard: update_state(config, {"compiled_profile": ...}) with no
        # as_node on a thread paused after onboard must not skip the compile_profile
        # node — onboard has an unconditional edge to it.
        _isolate_profile(tmp_path, monkeypatch)
        resume = _resume_txt(tmp_path)
        onboarded = json.loads(onboard_user(resume_path=str(resume)))

        result = json.loads(
            compile_profile(session_id=onboarded["session_id"], story_tags='["Rust"]')
        )

        assert {
            "status": result["status"],
            "session_id": result["session_id"],
            "next_action": result.get("next_action"),
            "has_compiled_profile": bool(result["data"]["compiled_profile"]),
            "orphaned_skills": sorted(result["data"]["orphaned_skills"]),
        } == {
            "status": "ok",
            "session_id": onboarded["session_id"],
            "next_action": "create_story",
            "has_compiled_profile": True,
            "orphaned_skills": ["Python", "Rust"],
        }

    def test_session_waiting_for_story_returns_invalid_state(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)
        compiled = json.loads(compile_profile(story_tags='["Rust"]'))  # paused before create_story

        result = json.loads(compile_profile(session_id=compiled["session_id"]))

        expected = {
            "status": "error",
            "error": {
                "stage": "compile_profile",
                "code": "invalid_state",
                "message": "session is not waiting for compile_profile",
                "retriable": False,
            },
            "session_id": compiled["session_id"],
        }
        assert result == expected

    def test_unknown_session_returns_session_not_found(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)

        result = json.loads(compile_profile(session_id="nope"))

        assert result == {
            "status": "error",
            "error": {
                "stage": "compile_profile",
                "code": "session_not_found",
                "message": "session_id not found",
                "retriable": False,
            },
            "session_id": "nope",
        }

    def test_without_profile_returns_profile_missing(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)

        result = json.loads(compile_profile())

        assert result["error"] == {
            "stage": "compile_profile",
            "code": "profile_missing",
            "message": "no profile; call onboard_user first",
            "retriable": False,
        }

    def test_invalid_story_tags_still_rejected(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)

        result = json.loads(compile_profile(story_tags="not json"))

        assert result["error"]["code"] == "invalid_story_tags"


# ---------------------------------------------------------------------------
# create_story
# ---------------------------------------------------------------------------


class TestCreateStory:
    def test_new_thread_saves_story_and_compiles(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

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

        assert {
            "status": result["status"],
            "next_action": result.get("next_action"),
            "story_saved": bool(result["data"]["story_id"]),
            "primary_skill": result["data"]["primary_skill"],
            "needs_compile": result["data"]["needs_compile"],
            "orphaned_skills": result["data"]["orphaned_skills"],
        } == {
            "status": "ok",
            "next_action": None,
            "story_saved": True,
            "primary_skill": "Python",
            "needs_compile": False,
            "orphaned_skills": [],
        }

    def test_resumes_thread_paused_before_create_story(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)
        compiled = json.loads(compile_profile(story_tags='["Rust"]'))
        compiled_next_action = compiled["next_action"]
        assert compiled_next_action == "create_story"
        compiled_session_id = compiled["session_id"]

        result = json.loads(
            create_story(
                session_id=compiled_session_id,
                primary_skill="Rust",
                skills=["Rust"],
                story_type="STAR",
                job_title="Backend Engineer",
                situation="Legacy system.",
                behavior="Rewrote it.",
                impact="40% faster.",
            )
        )

        actual = {
            "status": result["status"],
            "session_id": result["session_id"],
            "orphaned_skills": result["data"]["orphaned_skills"],
        }
        expected = {
            "status": "ok",
            "session_id": compiled_session_id,
            "orphaned_skills": [],
        }
        assert actual == expected

    def test_session_not_waiting_for_story_returns_invalid_state(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)
        compiled = json.loads(compile_profile())  # ends, next == ()

        result = json.loads(
            create_story(
                session_id=compiled["session_id"],
                primary_skill="Python",
                skills=["Python", "Docker"],
                story_type="STAR",
                job_title="Backend Engineer",
                situation="Legacy system.",
                behavior="Rewrote it.",
                impact="40% faster.",
            )
        )

        assert result["error"] == {
            "stage": "create_story",
            "code": "invalid_state",
            "message": "session is not waiting for create_story",
            "retriable": False,
        }

    def test_node_exception_returns_unexpected_error(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        def _raise(self, story):
            raise RuntimeError("disk")

        monkeypatch.setattr(pnodes.AccomplishmentsStore, "save_story", _raise)

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

        assert result["error"]["code"] == "unexpected_error"

    def test_blank_primary_skill_returns_invalid_story(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        result = json.loads(
            create_story(
                primary_skill="   ",
                skills=["Python", "Docker"],
                **_STORY_FIELDS,
            )
        )

        expected = {
            "status": "error",
            "error": {
                "stage": "create_story",
                "code": "invalid_story",
                "message": "primary_skill is required",
                "retriable": False,
            },
            "session_id": result["session_id"],
        }
        assert result == expected

    def test_run_without_saved_story_returns_story_not_saved(self, tmp_path, monkeypatch):
        _isolate_profile(tmp_path, monkeypatch)
        _save_profile_with_resumes(tmp_path)

        monkeypatch.setattr(server_module, "story_pending", lambda intake: False)

        result = json.loads(
            create_story(
                primary_skill="Python",
                skills=["Python", "Docker"],
                **_STORY_FIELDS,
            )
        )

        expected = {
            "status": "error",
            "error": {
                "stage": "create_story",
                "code": "story_not_saved",
                "message": "graph run completed without saving the story",
                "retriable": False,
            },
            "session_id": result["session_id"],
        }
        assert result == expected
