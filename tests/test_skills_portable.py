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
