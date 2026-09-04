"""Tests for the profile graph — structure, routing, and interrupt behaviour.

Isolation: XDG_DATA_HOME + wiki_module.BASE_DIR patched per test so nodes
write to tmp_path rather than ~/.local/share/callback.
"""

from datetime import UTC, datetime
from pathlib import Path

import callback.wiki as wiki_module
from callback.profile_graph import _route_check_profile, build_profile_graph, make_config
from callback.profilecompiler import save_compiled_profile
from callback.repository.resumes import list_resumes, save_resume
from callback.state import CompiledProfile, OrphanedSkill, ProfileState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tmp_graph(tmp_path):
    db_path = tmp_path / "profile-sessions.db"
    return build_profile_graph(db_path=db_path)


def test_get_profile_graph_returns_the_same_instance():
    from callback.profile_graph import get_profile_graph

    assert get_profile_graph() is get_profile_graph()


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

    def test_routes_to_compile_profile_when_profile_and_resume_exist(self):
        state = ProfileState(session_id="s-router-2", profile_exists=True)
        assert _route_check_profile(state) == "compile_profile"

    def test_reonboard_with_existing_profile_replaces_resume(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        new_resume = tmp_path / "new.txt"
        new_resume.write_text("John Roe\njohn@example.com\n\nSkills\nRust\n", encoding="utf-8")
        graph = _tmp_graph(tmp_path)
        config = make_config("s-reonboard-1")

        result = graph.invoke(_make_state("s-reonboard-1", resume_path=str(new_resume)), config)

        actual = {
            "resume_label": result.get("resume_label"),
            "intake_status": (result.get("intake") or {}).get("status"),
            "registered": list_resumes(),
        }
        expected = {
            "resume_label": "primary",
            "intake_status": "onboarded",
            "registered": ["primary"],
        }
        assert actual == expected

    def test_reonboard_with_orphans_does_not_enter_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path, orphans=["Rust"])
        new_resume = _resume_txt(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-reonboard-2")

        result = graph.invoke(_make_state("s-reonboard-2", resume_path=str(new_resume)), config)

        assert {k: result.get(k) for k in ("current_story_target", "compiled_profile")} == {
            "current_story_target": None,
            "compiled_profile": None,
        }

    def test_routes_to_compile_profile_when_profile_exists_and_no_resume_path(self):
        state = ProfileState(session_id="s", profile_exists=True)
        assert _route_check_profile(state) == "compile_profile"

    def test_routes_to_create_story_when_story_pending(self):
        state = ProfileState(session_id="s", profile_exists=True, intake={"primary_skill": "Rust"})
        assert _route_check_profile(state) == "create_story"

    def test_saved_story_is_not_pending(self):
        state = ProfileState(
            session_id="s",
            profile_exists=True,
            intake={"primary_skill": "Rust", "story_id": "story-001"},
        )
        assert _route_check_profile(state) == "compile_profile"


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
        # compile_profile recomputes orphans from state.compiled_profile["host_tags"]
        # (not from the profile seeded on disk), so seed the orphan there. With the
        # graph now pausing before create_story (rather than after), the observable
        # signal is the pending interrupt, not a current_story_target set by a node
        # that hasn't run yet.
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-orphan-2")

        graph.invoke(_make_state("s-orphan-2", compiled_profile={"host_tags": ["Rust"]}), config)

        assert graph.get_state(config).next == ("create_story",)


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


class TestCompileFlowsIntoCheckOrphans:
    def test_compile_profile_runs_through_to_check_orphans(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-1")

        result = graph.invoke(_make_state("s-cp-1"), config)

        assert {
            "has_compiled_profile": result.get("compiled_profile") is not None,
            "orphaned_skills": result.get("orphaned_skills"),
            "next": graph.get_state(config).next,
        } == {"has_compiled_profile": True, "orphaned_skills": [], "next": ()}

    def test_orphans_pause_before_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-cp-2")

        graph.invoke(_make_state("s-cp-2", compiled_profile={"host_tags": ["Rust"]}), config)

        assert graph.get_state(config).next == ("create_story",)


# ---------------------------------------------------------------------------
# create_story interrupt
# ---------------------------------------------------------------------------


class TestCreateStoryInterrupt:
    def test_pending_story_on_new_thread_pauses_before_create_story(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
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

        graph.invoke(_make_state("s-create-1", intake=intake), config)

        assert graph.get_state(config).next == ("create_story",)

    def test_resuming_runs_create_story_then_compile_then_check_orphans(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path / "profile-wiki")
        _save_profile_with_resumes(tmp_path)
        graph = _tmp_graph(tmp_path)
        config = make_config("s-create-2")
        intake = {
            "primary_skill": "Rust",
            "skills": ["Rust"],
            "story_type": "STAR",
            "job_title": "Systems Engineer",
            "situation": "S",
            "behavior": "B",
            "impact": "I",
        }
        graph.invoke(_make_state("s-create-2", intake=intake), config)

        result = graph.invoke(None, config)

        assert {
            "story_saved": bool((result.get("intake") or {}).get("story_id")),
            "has_compiled_profile": result.get("compiled_profile") is not None,
            "orphaned_skills": result.get("orphaned_skills"),
            "next": graph.get_state(config).next,
        } == {
            "story_saved": True,
            "has_compiled_profile": True,
            "orphaned_skills": [],
            "next": (),
        }
