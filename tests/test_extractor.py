"""Unit tests for pi_apply.extractor."""

import pytest

from pi_apply.extractor import (
    MAX_FILE_BYTES,
    _parse_contact_info,
    _parse_experience,
    _parse_projects,
    _parse_skills,
    _phase3_find_location,
    _process_url_line,
    extract,
    extract_sections,
)
from pi_apply.section_map import ContactInfo


class TestTxtExtraction:
    def test_extracts_plain_text(self, tmp_path):
        f = tmp_path / "resume.txt"
        f.write_text("Python developer\nFastAPI experience", encoding="utf-8")
        assert extract(f) == "Python developer\nFastAPI experience"

    def test_strips_surrounding_whitespace(self, tmp_path):
        f = tmp_path / "resume.txt"
        f.write_text("  hello  \n", encoding="utf-8")
        assert extract(f) == "hello"


class TestUnsupportedFormat:
    def test_raises_value_error_for_unknown_extension(self, tmp_path):
        f = tmp_path / "resume.rtf"
        f.write_bytes(b"content")
        with pytest.raises(ValueError, match="unsupported format"):
            extract(f)


class TestFileSizeGuard:
    def test_raises_value_error_when_over_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with pytest.raises(ValueError, match="too large"):
            extract(f)


class TestMissingFile:
    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "nonexistent.txt")


class TestContactInfoParsing:
    def test_email_extracted(self):
        lines = [
            "Jane Smith",
            "jane.smith@example.com",
            "San Francisco, CA",
        ]
        contact = _parse_contact_info(lines)
        assert contact.email == "jane.smith@example.com"

    def test_phone_extracted(self):
        lines = [
            "Jane Smith",
            "+1 (415) 555-1234",
            "San Francisco, CA",
        ]
        assert _parse_contact_info(lines) == ContactInfo(
            name="Jane Smith",
            phone="+1 (415) 555-1234",
            location="San Francisco, CA",
        )

    def test_name_extracted(self):
        lines = [
            "Jane Smith",
            "jane.smith@example.com",
            "+1 (415) 555-1234",
        ]
        contact = _parse_contact_info(lines)
        assert contact.name == "Jane Smith"

    def test_location_extracted_from_pipe_contact_line(self):
        lines = [
            "JANE DOE",
            "Anytown, USA | jane.doe@example.com | www.linkedin.com/in/janedoe",
        ]
        contact = _parse_contact_info(lines)
        actual = {
            "location": contact.location,
            "email": contact.email,
            "linkedin": contact.linkedin,
        }
        expected = {
            "location": "Anytown, USA",
            "email": "jane.doe@example.com",
            "linkedin": "www.linkedin.com/in/janedoe",
        }
        assert actual == expected

    def test_name_not_found_raises(self, tmp_path):
        # All lines are email/phone/URL — no candidate name line
        resume_text = (
            "jane.smith@example.com\n+1 (415) 555-1234\nhttps://linkedin.com/in/janesmith\n"
        )
        f = tmp_path / "resume.txt"
        f.write_text(resume_text, encoding="utf-8")
        with pytest.raises(ValueError, match="could not determine candidate name"):
            extract_sections(resume_text)


class TestLocationHeuristic:
    def test_rejects_long_line_with_one_comma(self):
        long_line = (
            "and pushed accuracy from 60% to 80%, and a RAG chatbot that a partner team "
            "took to production."
        )
        lines = ["Jane Doe", long_line, "jane@example.com"]
        location = _phase3_find_location(lines, email_lines={2}, url_lines=set(), name_idx=0)
        assert location is None

    def test_accepts_short_city_state(self):
        lines = ["Jane Doe", "Anytown, USA", "jane@example.com"]
        location = _phase3_find_location(lines, email_lines={2}, url_lines=set(), name_idx=0)
        assert location == "Anytown, USA"

    def test_accepts_city_with_period_abbreviation(self):
        lines = ["Jane Doe", "St. Louis, MO", "jane@example.com"]
        location = _phase3_find_location(lines, email_lines={2}, url_lines=set(), name_idx=0)
        assert location == "St. Louis, MO"

    def test_rejects_skill_category_line_with_comma(self):
        lines = ["Jane Doe", "Cloud: AWS, GCP", "jane@example.com"]
        location = _phase3_find_location(lines, email_lines={2}, url_lines=set(), name_idx=0)
        assert location is None


class TestLinkedinExtraction:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("linkedin.com/in/janedoe", "linkedin.com/in/janedoe"),
            ("www.linkedin.com/in/janedoe", "www.linkedin.com/in/janedoe"),
            ("linkedin.com/company/acme", "linkedin.com/company/acme"),
            ("www.linkedin.com/in/handle/", "www.linkedin.com/in/handle/"),
            (
                "Anytown, USA | dan@example.com | www.linkedin.com/in/janedoe",
                "www.linkedin.com/in/janedoe",
            ),
            (
                "City, ST | user@example.com | linkedin.com/company/acme",
                "linkedin.com/company/acme",
            ),
            (
                "City, ST | user@example.com | www.linkedin.com/in/handle/",
                "www.linkedin.com/in/handle/",
            ),
            (
                "City | user@example.com | https://linkedin.com/in/handle?trk=foo",
                "https://linkedin.com/in/handle?trk=foo",
            ),
        ],
    )
    def test_extracts_linkedin_url_segment(self, line, expected):
        linkedin, website = _process_url_line(line)
        assert linkedin == expected
        assert website is None


class TestSkillsParsing:
    def test_wrap_continuation_stays_in_previous_category(self):
        skills = _parse_skills(
            [
                "Backend & Data: Distributed systems, microservices, REST APIs, "
                "backend services, data pipelines, data",
                "contracts, schema validation, event-driven architecture, PySpark/Spark",
                "Cloud & Infrastructure: AWS, Docker",
                "Kubernetes",
            ]
        )
        actual = {
            "flat": skills.flat,
            "backend_tail": skills.categorized["Backend & Data"][-3:],
            "cloud": skills.categorized["Cloud & Infrastructure"],
        }
        expected = {
            "flat": [],
            "backend_tail": [
                "schema validation",
                "event-driven architecture",
                "PySpark/Spark",
            ],
            "cloud": ["AWS", "Docker", "Kubernetes"],
        }
        assert actual == expected


class TestExperienceParsing:
    def test_wrapped_bullet_lines_are_joined(self):
        experience = _parse_experience(
            [
                "Amazon, Anytown, USA",
                "Software Development Engineer II December 2024 – January 2026",
                "• The pricing pipeline handles 70% of prices. It runs on",
                "Python, Java, and TypeScript with AWS CDK.",
                "• Built a classifier. Accuracy went from 60% to",
                "80%, winning the org-wide GenAI hackathon.",
            ]
        )
        actual = {
            "count": len(experience),
            "company": experience[0].company,
            "role": experience[0].role,
            "bullets": experience[0].bullets,
        }
        expected = {
            "count": 1,
            "company": "Amazon, Anytown, USA",
            "role": "Software Development Engineer II",
            "bullets": [
                "The pricing pipeline handles 70% of prices. It runs on Python, Java, "
                "and TypeScript with AWS CDK.",
                "Built a classifier. Accuracy went from 60% to 80%, winning the "
                "org-wide GenAI hackathon.",
            ],
        }
        assert actual == expected


class TestProjectParsing:
    def test_wrapped_project_bullet_lines_are_joined(self):
        projects = _parse_projects(
            [
                "Howe-2 Care 4 Critters",
                "Full-Stack Web & Accessibility Engineer September 2020 – Present",
                "• Built the rescue’s first website from scratch: Node.js backend, "
                "Express routing, and API",
                "integration with error handling and caching.",
                "• Added SEO groundwork: JSON-LD structured data, per-page meta tags,",
                "and a dynamic sitemap.",
            ]
        )
        assert len(projects) == 1
        assert projects[0].bullets == [
            "Built the rescue’s first website from scratch: Node.js backend, "
            "Express routing, and API integration with error handling and caching.",
            "Added SEO groundwork: JSON-LD structured data, per-page meta tags, "
            "and a dynamic sitemap.",
        ]


class TestPreambleParsing:
    def test_title_and_summary_stay_in_summary_field(self):
        sections = extract_sections(
            "\n".join(
                [
                    "JANE DOE",
                    "Anytown, USA | jane.doe@example.com | www.linkedin.com/in/janedoe",
                    "SOFTWARE ENGINEER – BACKEND & AI",
                    "I build backend systems and AI tools.",
                    "SKILLS & ABILITIES",
                    "Languages: Python",
                    "EXPERIENCE",
                    "Amazon, Anytown, USA",
                    "Software Development Engineer II December 2024 – January 2026",
                    "• Built services.",
                ]
            )
        )
        assert (
            sections.summary
            == "SOFTWARE ENGINEER – BACKEND & AI\nI build backend systems and AI tools."
        )
