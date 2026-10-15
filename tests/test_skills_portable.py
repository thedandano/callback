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
        "preserves_source_offset": "recorded as-is with its offset" in schema,
        "rejects_time_zone_conversion": "Never convert it to another time zone" in schema,
        "passes_contact_date": "pass the email's own date as `date`" in schema,
    }
    expected = {
        "preserves_source_offset": True,
        "rejects_time_zone_conversion": True,
        "passes_contact_date": True,
    }

    assert actual == expected


def test_ledger_skills_keep_posting_identity_and_edd_contact_details():
    apply_skill = (REPO_ROOT / "skills/apply-to-job/SKILL.md").read_text()
    auto_skill = (REPO_ROOT / "skills/auto-job-apply/SKILL.md").read_text()
    scan_skill = (REPO_ROOT / "skills/scan-job-leads/SKILL.md").read_text()
    setup_skill = (REPO_ROOT / "skills/setup-callback/SKILL.md").read_text()
    export_skill = (REPO_ROOT / "skills/export-ledger/SKILL.md").read_text()
    schema = (REPO_ROOT / "skills/auto-job-apply/references/record-schema.md").read_text()

    actual = {
        "apply_non_submission_continues": (
            "When `ever_applied` is false, continue the workflow" in apply_skill
        ),
        "company_title_requires_confirmation": (
            "Reuse its `job_key` only when they confirm the same posting" in auto_skill
        ),
        "confirmation_has_distinct_status": (
            "Already applied - confirmation recorded" in apply_skill
        ),
        "status_only_reads_stored_scores": "Read `score_before` and `score_after`" in auto_skill,
        "unknown_salary_is_omitted": "Omit it when unknown" in schema,
        "contacts_have_a_method_prefix": (
            "Contact method: <Online|Email|Phone|Mail|Fax|In person>" in schema
        ),
        "scan_records_classified_outcomes": (
            "Record each classified outcome with `record_status`" in scan_skill
        ),
        "prior_submission_uses_ever_applied": "`ever_applied` is true" in apply_skill,
        "needs_source_key_match_is_retried": (
            "except when its latest status starts with `Needs source`" in scan_skill
        ),
        "setup_keeps_legacy_config_until_import": (
            "Keep its `record_csv`, `ledger_db`, and `edd_xlsx` keys when present" in setup_skill
        ),
        "setup_removes_legacy_config_after_success": (
            "After the import succeeds, remove `record_csv`, `ledger_db`, and `edd_xlsx`"
            in setup_skill
        ),
        "export_explains_contact_method": "that prefix is the contact-method field" in export_skill,
    }
    expected = {
        "apply_non_submission_continues": True,
        "company_title_requires_confirmation": True,
        "confirmation_has_distinct_status": True,
        "status_only_reads_stored_scores": True,
        "unknown_salary_is_omitted": True,
        "contacts_have_a_method_prefix": True,
        "scan_records_classified_outcomes": True,
        "prior_submission_uses_ever_applied": True,
        "needs_source_key_match_is_retried": True,
        "setup_keeps_legacy_config_until_import": True,
        "setup_removes_legacy_config_after_success": True,
        "export_explains_contact_method": True,
    }

    assert actual == expected
