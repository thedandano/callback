"""Tests for the profile graph — structure, routing, and interrupt behaviour.

Isolation: XDG_DATA_HOME + wiki_module.BASE_DIR patched per test so nodes
write to tmp_path rather than ~/.local/share/callback.
"""

from datetime import UTC, datetime
from pathlib import Path

import callback.wiki as wiki_module
from callback.profile_graph import build_profile_graph, make_config
from callback.profilecompiler import save_compiled_profile
from callback.repository.resumes import save_resume
from callback.state import CompiledProfile, OrphanedSkill, ProfileState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tmp_graph(tmp_path):
    db_path = tmp_path / "profile-sessions.db"
    return build_profile_graph(db_path=db_path)


def _make_state(session_id: str, **kwargs) -> ProfileState:
    return ProfileState(session_id=session_id, **kwargs)


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


# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------


class TestProfileGraphStructure:
    def test_graph_compiles_with_five_nodes(self, tmp_path):
        graph = _tmp_graph(tmp_path)
        nodes = [n for n in graph.get_graph().nodes if not n.startswith("__")]
        expected = {"check_profile", "onboard", "compile_profile", "check_orphans", "create_story"}
        assert set(nodes) == expected


# ---------------------------------------------------------------------------
# check_profile routing
# ---------------------------------------------------------------------------


class TestCheckProfileRouter:
    def test_routes_to_onboard_when_no_profile_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-router-1")

        result = graph.invoke(_make_state("s-router-1"), config)

        assert result.get("intake") == {"status": "no_resume"}

    def test_routes_to_check_orphans_when_profile_and_resume_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-router-2")

        result = graph.invoke(_make_state("s-router-2"), config)

        assert {k: result.get(k) for k in ("profile_exists", "intake")} == {
            "profile_exists": True,
            "intake": None,
        }


# ---------------------------------------------------------------------------
# check_orphans routing
# ---------------------------------------------------------------------------


class TestCheckOrphansRouter:
    def test_routes_to_end_when_no_orphans_in_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=[])
        graph = _tmp_graph(tmp_path)
        config = make_config("s-orphan-1")

        result = graph.invoke(_make_state("s-orphan-1"), config)

        assert result.get("orphaned_skills") == []
        assert result.get("current_story_target") is None

    def test_routes_to_create_story_when_orphans_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])
        graph = _tmp_graph(tmp_path)
        config = make_config("s-orphan-2")
        intake = {
            "primary_skill": "Rust",
            "skills": ["Rust"],
            "story_type": "STAR",
            "job_title": "Systems Engineer",
            "situation": "S",
            "behavior": "B",
            "impact": "I",
        }

        result = graph.invoke(_make_state("s-orphan-2", intake=intake), config)

        assert result.get("current_story_target") == "Rust"


# ---------------------------------------------------------------------------
# First-run interrupt (onboard)
# ---------------------------------------------------------------------------


class TestInterruptAfterOnboard:
    def test_graph_pauses_after_onboard_on_first_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-interrupt-1")

        result = graph.invoke(_make_state("s-interrupt-1"), config)

        assert result.get("intake") is not None
        assert result.get("compiled_profile") is None

    def test_graph_resumes_and_reaches_end_after_onboard(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-interrupt-2")

        graph.invoke(_make_state("s-interrupt-2"), config)
        result = graph.invoke(None, config)

        assert result.get("compiled_profile") is not None


# ---------------------------------------------------------------------------
# create_story interrupt
# ---------------------------------------------------------------------------


class TestInterruptAfterCreateStory:
    def test_graph_pauses_after_create_story_when_orphan_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])
        graph = _tmp_graph(tmp_path)
        config = make_config("s-create-1")
        intake = {
            "primary_skill": "Rust",
            "skills": ["Rust"],
            "story_type": "STAR",
            "job_title": "Systems Engineer",
            "situation": "S",
            "behavior": "B",
            "impact": "I",
        }

        result = graph.invoke(_make_state("s-create-1", intake=intake), config)

        assert {k: result.get(k) for k in ("current_story_target", "compiled_profile")} == {
            "current_story_target": "Rust",
            "compiled_profile": None,
        }


# ---------------------------------------------------------------------------
# compile_profile interrupt
# ---------------------------------------------------------------------------


class TestInterruptAfterCompileProfile:
    def test_graph_pauses_after_compile_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-1")

        graph.invoke(_make_state("s-cp-1"), config)
        result = graph.invoke(None, config)

        assert {
            "has_compiled_profile": result.get("compiled_profile") is not None,
            "orphaned_skills": result.get("orphaned_skills"),
        } == {
            "has_compiled_profile": True,
            "orphaned_skills": None,
        }

    def test_graph_reaches_check_orphans_after_compile_profile_resume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-2")

        graph.invoke(_make_state("s-cp-2"), config)
        graph.invoke(None, config)
        result = graph.invoke(None, config)

        assert result.get("orphaned_skills") == []
