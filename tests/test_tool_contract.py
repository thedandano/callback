"""Golden contracts for the public MCP tool surface and reply bytes."""

import json
import re
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

import callback.server as server
from callback.config import paths
from callback.graphs.apply.graph import get_apply_graph
from callback.models.section_map import ContactInfo, ExperienceEntry, SectionMap, SkillsSection
from callback.repositories.wiki import WikiStore
from callback.services import extractor as resume_extractor

FIXTURES_DIR = Path(__file__).parent / "fixtures"
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


@pytest.fixture
def fake_pdf_renderer(monkeypatch):
    """Reuse the render/extract patch setup from test_submit_tailor.py."""
    rendered_text: dict[str, str] = {}
    real_extract = resume_extractor.extract

    def fake_render_resume(tailored, output_path):
        text = "\n\n".join(
            str(tailored.get(key) or "")
            for key in ("summary", "skills_raw", "experience_raw", "projects_raw", "education_raw")
        )
        rendered_text[output_path] = text
        Path(output_path).write_bytes(b"fake pdf")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    def fake_extract(path):
        if str(path) in rendered_text:
            return rendered_text[str(path)]
        return real_extract(path)

    monkeypatch.setattr("callback.graphs.apply.nodes.render.render_resume", fake_render_resume)
    monkeypatch.setattr("callback.services.extractor.extract", fake_extract)


def _write_sections(resume_label: str) -> None:
    """Create the same minimal SectionMap shape used by submit-tailor tests."""
    sections = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Experienced software engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(
                company="Acme",
                role="SWE",
                bullets=["Led backend services handling 500K RPS"],
            )
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", sections.model_dump_json())


def _normalise(value: object, tmp_path: Path) -> object:
    if isinstance(value, dict):
        return {key: _normalise(item, tmp_path) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise(item, tmp_path) for item in value]
    if isinstance(value, str):
        tokenized = value.replace(str(tmp_path), "<tmp_path>")
        tokenized = UUID_PATTERN.sub("<session_id>", tokenized)
        return TIMESTAMP_PATTERN.sub("<timestamp>", tokenized)
    return value


def _read_golden(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _reply_cases(tmp_path: Path, monkeypatch) -> dict[str, dict]:
    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    replies: dict[str, dict] = {"load_jd_missing_input": server.load_jd()}

    with patch.object(server, "list_resumes", return_value=["golden_resume"]):
        loaded = server.load_jd(jd_raw_text="Python engineer needed")
    replies["load_jd_ok"] = loaded
    replies["submit_keywords_ok"] = server.submit_keywords(loaded["session_id"], jd_json)
    replies["submit_keywords_invalid_session"] = server.submit_keywords("missing-session", jd_json)
    replies["submit_responsibilities_ok"] = server.submit_responsibilities(
        loaded["session_id"], ["Build services"]
    )

    standard_label = "standard_resume"
    monkeypatch.setattr(paths, "wiki_dir", lambda: tmp_path / "wiki")
    _write_sections(standard_label)
    with patch.object(server, "list_resumes", return_value=[standard_label]):
        standard_loaded = server.load_jd(jd_raw_text="Python engineer needed")
    server.submit_keywords(standard_loaded["session_id"], jd_json)
    replies["submit_tailor_ok"] = server.submit_tailor(
        standard_loaded["session_id"],
        [{"section": "summary", "op": "replace", "value": "Python engineer."}],
        output_dir=str(tmp_path / "rendered"),
    )

    with patch.object(server, "list_resumes", return_value=["no_coverage_resume"]):
        no_coverage_loaded = server.load_jd(jd_raw_text="Python engineer needed")
    server.submit_keywords(no_coverage_loaded["session_id"], jd_json)
    replies["submit_tailor_no_coverage_ok"] = server.submit_tailor(
        no_coverage_loaded["session_id"], [], no_coverage=True
    )

    failed_label = "failed_resume"
    _write_sections(failed_label)
    with patch.object(server, "list_resumes", return_value=[failed_label]):
        failed_loaded = server.load_jd(jd_raw_text="Python engineer needed")
    server.submit_keywords(failed_loaded["session_id"], jd_json)
    monkeypatch.setattr(
        "callback.graphs.apply.nodes.render.render_resume",
        lambda tailored, output_path: {"success": False, "error": "chromium crashed"},
    )
    replies["submit_tailor_pipeline_error"] = server.submit_tailor(
        failed_loaded["session_id"],
        [{"section": "summary", "op": "replace", "value": "Python engineer."}],
    )

    resume_path = tmp_path / "jane.txt"
    resume_path.write_text("Jane Doe\njane@example.com\n\nSkills\nPython\n", encoding="utf-8")
    replies["onboard_user_ok"] = server.onboard_user(resume_path=str(resume_path))
    replies["compile_profile_ok"] = server.compile_profile(
        session_id=replies["onboard_user_ok"]["session_id"]
    )
    replies["create_story_ok"] = server.create_story(
        primary_skill="Python",
        skills=["Python"],
        story_type="STAR",
        job_title="Backend Engineer",
        situation="Legacy system.",
        behavior="Rewrote it.",
        impact="40% faster.",
    )
    replies["find_job_not_found"] = server.find_job(company="ExampleCo", title="SWE")
    replies["record_status_ok"] = server.record_status(
        status="Applied", company="ExampleCo", title="SWE", date="2026-11-21"
    )
    replies["export_ledger_ok"] = server.export_ledger(output_path=str(tmp_path / "ledger.csv"))
    return replies


def test_tool_surface_matches_golden():
    components = server.mcp.local_provider._components
    actual = {
        component.name: {
            "description": component.description,
            "inputSchema": cast(Any, component).parameters,
        }
        for key, component in components.items()
        if key.startswith("tool:")
    }

    assert len(actual) == 14
    assert actual == _read_golden("tool_surface.json")


def test_reply_bytes_match_golden(tmp_path, monkeypatch, fake_pdf_renderer):
    actual = _normalise(_reply_cases(tmp_path, monkeypatch), tmp_path)

    assert json.dumps(actual) == json.dumps(_read_golden("reply_goldens.json"))


def test_each_test_gets_its_own_session_db(tmp_path):
    first = get_apply_graph()
    first_path = paths.apply_db_path()

    get_apply_graph.cache_clear()
    second = get_apply_graph()
    second_path = paths.apply_db_path()

    assert tmp_path in first_path.parents
    assert first_path.name == "apply-sessions.db"
    assert second_path == first_path
    assert second is not first
