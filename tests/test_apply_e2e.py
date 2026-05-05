"""End-to-end apply graph test: drives the graph from JD text through finalize."""

import json
from pathlib import Path

import pytest

from pi_apply.state import TailoredResume

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_JD = (FIXTURES / "sample_jd.txt").read_text()
SAMPLE_RESUME = (FIXTURES / "sample_resume.txt").read_text()

KEYWORDS = {
    "title": "Software Engineer",
    "required": ["Python", "FastAPI", "PostgreSQL"],
    "preferred": ["Docker"],
    "required_years": 3.0,
    "seniority": "mid",
    "key_responsibilities": [],
}


@pytest.fixture
def setup_e2e_session(tmp_path, monkeypatch):
    """Setup e2e test session: return session_id at the tailor interrupt."""
    from pi_apply.server import load_jd, submit_keywords

    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path / "applications"))

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text(SAMPLE_RESUME)

    loaded = json.loads(load_jd(jd_raw_text=SAMPLE_JD, resume_path=str(resume_file)))
    assert loaded["status"] == "ok"
    session_id = loaded["session_id"]

    keywords_response = json.loads(
        submit_keywords(session_id=session_id, jd_json=json.dumps(KEYWORDS))
    )
    assert keywords_response["status"] == "ok"

    yield session_id


@pytest.fixture
def setup_e2e_session_with_graph(setup_e2e_session, tmp_path, monkeypatch):
    """Extended e2e fixture that also returns graph and config, advanced through finalize."""
    from pi_apply.apply_graph import build_apply_graph, make_config

    session_id = setup_e2e_session
    graph = build_apply_graph()
    config = make_config(session_id)

    # Advance all the way through the graph (tailor → render → parse_final → ... → finalize)
    graph.invoke(None, config)

    yield session_id, graph, config


class TestApplyGraphE2E:
    """End-to-end tests for the apply graph."""

    def test_tailor_produces_tailored_resume_object(self, setup_e2e_session):
        """After submit_keywords, graph is at tailor and state has TailoredResume."""
        from pi_apply.apply_graph import build_apply_graph, make_config

        session_id = setup_e2e_session
        graph = build_apply_graph()
        config = make_config(session_id)
        snapshot = graph.get_state(config)

        # Verify we're at tailor interrupt
        assert snapshot.next == ("tailor",)

        # Advance past tailor
        graph.invoke(None, config)
        snapshot_after_tailor = graph.get_state(config)
        state_values = snapshot_after_tailor.values

        # tailor should have produced a TailoredResume object
        tailored = state_values["tailored"]
        expected = TailoredResume(
            name="Jane Doe",
            email=tailored.email,
            phone=tailored.phone,
            location=tailored.location,
            summary=tailored.summary,
            skills_raw=tailored.skills_raw,
            experience_raw=tailored.experience_raw,
            education_raw=tailored.education_raw,
        )
        assert tailored == expected

    def test_graph_reaches_finalize_after_tailor(self, setup_e2e_session):
        """Graph completes all nodes from tailor through finalize."""
        from pi_apply.apply_graph import build_apply_graph, make_config

        session_id = setup_e2e_session
        graph = build_apply_graph()
        config = make_config(session_id)

        # Advance all the way through the graph
        graph.invoke(None, config)
        final_snapshot = graph.get_state(config)
        final_state = final_snapshot.values

        # Verify expected state keys
        expected_keys = {"finalized", "pdf_path", "score_initial", "score_final"}
        actual_keys = {k for k in expected_keys if final_state.get(k) is not None}
        assert actual_keys == expected_keys

    def test_m1_scenario_tailored_resume_has_name(self, setup_e2e_session):
        """M1 scenario: tailored resume object populated after tailor node."""
        from pi_apply.apply_graph import build_apply_graph, make_config

        session_id = setup_e2e_session
        graph = build_apply_graph()
        config = make_config(session_id)

        # Advance to tailor
        graph.invoke(None, config)

        # Get state at tailor
        snapshot = graph.get_state(config)
        state_values = snapshot.values
        tailored = state_values["tailored"]

        # Verify TailoredResume object with expected name
        expected = TailoredResume(
            name="Jane Doe",
            email=tailored.email,
            phone=tailored.phone,
            location=tailored.location,
            summary=tailored.summary,
            skills_raw=tailored.skills_raw,
            experience_raw=tailored.experience_raw,
            education_raw=tailored.education_raw,
        )
        assert tailored == expected

    def test_m2_scenario_real_pdf_round_trip(self, setup_e2e_session_with_graph):
        """M2: pipeline produces a real PDF and non-empty parsed_final."""
        session_id, graph, config = setup_e2e_session_with_graph
        state = graph.get_state(config).values
        from pathlib import Path

        pdf_path = state["pdf_path"]
        pdf_bytes = Path(pdf_path).read_bytes()
        parsed_final = state.get("parsed_final", "")

        actual = {
            "pdf_magic_bytes": pdf_bytes[:4],
            "has_parsed_final": bool(parsed_final),
            "parsed_final_nonempty": len(parsed_final) > 0,
            "finalized": state.get("finalized"),
        }
        expected = {
            "pdf_magic_bytes": b"%PDF",
            "has_parsed_final": True,
            "parsed_final_nonempty": True,
            "finalized": True,
        }
        assert actual == expected
