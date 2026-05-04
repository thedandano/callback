"""Test the apply graph keyword handoff interrupts."""

import json
import logging

import pytest

from pi_apply.apply_graph import build_apply_graph, make_config
from pi_apply.state import ApplyState


VALID_JD_DATA = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
    "preferred": [],
    "location": None,
    "seniority": "mid",
    "required_years": None,
    "team": None,
    "key_responsibilities": None,
    "pay_range_min": None,
    "pay_range_max": None,
}


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


def _node_log_payloads(caplog, node: str) -> list[dict]:
    payloads = []
    for record in caplog.records:
        if record.name != "pi_apply.apply_nodes":
            continue
        payload = json.loads(record.message)
        if payload.get("node") == node:
            payloads.append(payload)
    return payloads


class TestApplyGraphStructure:
    """Test apply graph topology and compilation."""

    def test_graph_compiles(self, apply_graph):
        assert apply_graph is not None

    def test_graph_has_ten_nodes(self, apply_graph):
        expected_nodes = {
            "jd_fetch",
            "keywords_accept",
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
        actual_nodes.discard("__start__")
        assert actual_nodes == expected_nodes


class TestKeywordHandoffInterrupts:
    """Test the milestone 2 graph handoff behavior."""

    def test_load_jd_stops_after_jd_fetch(self, apply_graph, tmp_resume):
        session_id = "test-load-jd-interrupt"
        jd_text = "Test JD: Need Python, Go, Kubernetes"
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text=jd_text,
            resume_path=tmp_resume,
        )

        config = make_config(session_id)
        result = apply_graph.invoke(initial_state, config)
        snapshot = apply_graph.get_state(config)
        expected_result = {
            "session_id": session_id,
            "jd_raw_text": jd_text,
            "jd_text": jd_text,
            "resume_path": tmp_resume,
        }

        assert result == expected_result
        assert snapshot.next == ("keywords_accept",)

    def test_submit_keywords_stops_after_keywords_accept(
        self,
        apply_graph,
        tmp_resume,
        caplog,
    ):
        caplog.set_level(logging.INFO, logger="pi_apply.apply_nodes")
        session_id = "test-submit-keywords-interrupt"
        config = make_config(session_id)
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD: Need Python",
            resume_path=tmp_resume,
        )

        apply_graph.invoke(initial_state, config)
        apply_graph.update_state(config, {"keywords": VALID_JD_DATA})
        result = apply_graph.invoke(None, config)
        snapshot = apply_graph.get_state(config)
        expected_result = {
            "session_id": session_id,
            "jd_raw_text": "Test JD: Need Python",
            "jd_text": "Test JD: Need Python",
            "keywords": VALID_JD_DATA,
            "resume_path": tmp_resume,
        }

        assert result == expected_result
        assert snapshot.next == ("parse_initial",)
        assert len(_node_log_payloads(caplog, "keywords_accept")) == 1

    def test_keywords_accept_rejects_missing_host_keywords(self, apply_graph, tmp_resume):
        session_id = "test-missing-keywords"
        config = make_config(session_id)
        initial_state = ApplyState(
            session_id=session_id,
            jd_raw_text="Test JD: Need Python",
            resume_path=tmp_resume,
        )

        apply_graph.invoke(initial_state, config)

        with pytest.raises(ValueError, match="keywords missing"):
            apply_graph.invoke(None, config)
