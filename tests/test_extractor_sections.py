"""Tests for extract_sections — SectionMap output from resume plain text."""

from __future__ import annotations

import pytest

from pi_apply.extractor import extract_sections
from pi_apply.section_map import SectionMap

RESUME_TEXT = """
John Doe
john@example.com | (555) 123-4567

SUMMARY
Experienced software engineer with 8 years building distributed systems.
Focused on Python, Go, and cloud-native architectures.

SKILLS
Languages: Python, Go, TypeScript
Cloud: AWS, GCP
Databases: PostgreSQL, Redis
Docker

EXPERIENCE
Acme Corp | Senior Engineer | Jan 2021 – Present
- Reduced deployment time by 40% via CI/CD pipeline rewrite
- Mentored 3 junior engineers through onboarding program

Startup Inc | Software Engineer | Mar 2018 – Dec 2020
- Built REST API serving 10k RPM on AWS Lambda
- Migrated monolith to microservices, reducing p99 latency by 60%

PROJECTS
pi-apply
LangGraph MCP server for resume tailoring
- Implemented holistic tailor pass replacing two-tier T1/T2 system
- Achieved 95% ATS pass rate in testing

EDUCATION
State University
B.S. Computer Science, 2018
"""


@pytest.fixture
def sm() -> SectionMap:
    return extract_sections(RESUME_TEXT)


def test_summary_extracted(sm: SectionMap) -> None:
    assert sm.summary is not None
    assert "Experienced software engineer" in sm.summary


def test_skills_categorized(sm: SectionMap) -> None:
    assert sm.skills.categorized["Languages"] == ["Python", "Go", "TypeScript"]


def test_skills_flat(sm: SectionMap) -> None:
    assert "Docker" in sm.skills.flat


def test_experience_count(sm: SectionMap) -> None:
    assert len(sm.experience) == 2


def test_experience_first_company(sm: SectionMap) -> None:
    assert "Acme" in sm.experience[0].company


def test_experience_bullets(sm: SectionMap) -> None:
    assert any("deployment" in b for b in sm.experience[0].bullets)


def test_experience_second_entry(sm: SectionMap) -> None:
    assert "Startup" in sm.experience[1].company


def test_projects_count(sm: SectionMap) -> None:
    assert len(sm.projects) >= 1


def test_projects_name(sm: SectionMap) -> None:
    assert "pi-apply" in sm.projects[0].name


def test_projects_bullets(sm: SectionMap) -> None:
    assert any("holistic" in b for b in sm.projects[0].bullets)


def test_education_preserved(sm: SectionMap) -> None:
    assert len(sm.education) >= 1
