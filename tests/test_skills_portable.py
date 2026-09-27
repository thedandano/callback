from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_SUBSTRINGS = [
    "/Users/",
    "/home/",
    "~/.codex",
    "~/.claude",
    "thedandano",
    "America/Los_Angeles",
]


def test_skills_have_no_hardcoded_personal_paths():
    hits = []
    for md_file in sorted((REPO_ROOT / "skills").rglob("*.md")):
        relative_path = md_file.relative_to(REPO_ROOT)
        for line_number, line_text in enumerate(md_file.read_text().splitlines(), start=1):
            for needle in FORBIDDEN_SUBSTRINGS:
                if needle in line_text:
                    hits.append((str(relative_path), line_number, line_text))
    assert hits == []


def test_email_date_preserves_the_source_timestamp():
    schema = (REPO_ROOT / "skills/auto-job-apply/references/record-schema.md").read_text()

    actual = {
        "preserves_source_offset": "recorded as-is with the offset from its Date header" in schema,
        "rejects_time_zone_conversion": "Never convert it to another time zone" in schema,
    }
    expected = {"preserves_source_offset": True, "rejects_time_zone_conversion": True}

    assert actual == expected
