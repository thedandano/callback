import pytest

from pi_apply.profile_graph import build_profile_graph, make_config
from pi_apply.state import ProfileState


@pytest.fixture
def tmp_db(tmp_path):
    """Temp SQLite DB for profile graph checkpointing."""
    db_path = tmp_path / "profile-sessions.db"
    return db_path


@pytest.fixture
def graph(tmp_db):
    """Build the profile graph with a temp DB."""
    return build_profile_graph(db_path=tmp_db)


class TestProfileGraphStructure:
    """Graph compiles with correct nodes and edges."""

    def test_graph_compiles_with_five_nodes(self, graph):
        """Graph contains exactly the five named nodes."""
        nodes_dict = graph.get_graph().nodes
        node_names = [n for n in nodes_dict if not n.startswith("__")]
        assert "check_profile" in node_names
        assert "onboard" in node_names
        assert "compile_profile" in node_names
        assert "check_orphans" in node_names
        assert "create_story" in node_names
        assert len(node_names) == 5, f"Expected 5 nodes, got {len(node_names)}: {node_names}"


class TestFirstRunPath:
    """First-run: profile_exists=False, no orphans."""

    def test_first_run_executes_onboard_compile_check_orphans(self, graph, tmp_db):
        """First run: check_profile → onboard → compile_profile → check_orphans → END."""
        config = make_config("test-session-1")
        state = ProfileState(
            session_id="test-session-1",
            profile_exists=False,
            orphaned_skills=[],
        )

        # First invoke: check_profile → onboard (pauses at interrupt_after)
        result = graph.invoke(state, config)
        assert result.get("intake") is not None  # onboard ran

        # Resume: compile_profile → check_orphans (checks, sees empty list) → END
        result = graph.invoke(None, config)
        assert result.get("compiled_profile") is not None


class TestExistingProfilePath:
    """Existing profile: profile_exists=True, skips onboard and compile_profile."""

    def test_existing_profile_skips_onboard_and_compile(self, graph, tmp_db):
        """Existing profile: check_profile → check_orphans → END (no onboard/compile)."""
        config = make_config("test-session-2")
        state = ProfileState(
            session_id="test-session-2",
            profile_exists=True,
            orphaned_skills=[],
        )

        result = graph.invoke(state, config)

        # With profile_exists=True and no orphans, should reach END immediately
        # intake and compiled_profile should remain None (not written)
        assert result.get("intake") is None
        assert result.get("compiled_profile") is None


class TestCycleTerminates:
    """Cycle: create_story → compile_profile → check_orphans, terminates when orphans drain."""

    def test_cycle_drains_three_orphans(self, graph, tmp_db):
        """Three orphans: exactly 3 create_story calls, 3 compile_profile calls, then END."""
        config = make_config("test-session-3")
        state = ProfileState(
            session_id="test-session-3",
            profile_exists=True,
            orphaned_skills=["Kubernetes", "Terraform", "Docker"],
        )

        # First invoke: check_profile → check_orphans → create_story (pauses at interrupt_after)
        result = graph.invoke(state, config)
        assert result.get("current_story_target") is not None
        assert len(result.get("orphaned_skills", [])) == 2  # One orphan popped

        # Resume 1: compile_profile → check_orphans → create_story (pauses again)
        result = graph.invoke(None, config)
        assert len(result.get("orphaned_skills", [])) == 1

        # Resume 2: compile_profile → check_orphans → create_story (pauses again)
        result = graph.invoke(None, config)
        assert len(result.get("orphaned_skills", [])) == 0

        # Resume 3: compile_profile → check_orphans (checks, sees empty list) → END
        result = graph.invoke(None, config)

        # Verify by checking final state
        assert result.get("orphaned_skills") == []


class TestInterrupts:
    """Graph pauses at onboard and create_story."""

    def test_interrupt_after_onboard(self, graph, tmp_db):
        """Graph pauses after onboard on first run."""
        config = make_config("test-session-4")
        state = ProfileState(
            session_id="test-session-4",
            profile_exists=False,
            orphaned_skills=[],
        )

        # First invoke should pause at onboard
        result = graph.invoke(state, config)
        assert result.get("intake") is not None  # onboard wrote intake
        assert result.get("compiled_profile") is None  # compile_profile hasn't run yet

    def test_interrupt_after_create_story(self, graph, tmp_db):
        """Graph pauses after create_story."""
        config = make_config("test-session-5")
        state = ProfileState(
            session_id="test-session-5",
            profile_exists=True,
            orphaned_skills=["Skill1"],
        )

        # Invoke: check_profile → check_orphans → create_story (pauses)
        result = graph.invoke(state, config)
        assert result.get("current_story_target") is not None  # create_story ran and popped a skill
        assert result.get("orphaned_skills") == []

        # compiled_profile should not be set yet (compile_profile hasn't run)
        assert result.get("compiled_profile") is None


class TestCheckProfileRouter:
    """check_profile routes correctly based on profile_exists."""

    def test_check_profile_routes_to_onboard_when_no_profile(self, graph, tmp_db):
        """profile_exists=False → routes to onboard."""
        config = make_config("test-session-6")
        state = ProfileState(
            session_id="test-session-6",
            profile_exists=False,
            orphaned_skills=[],
        )

        result = graph.invoke(state, config)
        # onboard ran (writes intake)
        assert result.get("intake") is not None

    def test_check_profile_routes_to_check_orphans_when_profile_exists(self, graph, tmp_db):
        """profile_exists=True → routes to check_orphans."""
        config = make_config("test-session-7")
        state = ProfileState(
            session_id="test-session-7",
            profile_exists=True,
            orphaned_skills=[],
        )

        result = graph.invoke(state, config)
        # onboard did not run (intake still None)
        assert result.get("intake") is None


class TestCheckOrphansRouter:
    """check_orphans routes correctly based on orphaned_skills."""

    def test_check_orphans_routes_to_create_story_when_orphans_exist(self, graph, tmp_db):
        """orphaned_skills non-empty → routes to create_story."""
        config = make_config("test-session-8")
        state = ProfileState(
            session_id="test-session-8",
            profile_exists=True,
            orphaned_skills=["Go", "Python"],
        )

        result = graph.invoke(state, config)
        # create_story ran (popped one orphan)
        assert result.get("current_story_target") is not None
        assert len(result.get("orphaned_skills", [])) == 1

    def test_check_orphans_routes_to_end_when_no_orphans(self, graph, tmp_db):
        """orphaned_skills empty → routes to END."""
        config = make_config("test-session-9")
        state = ProfileState(
            session_id="test-session-9",
            profile_exists=True,
            orphaned_skills=[],
        )

        result = graph.invoke(state, config)
        # Should reach END without entering create_story
        # intake should remain None (onboard never ran)
        assert result.get("intake") is None
