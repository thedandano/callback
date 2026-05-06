"""Integration tests for the profile MCP tools → graph → stores pipeline.

These tests exercise the full stack (server tools → profile graph → real stores)
using isolated tmp_path state. Run via: pytest -m integration
"""

import json
from pathlib import Path

import pytest

import pi_apply.server as server_module
import pi_apply.wiki as wiki_module
from pi_apply.profile_graph import build_profile_graph
from pi_apply.server import compile_profile, create_story, onboard_user

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
            server_module, "build_profile_graph", lambda: build_profile_graph(db_path=db_path)
        )

        resume = _make_resume(tmp_path)

        # onboard: registers resume, returns intake after graph interrupt
        r1 = json.loads(onboard_user(resume_path=str(resume)))
        assert r1 == {
            "session_id": r1["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "intake": {"status": "onboarded", "resume_label": "jane_doe", "stories": []},
                "resume_label": "jane_doe",
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

        # compile: builds compiled_profile from (empty) stories
        r2 = json.loads(compile_profile())
        assert r2 == {
            "session_id": r2["session_id"],
            "status": "ok",
            "data": {
                "compiled_profile": {
                    "schema_version": "1",
                    "skills_index": [],
                    "stories": [],
                    "orphaned_skills": [],
                    "compiled_at": r2["data"]["compiled_profile"]["compiled_at"],
                },
                "skill_coverage_warnings": [],
                "skills_index": [],
            },
        }

        # create_story: persists a story and signals needs_compile
        r3 = json.loads(
            create_story(
                primary_skill="Python",
                skills=["Python", "Kubernetes"],
                story_type="STAR",
                job_title="Software Engineer",
                situation="Legacy monolith slowed deploys.",
                behavior="Migrated to Kubernetes microservices.",
                impact="Deploy time cut by 60%.",
            )
        )
        assert r3 == {
            "session_id": r3["session_id"],
            "status": "ok",
            "next_action": "compile_profile",
            "data": {
                "story_id": r3["data"]["story_id"],
                "primary_skill": "Python",
                "needs_compile": True,
            },
        }

        # compile again: picks up the new story — both skills now covered
        r4 = json.loads(compile_profile())
        assert r4 == {
            "session_id": r4["session_id"],
            "status": "ok",
            "data": {
                "compiled_profile": r4["data"]["compiled_profile"],
                "skill_coverage_warnings": [],
                "skills_index": ["Kubernetes", "Python"],
            },
        }

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
