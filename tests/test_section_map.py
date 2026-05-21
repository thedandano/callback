"""Tests for SectionMap data model and apply_edit logic."""

from __future__ import annotations

import json

from pi_apply.section_map import (
    ContactInfo,
    EditResult,
    EducationEntry,
    ExperienceEntry,
    ProjectEntry,
    SectionMap,
    SkillsSection,
    apply_edit,
)


def make_full_section_map() -> SectionMap:
    """Build a SectionMap with all fields populated."""
    return SectionMap(
        summary="Experienced software engineer with 10 years of Python expertise.",
        skills=SkillsSection(
            flat=["Python", "Go"],
            categorized={"Languages": ["Python", "Go"], "Cloud": ["AWS", "GCP"]},
        ),
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                role="Senior Engineer",
                start_date="2020-01",
                end_date="2024-12",
                context_line="Led platform modernization initiative",
                bullets=[
                    "Reduced deployment time by 40%",
                    "Mentored 5 junior engineers",
                ],
            ),
            ExperienceEntry(
                company="Startup Inc",
                role="Software Engineer",
                start_date="2018-03",
                end_date="2020-01",
                bullets=["Built REST API serving 10k RPM"],
            ),
        ],
        projects=[
            ProjectEntry(
                name="pi-apply",
                description="LangGraph MCP server for resume tailoring",
                bullets=["Implemented holistic tailor pass", "Reduced ATS rejection rate"],
            )
        ],
        education=[
            EducationEntry(
                institution="State University",
                degree="B.S.",
                field="Computer Science",
                graduation_date="2018-05",
            )
        ],
        contact=ContactInfo(
            name="John Doe",
            email="john@example.com",
            phone="(555) 123-4567",
        ),
        certifications=["AWS Certified Solutions Architect"],
        awards=["Employee of the Year 2022"],
    )


# --- Task 1.5: JSON round-trip ---


def test_json_roundtrip() -> None:
    original = make_full_section_map()
    serialized = original.model_dump_json()
    deserialized = SectionMap.model_validate(json.loads(serialized))
    assert deserialized == original


# --- Task 1.6: apply_edit tests ---


def test_summary_replace() -> None:
    sm = SectionMap(summary="Old summary")
    result = apply_edit(sm, {"section": "summary", "op": "replace", "value": "New summary"})
    expected = EditResult(applied=True)
    assert result == expected
    assert sm.summary == "New summary"


def test_skills_add_flat() -> None:
    sm = SectionMap(skills=SkillsSection(flat=["Python"]))
    result = apply_edit(sm, {"section": "skills", "op": "add", "value": "Rust"})
    expected_result = EditResult(applied=True)
    expected_flat = ["Python", "Rust"]
    assert result == expected_result
    assert sm.skills.flat == expected_flat


def test_skills_replace_flat_by_index() -> None:
    sm = SectionMap(skills=SkillsSection(flat=["Python", "Go"]))
    result = apply_edit(
        sm,
        {"section": "skills", "op": "replace", "target": "skills-0", "value": "TypeScript"},
    )
    expected_result = EditResult(applied=True)
    expected_flat = ["TypeScript", "Go"]
    assert result == expected_result
    assert sm.skills.flat == expected_flat


def test_skills_add_categorized_new_category() -> None:
    sm = SectionMap()
    result = apply_edit(
        sm,
        {"section": "skills", "op": "add", "category": "Languages", "value": "Python"},
    )
    expected_result = EditResult(applied=True)
    expected_categorized = {"Languages": ["Python"]}
    assert result == expected_result
    assert sm.skills.categorized == expected_categorized


def test_skills_add_categorized_existing_category() -> None:
    sm = SectionMap(skills=SkillsSection(categorized={"Languages": ["Python"]}))
    result = apply_edit(
        sm,
        {"section": "skills", "op": "add", "category": "Languages", "value": "Go"},
    )
    expected_result = EditResult(applied=True)
    expected_categorized = {"Languages": ["Python", "Go"]}
    assert result == expected_result
    assert sm.skills.categorized == expected_categorized


def test_experience_bullet_replace_valid() -> None:
    sm = SectionMap(
        experience=[
            ExperienceEntry(
                company="Acme",
                role="Engineer",
                bullets=["Old bullet", "Keep this"],
            )
        ]
    )
    result = apply_edit(
        sm,
        {"section": "experience", "op": "replace", "target": "exp-0-b0", "value": "New bullet"},
    )
    expected_result = EditResult(applied=True)
    expected_bullets = ["New bullet", "Keep this"]
    assert result == expected_result
    assert sm.experience[0].bullets == expected_bullets


def test_experience_bullet_out_of_bounds_i() -> None:
    sm = SectionMap(
        experience=[ExperienceEntry(company="Acme", role="Engineer", bullets=["Bullet"])]
    )
    result = apply_edit(
        sm,
        {"section": "experience", "op": "replace", "target": "exp-5-b0", "value": "x"},
    )
    assert result == EditResult(
        applied=False, rejection_reason="experience index 5 out of bounds (have 1)"
    )


def test_experience_bullet_out_of_bounds_j() -> None:
    sm = SectionMap(
        experience=[ExperienceEntry(company="Acme", role="Engineer", bullets=["Only bullet"])]
    )
    result = apply_edit(
        sm,
        {"section": "experience", "op": "replace", "target": "exp-0-b9", "value": "x"},
    )
    assert result == EditResult(
        applied=False,
        rejection_reason="experience[0] bullet index 9 out of bounds (have 1)",
    )


def test_experience_context_line_set() -> None:
    sm = SectionMap(experience=[ExperienceEntry(company="Acme", role="Engineer", bullets=[])])
    result = apply_edit(
        sm,
        {
            "section": "experience",
            "op": "replace",
            "target": "exp-0-context",
            "value": "Led the payments platform",
        },
    )
    expected_result = EditResult(applied=True)
    assert result == expected_result
    assert sm.experience[0].context_line == "Led the payments platform"


def test_project_desc_replace() -> None:
    sm = SectionMap(projects=[ProjectEntry(name="MyProject", description="Old desc", bullets=[])])
    result = apply_edit(
        sm,
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0-desc",
            "value": "New description",
        },
    )
    expected_result = EditResult(applied=True)
    assert result == expected_result
    assert sm.projects[0].description == "New description"


def test_project_bullet_replace() -> None:
    sm = SectionMap(
        projects=[
            ProjectEntry(
                name="MyProject",
                bullets=["Old bullet", "Keep this"],
            )
        ]
    )
    result = apply_edit(
        sm,
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0-b0",
            "value": "Improved performance by 50%",
        },
    )
    expected_result = EditResult(applied=True)
    expected_bullets = ["Improved performance by 50%", "Keep this"]
    assert result == expected_result
    assert sm.projects[0].bullets == expected_bullets


def test_project_entry_replace() -> None:
    sm = SectionMap(
        projects=[
            ProjectEntry(
                name="Howe-2",
                description="Nonprofit website",
                bullets=["Built adoption site"],
            )
        ]
    )
    result = apply_edit(
        sm,
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0",
            "value": {
                "name": "Personal Voice LLM",
                "description": "Fine-tuning pipeline",
                "bullets": ["Built ChatML dataset for 17,027 records"],
            },
        },
    )
    expected_result = EditResult(applied=True)
    expected_project = ProjectEntry(
        name="Personal Voice LLM",
        description="Fine-tuning pipeline",
        bullets=["Built ChatML dataset for 17,027 records"],
    )
    assert result == expected_result
    assert sm.projects[0] == expected_project


def test_project_entry_replace_rejects_missing_name() -> None:
    sm = SectionMap(projects=[ProjectEntry(name="Howe-2")])
    result = apply_edit(
        sm,
        {
            "section": "projects",
            "op": "replace",
            "target": "proj-0",
            "value": {"description": "Missing name"},
        },
    )
    assert result == EditResult(
        applied=False,
        rejection_reason="project replacement value must include name",
    )
    assert sm.projects[0].name == "Howe-2"


def test_non_editable_section_rejected() -> None:
    sm = make_full_section_map()
    result = apply_edit(
        sm,
        {
            "section": "education",
            "op": "replace",
            "target": "edu-0",
            "value": "Fake University",
        },
    )
    assert result == EditResult(applied=False, rejection_reason="non-editable section: education")
