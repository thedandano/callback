"""End-to-end apply graph coverage for fetched job description propagation."""

import json
from unittest.mock import AsyncMock, patch

from pi_apply.apply_graph import build_apply_graph
from pi_apply.state import ApplyState


FIXTURE_MD = """# Senior Python Engineer

We need a senior engineer to build production Python services, improve
Kubernetes delivery workflows, and partner with product teams on measurable
customer-facing outcomes.

- Python
- Kubernetes
- API design
- Incident response
"""


def test_url_fetched_markdown_propagates_to_final_archive(tmp_path, monkeypatch):
    """Fetched markdown becomes state.jd_text and is archived by finalize."""
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(apps_dir))

    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(
        "Jane Candidate\nSenior Software Engineer\nBuilt Python services on Kubernetes.\n"
    )

    session_id = "e2e-jd-fetch-propagation"
    jd_url = "https://example.test/jobs/senior-python-engineer"
    graph = build_apply_graph(db_path=tmp_path / "apply-test.db")
    initial_state = ApplyState(
        session_id=session_id,
        jd_url=jd_url,
        resume_path=str(resume_path),
    )

    fetch_mock = AsyncMock(return_value=FIXTURE_MD)
    with patch("pi_apply.apply_nodes.fetch_url_to_markdown", fetch_mock):
        result = graph.invoke(
            initial_state,
            {"configurable": {"thread_id": session_id}},
        )

    assert result["jd_text"] == FIXTURE_MD

    archive_path = apps_dir / f"{session_id}.json"
    assert archive_path.exists()
    archive = json.loads(archive_path.read_text())
    assert archive["jd_text"] == FIXTURE_MD

    fetch_mock.assert_awaited_once_with(jd_url)
