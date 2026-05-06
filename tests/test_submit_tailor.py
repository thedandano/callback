"""Tests for the submit_tailor MCP tool."""

import json

from pi_apply.section_map import ContactInfo, ExperienceEntry, SectionMap, SkillsSection
from pi_apply.wiki import WikiStore


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


def test_submit_tailor_rejects_session_not_at_tailor(tmp_path):
    """Session that has only completed load_jd (at keywords_accept, not tailor) is rejected."""
    from pi_apply.server import load_jd, submit_tailor

    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python developer")
    loaded = json.loads(load_jd(jd_raw_text="Python engineer", resume_path=str(resume_file)))
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
    import os

    from pi_apply.server import load_jd, submit_keywords

    apps_dir = str(tmp_path / "applications")
    if monkeypatch is not None:
        monkeypatch.setenv("PI_APPLY_APPS_DIR", apps_dir)
    else:
        os.environ["PI_APPLY_APPS_DIR"] = apps_dir
    resume_file = tmp_path / f"{resume_label}.txt"
    resume_file.write_text("Placeholder resume text")
    loaded = json.loads(load_jd(jd_raw_text="Sample JD", resume_path=str(resume_file)))
    session_id = loaded["session_id"]
    submit_keywords(session_id=session_id, jd_json=jd_json_str)
    return session_id


def test_submit_tailor_applies_valid_edits_and_rescores(tmp_path, monkeypatch):
    """Happy path: valid edits are applied, score_final and report returned from final state."""
    from pi_apply.server import submit_tailor

    resume_label = "test_resume"
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
        "score_final_has_total": True,
        "report_has_delta": True,
        "outcome_no_coverage": False,
    }


def test_submit_tailor_rejects_out_of_bounds_target(tmp_path, monkeypatch):
    """Out-of-bounds experience target is rejected; in-bounds edits still applied."""
    from pi_apply.server import submit_tailor

    resume_label = "oob_resume"
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
