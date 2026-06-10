"""Tests for the submit_tailor MCP tool."""

import json
import os
from pathlib import Path

import pytest

from pi_apply.section_map import (
    ContactInfo,
    ExperienceEntry,
    ProjectEntry,
    SectionMap,
    SkillsSection,
)
from pi_apply.wiki import WikiStore


@pytest.fixture(autouse=True)
def fake_pdf_renderer(monkeypatch):
    rendered_text: dict[str, str] = {}

    def fake_render_resume(tailored, output_path):
        text = "\n\n".join(
            str(tailored.get(key) or "")
            for key in ("summary", "skills_raw", "experience_raw", "projects_raw", "education_raw")
        )
        rendered_text[output_path] = text
        Path(output_path).write_bytes(b"fake pdf")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    def fake_extract(path):
        return rendered_text.get(str(path), "")

    monkeypatch.setattr("pi_apply.apply_nodes.render_resume", fake_render_resume)
    monkeypatch.setattr("pi_apply.apply_nodes.resume_extractor.extract", fake_extract)


def test_submit_tailor_rejects_unknown_session():
    from pi_apply.server import submit_tailor

    result = json.loads(submit_tailor(session_id="no-such-session", edits=[]))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "session_not_found",
            "message": "session_id not found",
            "retriable": False,
        },
        "session_id": "no-such-session",
    }
    assert result == expected


def test_submit_tailor_rejects_session_not_at_tailor(tmp_path, monkeypatch):
    """Session that has only completed load_jd (at keywords_accept, not tailor) is rejected."""
    from unittest.mock import patch

    from pi_apply.server import load_jd, submit_tailor

    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path / "applications"))
    with patch("pi_apply.server.list_resumes", return_value=["resume"]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer"))
    session_id = loaded["session_id"]

    # Session is at keywords_accept (not tailor) — submit_tailor should reject
    result = json.loads(submit_tailor(session_id=session_id, edits=[]))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_tailor",
            "code": "invalid_state",
            "message": "session is not waiting for tailor edits",
            "retriable": False,
        },
        "session_id": session_id,
    }
    assert result == expected


def _make_section_map_and_write(
    resume_label: str, extra_bullets: list[str] | None = None
) -> SectionMap:
    """Create a minimal SectionMap, write sections.json to WikiStore, and return the model."""
    bullets = extra_bullets or ["Led backend services handling 500K RPS"]
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Experienced software engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(
                company="Acme",
                role="SWE",
                bullets=bullets + ["Improved deployment pipeline reducing release time by 40%"],
            ),
            ExperienceEntry(
                company="Beta Corp",
                role="Senior SWE",
                bullets=["Designed data platform serving 2M users", "Mentored 3 junior engineers"],
            ),
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())
    return section_map


def _run_to_tailor(
    tmp_path, jd_json_str: str, resume_label: str = "test_resume", monkeypatch=None
) -> str:
    """Run load_jd + submit_keywords and return the session_id at TAILOR_NODE."""
    from unittest.mock import patch

    from pi_apply.server import load_jd, submit_keywords

    apps_dir = str(tmp_path / "applications")
    if monkeypatch is not None:
        monkeypatch.setenv("PI_APPLY_APPS_DIR", apps_dir)
    else:
        os.environ["PI_APPLY_APPS_DIR"] = apps_dir
    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="Sample JD"))
    session_id = loaded["session_id"]
    submit_keywords(session_id=session_id, jd_json=jd_json_str)
    return session_id


def test_submit_tailor_applies_valid_edits_and_rescores(tmp_path, monkeypatch):
    """Happy path: valid edits are applied, score_final and report returned from final state."""
    from pi_apply.server import submit_tailor

    resume_label = "test_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python", "Kubernetes"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {"section": "summary", "op": "replace", "value": "Python + Kubernetes engineer."},
        {"section": "skills", "op": "add", "value": "Kubernetes"},
        {
            "section": "experience",
            "op": "replace",
            "target": "exp-0-b0",
            "value": "Deployed Kubernetes clusters serving 1M RPS",
        },
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    actual = {
        "status": result["status"],
        "has_session_id": bool(result.get("session_id")),
        "no_next_action": "next_action" not in result,
        "edits_applied": result["data"]["edits_applied"],
        "edits_rejected": result["data"]["edits_rejected"],
        "pdf_exists": Path(result["data"]["pdf_path"]).exists(),
        "archive_exists": Path(result["data"]["archive_path"]).exists(),
        "workflow_phase": result["workflow"]["phase"],
        "workflow_next_tool": result["workflow"]["next_tool"],
        "score_final_has_total": "total" in (result["data"]["score_final"] or {}),
        "report_has_delta": "delta" in (result["data"]["report"] or {}),
        "outcome_no_coverage": result["data"]["outcome"]["no_coverage"],
    }
    assert actual == {
        "status": "ok",
        "has_session_id": True,
        "no_next_action": True,
        "edits_applied": [0, 1, 2],
        "edits_rejected": [],
        "pdf_exists": True,
        "archive_exists": True,
        "workflow_phase": "complete",
        "workflow_next_tool": None,
        "score_final_has_total": True,
        "report_has_delta": True,
        "outcome_no_coverage": False,
    }
    assert result["workflow"]["required_input"] == {}


def test_submit_tailor_replaces_project_entry(tmp_path, monkeypatch):
    from pi_apply.server import submit_tailor

    resume_label = "project_replace_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Python engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(
                company="Acme",
                role="SWE",
                bullets=["Built Python services serving 500K users"],
            )
        ],
        projects=[
            ProjectEntry(
                name="Howe-2",
                description="Nonprofit website",
                bullets=["Built adoption site"],
            )
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python", "ChatML"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0",
            "value": {
                "name": "Personal Voice LLM",
                "description": "Gemma fine-tuning pipeline",
                "bullets": ["Built ChatML dataset with 17,027 records using Python"],
            },
        }
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    archive = json.loads(Path(result["data"]["archive_path"]).read_text())
    actual = {
        "status": result["status"],
        "edits_applied": result["data"]["edits_applied"],
        "edits_rejected": result["data"]["edits_rejected"],
        "rendered_has_new_project": "Personal Voice LLM" in archive["tailored_resume_text"],
        "rendered_lost_old_project": "Howe-2" not in archive["tailored_resume_text"],
        "chatml_matched": "ChatML" in result["data"]["score_final"]["req_matched"],
    }
    expected = {
        "status": "ok",
        "edits_applied": [0],
        "edits_rejected": [],
        "rendered_has_new_project": True,
        "rendered_lost_old_project": True,
        "chatml_matched": True,
    }
    assert actual == expected


def test_submit_tailor_removes_weak_bullet_and_adds_second_project(tmp_path, monkeypatch):
    from pi_apply.server import submit_tailor

    resume_label = "project_add_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Python engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(
                company="Acme",
                role="SWE",
                bullets=[
                    "Built Python services serving 500K users",
                    "Mentored teammates",
                ],
            )
        ],
        projects=[
            ProjectEntry(
                name="Howe-2",
                description="Nonprofit website",
                bullets=["Built AWS adoption site"],
            )
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps(
        {"title": "SWE", "company": "Co", "required": ["Python", "ChatML"], "preferred": ["AWS"]}
    )
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {"section": "experience", "op": "remove", "target": "exp-0-b1"},
        {
            "section": "projects",
            "op": "add",
            "target": "proj-end",
            "value": {
                "name": "Personal Voice LLM",
                "description": "Gemma fine-tuning pipeline",
                "bullets": ["Built ChatML dataset with 17,027 records using Python"],
            },
        },
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    archive = json.loads(Path(result["data"]["archive_path"]).read_text())
    rendered_text = archive["tailored_resume_text"]
    actual = {
        "status": result["status"],
        "edits_applied": result["data"]["edits_applied"],
        "edits_rejected": result["data"]["edits_rejected"],
        "rendered_keeps_old_project": "Howe-2" in rendered_text,
        "rendered_has_new_project": "Personal Voice LLM" in rendered_text,
        "removed_weak_bullet": "Mentored teammates" not in rendered_text,
        "chatml_matched": "ChatML" in result["data"]["score_final"]["req_matched"],
    }
    expected = {
        "status": "ok",
        "edits_applied": [0, 1],
        "edits_rejected": [],
        "rendered_keeps_old_project": True,
        "rendered_has_new_project": True,
        "removed_weak_bullet": True,
        "chatml_matched": True,
    }
    assert actual == expected


def test_submit_tailor_rejects_out_of_bounds_target(tmp_path, monkeypatch):
    """Out-of-bounds experience target is rejected; in-bounds edits still applied."""
    from pi_apply.server import submit_tailor

    resume_label = "oob_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(company="Co", role="SWE", bullets=["Built APIs"]),
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {"section": "summary", "op": "replace", "value": "Good summary"},
        {"section": "experience", "op": "replace", "target": "exp-5-b0", "value": "New bullet"},
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    # Verify the rejection record contains expected index and a reason mentioning out of bounds
    rejection = result["data"]["edits_rejected"][0]
    expected_rejection = {"index": 1, "reason": rejection["reason"]}
    assert rejection == expected_rejection
    assert "out of bounds" in rejection["reason"]

    actual = {
        "status": result["status"],
        "has_session_id": bool(result.get("session_id")),
        "no_next_action": "next_action" not in result,
        "edits_applied": result["data"]["edits_applied"],
        "edits_rejected": result["data"]["edits_rejected"],
        "score_final_has_total": "total" in (result["data"]["score_final"] or {}),
        "report_has_delta": "delta" in (result["data"]["report"] or {}),
        "outcome_no_coverage": result["data"]["outcome"]["no_coverage"],
    }
    assert actual == {
        "status": "ok",
        "has_session_id": True,
        "no_next_action": True,
        "edits_applied": [0],
        "edits_rejected": [expected_rejection],
        "score_final_has_total": True,
        "report_has_delta": True,
        "outcome_no_coverage": False,
    }


def test_submit_tailor_flags_uncovered_skill(tmp_path, monkeypatch):
    """Skill added to skills section but absent from all bullets appears in uncovered_skills."""
    from pi_apply.server import submit_tailor

    resume_label = "uncovered_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(company="Co", role="SWE", bullets=["Built REST APIs with Python"]),
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python", "Apache Kafka"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {"section": "skills", "op": "add", "value": "Apache Kafka"},
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    actual = {
        "status": result["status"],
        "apache_kafka_in_uncovered": "Apache Kafka" in result["data"]["uncovered_skills"],
        "edit_0_applied": 0 in result["data"]["edits_applied"],
    }
    assert actual == {
        "status": "ok",
        "apache_kafka_in_uncovered": True,
        "edit_0_applied": True,
    }


def test_submit_tailor_does_not_flag_covered_skill(tmp_path, monkeypatch):
    """Skill present in experience bullets is NOT flagged as uncovered."""
    from pi_apply.server import submit_tailor

    resume_label = "covered_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(company="Co", role="SWE", bullets=["Managed Python services"]),
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python", "Kubernetes"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {"section": "skills", "op": "add", "value": "Kubernetes"},
        {
            "section": "experience",
            "op": "replace",
            "target": "exp-0-b0",
            "value": "Managed Kubernetes clusters handling 1M RPS",
        },
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    actual = {
        "status": result["status"],
        "kubernetes_not_uncovered": "Kubernetes" not in result["data"]["uncovered_skills"],
    }
    assert actual == {
        "status": "ok",
        "kubernetes_not_uncovered": True,
    }


def test_submit_tailor_project_bullet_replacement_can_match_required_keyword(tmp_path, monkeypatch):
    from pi_apply.server import submit_tailor

    resume_label = "project_keyword_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    rendered = {}

    def fake_render_resume(tailored, output_path):
        rendered["text"] = "\n\n".join(
            str(tailored.get(key) or "")
            for key in ("summary", "skills_raw", "experience_raw", "projects_raw", "education_raw")
        )
        with open(output_path, "wb") as handle:
            handle.write(b"fake pdf")
        return {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    def fake_extract(_path):
        return rendered["text"]

    monkeypatch.setattr("pi_apply.apply_nodes.render_resume", fake_render_resume)
    monkeypatch.setattr("pi_apply.apply_nodes.resume_extractor.extract", fake_extract)

    section_map = SectionMap(
        contact=ContactInfo(name="Jane Dev"),
        summary="Python engineer",
        skills=SkillsSection(flat=["Python"]),
        experience=[
            ExperienceEntry(company="Co", role="SWE", bullets=["Built REST APIs with Python"]),
        ],
        projects=[
            ProjectEntry(
                name="Search Lab",
                description="Explored ranking systems",
                bullets=["Built prototype search APIs"],
            )
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python", "Vector Search"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0-b0",
            "value": "Built vector search ranking prototype for 250K documents",
        }
    ]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    actual = {
        "status": result["status"],
        "edits_applied": result["data"]["edits_applied"],
        "edits_rejected": result["data"]["edits_rejected"],
        "keyword_matched": "Vector Search" in result["data"]["score_final"]["req_matched"],
        "keyword_unmatched": "Vector Search" in result["data"]["score_final"]["req_unmatched"],
        "rendered_project_edit": "Built vector search ranking prototype" in rendered["text"],
    }
    expected = {
        "status": "ok",
        "edits_applied": [0],
        "edits_rejected": [],
        "keyword_matched": True,
        "keyword_unmatched": False,
        "rendered_project_edit": True,
    }
    assert actual == expected


def test_submit_tailor_redirects_pdf_to_output_dir(tmp_path, monkeypatch):
    """output_dir redirects the final PDF there; archive stays in apps_dir; no PDF in apps_dir."""
    from pi_apply.server import submit_tailor

    resume_label = "redirect_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    output_dir = tmp_path / "sandbox_out"
    apps_dir = tmp_path / "applications"
    edits = [{"section": "summary", "op": "replace", "value": "Python engineer."}]
    result = json.loads(
        submit_tailor(session_id=session_id, edits=edits, output_dir=str(output_dir))
    )

    pdf_path = Path(result["data"]["pdf_path"])
    actual = {
        "status": result["status"],
        "pdf_in_output_dir": pdf_path.parent == output_dir,
        "pdf_exists": pdf_path.exists(),
        "no_pdf_in_apps_dir": list(apps_dir.glob("*.pdf")) == [],
        "archive_in_apps_dir": Path(result["data"]["archive_path"]).parent == apps_dir,
        "archive_exists": Path(result["data"]["archive_path"]).exists(),
    }
    assert actual == {
        "status": "ok",
        "pdf_in_output_dir": True,
        "pdf_exists": True,
        "no_pdf_in_apps_dir": True,
        "archive_in_apps_dir": True,
        "archive_exists": True,
    }


def test_submit_tailor_no_coverage_accepts_output_dir_without_error(tmp_path, monkeypatch):
    """no_coverage skips render (no PDF to produce), so output_dir is accepted but unused."""
    from pi_apply.server import submit_tailor

    resume_label = "no_cov_redirect_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    output_dir = tmp_path / "no_cov_out"
    result = json.loads(
        submit_tailor(session_id=session_id, edits=[], no_coverage=True, output_dir=str(output_dir))
    )

    pdfs_anywhere = list((tmp_path / "applications").glob("*.pdf")) + list(output_dir.glob("*.pdf"))
    actual = {
        "status": result["status"],
        "no_coverage": result["data"]["outcome"]["no_coverage"],
        "pdf_path": result["data"]["pdf_path"],
        "no_pdf_written": pdfs_anywhere == [],
    }
    assert actual == {
        "status": "ok",
        "no_coverage": True,
        "pdf_path": None,
        "no_pdf_written": True,
    }


def test_submit_tailor_rejects_relative_output_dir(tmp_path, monkeypatch):
    """A relative output_dir is rejected up front (contract is an absolute path)."""
    from pi_apply.server import submit_tailor

    resume_label = "rel_dir_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    edits = [{"section": "summary", "op": "replace", "value": "Python engineer."}]
    result = json.loads(
        submit_tailor(session_id=session_id, edits=edits, output_dir="relative/out")
    )

    actual = {
        "status": result["status"],
        "stage": result["error"]["stage"],
        "code": result["error"]["code"],
        "retriable": result["error"]["retriable"],
        "session_id": result["session_id"],
    }
    assert actual == {
        "status": "error",
        "stage": "submit_tailor",
        "code": "invalid_output_dir",
        "retriable": True,
        "session_id": session_id,
    }


def test_submit_tailor_without_output_dir_writes_to_apps_dir(tmp_path, monkeypatch):
    """Default (no output_dir): PDF lands in apps_dir, unchanged from prior behavior."""
    from pi_apply.server import submit_tailor

    resume_label = "default_dir_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    apps_dir = tmp_path / "applications"
    edits = [{"section": "summary", "op": "replace", "value": "Python engineer."}]
    result = json.loads(submit_tailor(session_id=session_id, edits=edits))

    pdf_path = Path(result["data"]["pdf_path"])
    actual = {
        "status": result["status"],
        "pdf_in_apps_dir": pdf_path.parent == apps_dir,
        "pdf_exists": pdf_path.exists(),
    }
    assert actual == {"status": "ok", "pdf_in_apps_dir": True, "pdf_exists": True}


def test_submit_tailor_rejects_unwritable_output_dir(tmp_path, monkeypatch):
    """An output_dir that cannot be created returns invalid_output_dir, not a silent fallback."""
    from pi_apply.server import submit_tailor

    resume_label = "bad_dir_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    _make_section_map_and_write(resume_label)

    jd_json = json.dumps({"title": "SWE", "company": "Co", "required": ["Python"]})
    session_id = _run_to_tailor(tmp_path, jd_json, resume_label, monkeypatch)

    # mkdir fails because a regular file already occupies the parent path.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    bad_output_dir = blocker / "nested"

    edits = [{"section": "summary", "op": "replace", "value": "Python engineer."}]
    result = json.loads(
        submit_tailor(session_id=session_id, edits=edits, output_dir=str(bad_output_dir))
    )

    actual = {
        "status": result["status"],
        "stage": result["error"]["stage"],
        "code": result["error"]["code"],
        "retriable": result["error"]["retriable"],
        "session_id": result["session_id"],
        "no_pdf_written": list((tmp_path / "applications").glob("*.pdf")) == [],
    }
    assert actual == {
        "status": "error",
        "stage": "submit_tailor",
        "code": "invalid_output_dir",
        "retriable": True,
        "session_id": session_id,
        "no_pdf_written": True,
    }
