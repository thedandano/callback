"""Integration tests for the profile MCP tools → graph → stores pipeline.

These tests exercise the full stack (server tools → profile graph → real stores)
using isolated tmp_path state. Run via: pytest -m integration
"""

import json
from pathlib import Path

import pytest

import callback.server as server_module
import callback.wiki as wiki_module
from callback.profile_graph import build_profile_graph
from callback.server import compile_profile, create_story, onboard_user

RESUME_TEXT = """\
Jane Doe
jane@example.com

Experience
Acme Corp | Software Engineer | 2020 - 2024
- Built Python microservices serving 10k daily users.
- Reduced deploy time by 60% via Kubernetes migration.

Skills
Python, Kubernetes, Docker
"""


def _make_resume(tmp_path: Path) -> Path:
    f = tmp_path / "jane_doe.txt"
    f.write_text(RESUME_TEXT, encoding="utf-8")
    return f


@pytest.mark.integration
class TestProfileToolsEndToEnd:
    def test_onboard_then_compile_then_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        db_path = tmp_path / "profile-sessions.db"
        monkeypatch.setattr(
            server_module, "get_profile_graph", lambda: build_profile_graph(db_path=db_path)
        )

        resume = _make_resume(tmp_path)

        # onboard: registers resume, returns intake after graph interrupt
        r1 = json.loads(onboard_user(resume_path=str(resume)))
        assert r1 == {
            "session_id": r1["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "intake": {"status": "onboarded", "resume_label": "primary", "stories": []},
                "resume_label": "primary",
                "sections": r1["data"]["sections"],
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

        # compile: resumes the onboard thread. With no stories yet, every resume
        # skill is an orphan, so the graph flows through compile_profile into
        # check_orphans and pauses before create_story.
        session_id = r1["session_id"]
        r2 = json.loads(compile_profile(session_id=session_id))
        _skills_sorted = ["Docker", "Kubernetes", "Python"]
        _orphans = r2["data"]["compiled_profile"]["orphaned_skills"]
        orphan_names = {o["skill"] for o in _orphans}
        assert orphan_names == set(_skills_sorted)
        assert r2 == {
            "session_id": session_id,
            "status": "ok",
            "next_action": "create_story",
            "data": {
                "compiled_profile": {
                    "schema_version": "1",
                    "skills_index": _skills_sorted,
                    "stories": [],
                    "orphaned_skills": _orphans,
                    "compiled_at": r2["data"]["compiled_profile"]["compiled_at"],
                },
                "skill_coverage_warnings": [],
                "skills_index": _skills_sorted,
                "orphaned_skills": [o["skill"] for o in _orphans],
            },
        }

        # create_story: resumes the paused thread, persists a story for Python, and
        # recompiles in the same call. Kubernetes is covered by the story's skills,
        # Docker remains an orphan, so the thread pauses before create_story again.
        r3 = json.loads(
            create_story(
                session_id=session_id,
                primary_skill="Python",
                skills=["Python", "Kubernetes"],
                story_type="STAR",
                job_title="Software Engineer",
                situation="Legacy monolith slowed deploys.",
                behavior="Migrated to Kubernetes microservices.",
                impact="Deploy time cut by 60%.",
            )
        )
        r3_actual = {
            "session_id": r3["session_id"],
            "status": r3["status"],
            "next_action": r3.get("next_action"),
            "story_id": r3["data"]["story_id"],
            "primary_skill": r3["data"]["primary_skill"],
            "needs_compile": r3["data"]["needs_compile"],
            "orphaned_skills": r3["data"]["orphaned_skills"],
        }
        r3_expected = {
            "session_id": session_id,
            "status": "ok",
            "next_action": "create_story",
            "story_id": r3["data"]["story_id"],
            "primary_skill": "Python",
            "needs_compile": False,
            "orphaned_skills": ["Docker"],
        }
        assert r3_actual == r3_expected

        # create_story again: covers Docker too — no orphans remain, thread ends.
        r4 = json.loads(
            create_story(
                session_id=session_id,
                primary_skill="Docker",
                skills=["Docker"],
                story_type="STAR",
                job_title="Software Engineer",
                situation="Manual deploys were slow.",
                behavior="Containerized the service with Docker.",
                impact="Deploy time cut further.",
            )
        )
        r4_actual = {
            "session_id": r4["session_id"],
            "status": r4["status"],
            "next_action": r4.get("next_action"),
            "orphaned_skills": r4["data"]["orphaned_skills"],
        }
        r4_expected = {
            "session_id": session_id,
            "status": "ok",
            "next_action": None,
            "orphaned_skills": [],
        }
        assert r4_actual == r4_expected

    def test_onboard_missing_resume_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

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
