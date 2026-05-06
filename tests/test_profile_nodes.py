"""Tests for pi_apply.profile_nodes — onboard and compile_profile nodes."""

import pi_apply.wiki as wiki_module
from pi_apply.profile_nodes import compile_profile, onboard
from pi_apply.state import ProfileState

SAMPLE_RESUME = """\
John Doe
john@example.com

EXPERIENCE
Acme Corp | Software Engineer | 2020 - Present
- Built Python microservices
- Improved API performance by 40%

SKILLS
Python, Go, Docker

EDUCATION
State University
B.S. Computer Science
"""

EXPECTED_SECTIONS = {
    "summary": None,
    "skills": {
        "flat": ["Python", "Go", "Docker"],
        "categorized": {},
    },
    "experience": [
        {
            "company": "Acme Corp",
            "role": "Software Engineer",
            "start_date": "2020",
            "end_date": "Present",
            "context_line": None,
            "bullets": [
                "Built Python microservices",
                "Improved API performance by 40%",
            ],
        }
    ],
    "projects": [],
    "education": [
        {
            "institution": "State University",
            "degree": "B.S. Computer Science",
            "field": None,
            "graduation_date": None,
        }
    ],
    "contact": {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": None,
        "location": None,
        "linkedin": None,
        "website": None,
    },
    "certifications": [],
    "awards": [],
}


def test_onboard_with_resume_path_extracts_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path)

    resume_file = tmp_path / "my_resume.txt"
    resume_file.write_text(SAMPLE_RESUME, encoding="utf-8")

    state = ProfileState(session_id="test", resume_path=str(resume_file))
    result = onboard(state)

    expected = {
        "resume_label": "my_resume",
        "sections": EXPECTED_SECTIONS,
        "intake": {"status": "onboarded", "resume_label": "my_resume"},
    }

    assert result == expected

    sections_file = tmp_path / "my_resume" / "sections.json"
    assert sections_file.exists()


def test_onboard_without_resume_path_returns_no_resume():
    state = ProfileState(session_id="test")
    result = onboard(state)

    expected = {"intake": {"status": "no_resume"}}

    assert result == expected


def test_compile_profile_returns_compiled_profile_stub():
    state = ProfileState(session_id="test")
    result = compile_profile(state)

    expected = {"compiled_profile": {"stub": True}}

    assert result == expected
