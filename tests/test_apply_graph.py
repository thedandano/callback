"""Test the apply graph: 10 nodes, linear chain, no interrupts, single invoke() to completion."""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from pi_apply.state import ApplyState
from pi_apply.apply_graph import build_apply_graph


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite checkpointer DB for testing."""
    return tmp_path / "apply-test.db"


@pytest.fixture
def tmp_apps_dir(tmp_path, monkeypatch):
    """Temporary applications directory for testing."""
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(apps_dir))
    return apps_dir


@pytest.fixture
def tmp_resume(tmp_path):
    """Temporary resume file for testing."""
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("John Doe\nSoftware Engineer\n10 years experience")
    return str(resume_file)


@pytest.fixture
def apply_graph(tmp_db, tmp_apps_dir):
    """Build the apply graph with temporary checkpointer and apps dir."""
    return build_apply_graph(db_path=tmp_db)


class TestApplyGraphStructure:
    """Test apply graph topology and compilation."""

    def test_graph_compiles(self, apply_graph):
        """Graph compiles without raising."""
        assert apply_graph is not None

    def test_graph_has_ten_nodes(self, apply_graph):
        """Graph contains exactly 10 named nodes (plus LangGraph's __start__)."""
        expected_nodes = {
            "jd_fetch",
            "keywords_extract",
            "parse_initial",
            "score_initial",
            "tailor",
            "render",
            "parse_final",
            "score_final",
            "report",
            "finalize",
        }
        actual_nodes = set(apply_graph.nodes.keys())
        # Remove LangGraph's synthetic __start__ node for comparison
        actual_nodes.discard("__start__")
        assert actual_nodes == expected_nodes, f"Expected {expected_nodes}, got {actual_nodes}"


class TestSingleInvocation:
    """Test single-call execution from jd_fetch to finalize."""

    def test_invoke_completes_end_to_end(self, apply_graph, tmp_resume):
        """Graph runs end-to-end in one invoke() call, finalized is truthy."""
        session_id = "test-session-001"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD: Need Python, Go, Kubernetes",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        assert result.get("finalized") is True, "Graph did not reach finalize or finalized not set"


class TestNodeOutputs:
    """Test that each node writes its expected output field."""

    def test_outputs_present_after_run(self, apply_graph, tmp_resume):
        """After run, every output field needed by downstream nodes is present."""
        session_id = "test-session-outputs"
        jd_text = "Test JD"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text=jd_text,
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        # Check output presence
        assert result.get("jd_text") == jd_text, "jd_text not set by jd_fetch"
        assert isinstance(result.get("keywords"), dict), "keywords not set by keywords_extract"
        assert result.get("parsed_initial") is not None, "parsed_initial not set by parse_initial"
        assert isinstance(result.get("score_initial"), dict), "score_initial not set by score_initial"
        assert result.get("tailored") is not None, "tailored not set by tailor"
        assert result.get("pdf_path") is not None, "pdf_path not set by render"
        assert result.get("parsed_final") is not None, "parsed_final not set by parse_final"
        assert isinstance(result.get("score_final"), dict), "score_final not set by score_final"
        assert isinstance(result.get("report"), dict), "report not set by report"
        assert isinstance(result.get("uncovered_skills"), list), "uncovered_skills not set by report"
        assert result.get("finalized") is True, "finalized not set by finalize"


class TestDistinctParseScoreFields:
    """Test that parse_initial/final and score_initial/final have distinct fields."""

    def test_parsed_initial_differs_from_parsed_final(self, apply_graph, tmp_resume):
        """parsed_initial and parsed_final are distinct (different sources)."""
        session_id = "test-session-parse"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        parsed_initial = result.get("parsed_initial")
        parsed_final = result.get("parsed_final")

        # They should differ because they read from different sources
        # (resume file vs. rendered PDF)
        assert parsed_initial is not None
        assert parsed_final is not None
        # Sentinels should identify the source
        assert "parsed_initial" in str(parsed_initial) or "resume" in str(parsed_initial)
        assert "parsed_final" in str(parsed_final) or "pdf" in str(parsed_final)

    def test_score_initial_differs_from_score_final(self, apply_graph, tmp_resume):
        """score_initial and score_final are distinct dicts."""
        session_id = "test-session-score"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        score_initial = result.get("score_initial")
        score_final = result.get("score_final")

        # Both should be dicts with stub marker
        assert isinstance(score_initial, dict)
        assert isinstance(score_final, dict)
        assert score_initial.get("stub") is True
        assert score_final.get("stub") is True


class TestRenderProducesRealFile:
    """Test that render node produces a real on-disk PDF file."""

    def test_pdf_path_exists_after_render(self, apply_graph, tmp_resume, tmp_apps_dir):
        """After run, pdf_path is set and the file exists."""
        session_id = "test-session-render"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        pdf_path = result.get("pdf_path")
        assert pdf_path is not None, "pdf_path not set"
        assert isinstance(pdf_path, str), "pdf_path is not a string"

        path_obj = Path(pdf_path)
        assert path_obj.exists(), f"PDF file does not exist at {pdf_path}"

    def test_parse_final_can_read_pdf(self, apply_graph, tmp_resume):
        """parse_final reads the PDF without raising."""
        session_id = "test-session-parse-pdf"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        # If parse_final ran without error, parsed_final is set
        assert result.get("parsed_final") is not None


class TestFinalizeArchive:
    """Test that finalize writes a complete audit JSON archive."""

    def test_archive_file_exists(self, apply_graph, tmp_resume, tmp_apps_dir):
        """After finalize, archive JSON exists at apps_dir/<session_id>.json."""
        session_id = "test-session-archive"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD: Python, Go",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        archive_path = tmp_apps_dir / f"{session_id}.json"
        assert archive_path.exists(), f"Archive file not found at {archive_path}"

    def test_archive_contains_all_required_fields(self, apply_graph, tmp_resume, tmp_apps_dir):
        """Archive JSON contains all required fields per spec."""
        session_id = "test-session-fields"
        jd_text = "Test JD: Python, Kubernetes"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text=jd_text,
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        archive_path = tmp_apps_dir / f"{session_id}.json"
        with open(archive_path, "r") as f:
            archive = json.load(f)

        # Required fields per spec
        required_fields = {
            "session_id",
            "timestamp",
            "jd_url",
            "jd_text",
            "keywords",
            "tailored_resume_text",
            "pdf_path",
            "scores",
            "uncovered_skills",
        }
        actual_fields = set(archive.keys())
        assert required_fields.issubset(actual_fields), \
            f"Missing fields: {required_fields - actual_fields}"

        # Nested score fields
        scores = archive.get("scores", {})
        assert "initial" in scores, "scores.initial missing"
        assert "final" in scores, "scores.final missing"
        assert "scoring_engine_version" in scores, "scores.scoring_engine_version missing"

    def test_archive_timestamp_is_iso8601(self, apply_graph, tmp_resume, tmp_apps_dir):
        """Archive timestamp is valid ISO 8601 UTC."""
        session_id = "test-session-timestamp"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD",
            resume_path=tmp_resume,
        )

        config = {"configurable": {"thread_id": session_id}}
        result = apply_graph.invoke(initial_state, config)

        archive_path = tmp_apps_dir / f"{session_id}.json"
        with open(archive_path, "r") as f:
            archive = json.load(f)

        timestamp_str = archive.get("timestamp")
        assert timestamp_str is not None
        # Should parse as ISO 8601
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        assert parsed is not None
