import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from callback import ledger
from callback.ledger_import import (
    ImportReport,
    _iso_date,
    import_archives,
    import_contact_ledger,
    import_record_csv,
)

_CSV = (
    "Company,Title,Recorded Date,Email Date,URL,Salary range,Status,Notes,"
    "Resume score after tailoring,Resume score before tailoring,Link to resume used,"
    "Link to cover letter used\n"
    'Acme,"Engineer, Platform",2026-10-01,,https://jobs.acme.com/1/,"$100,000-$120,000",'
    'Applied,"Notes, with comma",,,,\n'
    "Beta,Dev,2026-10-02,,https://beta.com/2,,,,,,,\n"
    "Gamma,Dev,,,https://gamma.com/3,,Applied,,,,,\n"
)


def _archive(tmp_path, session_id, url, pdf_path=None):
    d = tmp_path / "apps"
    d.mkdir(exist_ok=True)
    data = {
        "session_id": session_id,
        "timestamp": "2026-10-01T10:00:00+00:00",
        "jd_url": url,
        "keywords": {"company": "Acme", "title": "Engineer, Platform"},
        "scores": {"initial": {"total": 50.0}, "final": {"total": 70.0}},
    }
    if pdf_path:
        data["pdf_path"] = pdf_path
    (d / f"{session_id}.json").write_text(json.dumps(data))
    return d


def _counts(conn):
    return conn.execute(
        "SELECT (SELECT COUNT(*) FROM jobs), (SELECT COUNT(*) FROM runs), "
        "(SELECT COUNT(*) FROM status_events)"
    ).fetchone()


def _pdf_path(conn, session_id):
    row = conn.execute("SELECT pdf_path FROM runs WHERE session_id = ?", (session_id,))
    return row.fetchone()[0]


def test_archives_and_csv_merge_by_url_and_rerun_adds_nothing(tmp_path):
    apps = _archive(tmp_path, "s1", "https://jobs.acme.com/1")
    (apps / "notes.json").write_text('{"not": "a run"}')
    csv_path = tmp_path / "record.csv"
    csv_path.write_text(_CSV, encoding="utf-8")
    before = (csv_path.read_bytes(), (apps / "s1.json").read_bytes())

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        first = (import_archives(conn, apps), import_record_csv(conn, csv_path), _counts(conn))
        second = (import_archives(conn, apps), import_record_csv(conn, csv_path), _counts(conn))
        acme = conn.execute(
            "SELECT company, title, salary_range FROM jobs "
            "WHERE job_key = 'https://jobs.acme.com/1'"
        ).fetchone()

    assert (first, second, acme, (csv_path.read_bytes(), (apps / "s1.json").read_bytes())) == (
        (
            ImportReport(imported=1, skipped=["notes.json"], jobs=1),
            ImportReport(imported=1, skipped=["line 4"], jobs=2, events=1),
            (3, 1, 1),
        ),
        (
            ImportReport(imported=0, skipped=["notes.json", "s1.json"]),
            ImportReport(imported=0, skipped=["line 4"]),
            (3, 1, 1),
        ),
        ("Acme", "Engineer, Platform", "$100,000-$120,000"),
        before,
    )


def test_reimport_never_overwrites_a_newer_run(tmp_path):
    apps = _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/old.pdf")
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(
            conn,
            ledger.RunRecord(
                session_id="s1",
                timestamp="2026-10-05T00:00:00+00:00",
                jd_url="https://a.com/1",
                pdf_path="/new.pdf",
            ),
        )
        report = import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    assert (report, stored) == (ImportReport(imported=0, skipped=["s1.json"]), "/new.pdf")


def test_missing_pdf_is_relinked_to_a_file_in_the_archive_folder(tmp_path, caplog):
    apps = _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/home/other/x/resume.pdf")
    (apps / "sub").mkdir()
    found = apps / "sub" / "resume.pdf"
    found.write_bytes(b"%PDF")

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    events = [json.loads(r.message)["event"] for r in caplog.records]
    assert (stored, events) == (str(found), ["ledger_import_pdf_relinked"])


def test_pdf_that_cannot_be_found_keeps_its_path_and_warns(tmp_path, caplog):
    apps = _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/home/other/x/gone.pdf")

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    events = [json.loads(r.message)["event"] for r in caplog.records]
    assert (stored, events) == ("/home/other/x/gone.pdf", ["ledger_import_pdf_missing"])


def test_undecodable_archive_is_skipped(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "bad.json").write_bytes(b"\xff\xfe\x00bad")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_archives(conn, apps)

    assert report == ImportReport(imported=0, skipped=["bad.json"])


def test_missing_archive_folder_raises_a_clear_error(tmp_path):
    with (
        closing(ledger.connect(tmp_path / "l.db")) as conn,
        pytest.raises(ValueError, match="cannot read archive folder"),
    ):
        import_archives(conn, tmp_path / "nope")


def test_csv_with_a_byte_order_mark_keeps_the_company_column(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text(_CSV, encoding="utf-8-sig")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_record_csv(conn, csv_path)
        companies = conn.execute("SELECT company FROM jobs ORDER BY company").fetchall()

    assert [tuple(c) for c in companies] == [("Acme",), ("Beta",), ("Gamma",)]


def test_unreadable_csv_raises_a_clear_error(tmp_path):
    missing = tmp_path / "nope.csv"
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"\xff\xfe\x00\x00")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for path in (missing, bad):
            with pytest.raises(ValueError, match="cannot read record CSV"):
                import_record_csv(conn, path)


def _contacts_db(path):
    rows = [
        (1, "2026-09-01", "Acme", "Engineer", "Online", "Applied"),
        (2, "2026-09-02", "Beta", "Dev", "Email", "Emailed"),
        (3, "", "Gamma", "Dev", "Email", "Applied"),
    ]
    details = [
        ("https://acme.com/job/1", "", "via site"),
        ("a@b.com", "Pat", ""),
        ("", "", ""),
    ]
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE job_search_entries (id INTEGER PRIMARY KEY, date TEXT, "
            "employer_name TEXT, type_of_work TEXT, contact_type TEXT, outcome TEXT, "
            "contact_detail TEXT, person_contacted TEXT, notes TEXT)"
        )
        db.executemany(
            "INSERT INTO job_search_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [row + detail for row, detail in zip(rows, details, strict=True)],
        )


def test_contact_ledger_import_is_idempotent_and_read_only(tmp_path):
    src = tmp_path / "old.sqlite3"
    _contacts_db(src)
    before = src.read_bytes()

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        first = (import_contact_ledger(conn, src), _counts(conn))
        second = (import_contact_ledger(conn, src), _counts(conn))
        jobs = conn.execute("SELECT job_key, company, title FROM jobs ORDER BY job_key").fetchall()
        events = conn.execute(
            "SELECT status, recorded_at, note, source FROM status_events ORDER BY id"
        ).fetchall()

    assert (first, second, [tuple(j) for j in jobs], [tuple(e) for e in events]) == (
        (ImportReport(imported=2, skipped=["entry 3"], jobs=2, events=2), (2, 0, 2)),
        (ImportReport(imported=0, skipped=["entry 3"]), (2, 0, 2)),
        [
            ("https://acme.com/job/1", "Acme", "Engineer"),
            ("pasted:beta-dev-7a3fc084", "Beta", "Dev"),
        ],
        [
            ("Applied", "2026-09-01", "Contact method: Online | via site", "contacts-import"),
            (
                "Emailed",
                "2026-09-02",
                "Contact method: Email | a@b.com | Person: Pat",
                "contacts-import",
            ),
        ],
    )
    assert src.read_bytes() == before


def test_contact_ledger_without_the_table_raises_a_clear_error(tmp_path):
    src = tmp_path / "empty.sqlite3"
    sqlite3.connect(src).close()

    with (
        closing(ledger.connect(tmp_path / "l.db")) as conn,
        pytest.raises(ValueError, match="cannot read contact ledger"),
    ):
        import_contact_ledger(conn, src)


def _csv(tmp_path, body, header="Company,Title,Recorded Date,URL,Status,Notes"):
    path = tmp_path / "r.csv"
    path.write_text(f"{header}\n{body}", encoding="utf-8")
    return path


def _import_csv(tmp_path, csv_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_record_csv(conn, csv_path)
        jobs = [tuple(r) for r in conn.execute("SELECT job_key FROM jobs ORDER BY job_key")]
        events = [
            tuple(r) for r in conn.execute("SELECT job_key, recorded_at, note FROM status_events")
        ]
    return report, jobs, events


def test_csv_non_url_goes_to_the_note_and_blank_rows_are_skipped(tmp_path):
    path = _csv(
        tmp_path,
        "Acme,Eng,2026-10-01,via quick apply,Applied,hi\n,,2026-10-02,,Applied,\n",
    )

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=1, skipped=["line 3"], jobs=1, events=1),
        [("pasted:acme-eng-82da35ff",)],
        [("pasted:acme-eng-82da35ff", "2026-10-01", "hi | URL: via quick apply")],
    )


def test_csv_dates_are_normalized_so_formats_dedupe(tmp_path):
    path = _csv(
        tmp_path,
        "Acme,Eng,10/1/2026,,Applied,\nAcme,Eng,2026-10-01,,Applied,\n"
        "Acme,Eng,10/2/26,,Seen,\nAcme,Eng,Oct 3,,Seen,\n",
    )

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=2, skipped=["line 5"], jobs=1, events=2),
        [("pasted:acme-eng-82da35ff",)],
        [
            ("pasted:acme-eng-82da35ff", "2026-10-01", None),
            ("pasted:acme-eng-82da35ff", "2026-10-02", None),
        ],
    )


def test_csv_labels_follow_real_lines_after_multiline_cells(tmp_path):
    path = _csv(tmp_path, 'Acme,Eng,2026-10-01,,Applied,"two\nlines"\n,,,,Applied,\n')

    report, _, _ = _import_csv(tmp_path, path)

    assert report == ImportReport(imported=1, skipped=["line 4"], jobs=1, events=1)


def test_csv_missing_columns_raises(tmp_path):
    path = _csv(tmp_path, "x\n", header="Foo,Bar")

    with (
        closing(ledger.connect(tmp_path / "l.db")) as conn,
        pytest.raises(ValueError, match=r"missing columns \['Company', 'Title', 'URL'\]"),
    ):
        import_record_csv(conn, path)


def test_archive_with_a_non_url_jd_url_is_keyed_by_company_and_title(tmp_path):
    apps = _archive(tmp_path, "s1", "linkedin.com")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        keys = [tuple(r) for r in conn.execute("SELECT job_key FROM jobs")]

    assert keys == [("pasted:acme-engineer-platform-789b02b5",)]


def test_pdf_name_with_brackets_is_relinked_exactly(tmp_path):
    apps = _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/gone/a [1].pdf")
    (apps / "a [1].pdf").write_bytes(b"%PDF")
    (apps / "a 1.pdf").write_bytes(b"%PDF")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    assert stored == str(apps / "a [1].pdf")


def test_ambiguous_pdf_name_is_not_relinked(tmp_path, caplog):
    apps = _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/gone/r.pdf")
    for sub in ("x", "y"):
        (apps / sub).mkdir()
        (apps / sub / "r.pdf").write_bytes(b"%PDF")

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    events = [json.loads(r.message)["event"] for r in caplog.records]
    assert (stored, events) == ("/gone/r.pdf", ["ledger_import_pdf_ambiguous"])


def test_contact_dates_and_urls_are_validated(tmp_path):
    src = tmp_path / "old.sqlite3"
    _contacts_db(src)
    with closing(sqlite3.connect(src)) as db, db:
        db.execute("UPDATE job_search_entries SET date = '9/2/2026' WHERE id = 2")
        db.execute("UPDATE job_search_entries SET date = 'soon' WHERE id = 1")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_contact_ledger(conn, src)
        dates = [tuple(r) for r in conn.execute("SELECT recorded_at FROM status_events")]

    assert (report, dates) == (
        ImportReport(imported=1, skipped=["entry 1", "entry 3"], jobs=1, events=1),
        [("2026-09-02",)],
    )


_SCORE_HEADER = (
    "Company,Title,Recorded Date,URL,Status,Notes,Resume score before tailoring,"
    "Resume score after tailoring,{resume},Link to cover letter used"
)


@pytest.mark.parametrize("resume_column", ["Link to resume used", "Link resume used"])
def test_csv_scores_and_links_go_into_the_note(tmp_path, resume_column):
    path = _csv(
        tmp_path,
        "Acme,Eng,2026-10-01,,Applied,hi,62,81,/r/acme.pdf,/r/acme-cl.pdf\n"
        "Beta,Dev,2026-10-02,,Applied,,,90,,\n",
        header=_SCORE_HEADER.format(resume=resume_column),
    )

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=2, skipped=[], jobs=2, events=2),
        [("pasted:acme-eng-82da35ff",), ("pasted:beta-dev-7a3fc084",)],
        [
            (
                "pasted:acme-eng-82da35ff",
                "2026-10-01",
                "hi | Score before: 62 | Score after: 81 | Resume: /r/acme.pdf | "
                "Cover letter: /r/acme-cl.pdf",
            ),
            ("pasted:beta-dev-7a3fc084", "2026-10-02", "Score after: 90"),
        ],
    )


def test_csv_row_with_notes_but_no_status_becomes_a_note_event(tmp_path):
    path = _csv(
        tmp_path,
        "Acme,Eng,2026-10-01,,,called back\nBeta,Dev,,,,no date\nGamma,Dev,2026-10-03,,,\n",
    )

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_record_csv(conn, path)
        events = [
            tuple(r)
            for r in conn.execute("SELECT job_key, status, recorded_at, note FROM status_events")
        ]
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    assert (report, events, jobs) == (
        ImportReport(imported=1, skipped=["line 3"], jobs=3, events=1),
        [("pasted:acme-eng-82da35ff", "Note", "2026-10-01", "called back")],
        3,
    )


def test_csv_iso_dates_with_a_time_part_dedupe_with_plain_dates(tmp_path):
    path = _csv(tmp_path, "Acme,Eng,2026-06-16T10:00:00,,Applied,\nAcme,Eng,2026-06-16,,Applied,\n")

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=1, skipped=[], jobs=1, events=1),
        [("pasted:acme-eng-82da35ff",)],
        [("pasted:acme-eng-82da35ff", "2026-06-16", None)],
    )


def test_contact_ledger_path_with_a_hash_opens_the_right_file(tmp_path):
    folder = tmp_path / "a#b"
    folder.mkdir()
    src = folder / "c.sqlite3"
    _contacts_db(src)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_contact_ledger(conn, src)

    assert report == ImportReport(imported=2, skipped=["entry 3"], jobs=2, events=2)


def _write_run(folder, session_id, timestamp, total):
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "session_id": session_id,
        "timestamp": timestamp,
        "jd_url": "https://a.com/1",
        "scores": {"final": {"total": total}},
    }
    (folder / f"{session_id}.json").write_text(json.dumps(data))


def test_repeated_session_keeps_the_newest_copy_and_warns(tmp_path, caplog):
    apps = tmp_path / "apps"
    _write_run(apps / "a", "s1", "2026-10-01T10:00:00+00:00", 10)
    _write_run(apps / "b", "s1", "2026-10-12T10:00:00+00:00", 90)

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_archives(conn, apps)
        stored = conn.execute("SELECT finalized_at, scores FROM runs").fetchall()

    warnings = [json.loads(r.message) for r in caplog.records]
    assert (report, [tuple(r) for r in stored], warnings) == (
        ImportReport(imported=1, skipped=[], jobs=1),
        [("2026-10-12T10:00:00+00:00", '{"final": {"total": 90}}')],
        [
            {
                "event": "ledger_import_duplicate_session",
                "session_id": "s1",
                "kept": "b/s1.json",
                "dropped": "a/s1.json",
            }
        ],
    )


def test_repeated_session_compares_timestamps_across_utc_offsets(tmp_path):
    apps = tmp_path / "apps"
    # 01:00-08:00 is 09:00 UTC: later than 05:00 UTC, though it sorts first as text.
    _write_run(apps / "a", "s1", "2026-10-12T05:00:00+00:00", 10)
    _write_run(apps / "b", "s1", "2026-10-12T01:00:00-08:00", 90)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = conn.execute("SELECT finalized_at FROM runs").fetchall()

    assert [tuple(r) for r in stored] == [("2026-10-12T01:00:00-08:00",)]


def test_archive_roots_are_combined_before_choosing_the_newest_session(tmp_path):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    _write_run(older, "s1", "2026-10-01T10:00:00+00:00", 10)
    _write_run(newer, "s1", "2026-10-12T10:00:00+00:00", 90)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_archives(conn, [older, newer])
        stored = conn.execute("SELECT finalized_at, scores FROM runs").fetchall()

    assert (report, [tuple(row) for row in stored]) == (
        ImportReport(imported=1, skipped=[], jobs=1),
        [("2026-10-12T10:00:00+00:00", '{"final": {"total": 90}}')],
    )


def test_archive_with_non_iso_timestamp_is_skipped(tmp_path):
    apps = tmp_path / "apps"
    _write_run(apps, "s1", "October 12", 90)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_archives(conn, apps)
        runs = conn.execute("SELECT session_id FROM runs").fetchall()

    assert (report, runs) == (ImportReport(imported=0, skipped=["s1.json"]), [])


def test_invalid_https_values_fall_back_to_identity_and_preserve_raw_url_in_note(tmp_path):
    path = _csv(
        tmp_path,
        "Acme,Eng,2026-10-01,https://,Applied,hi\n"
        "Beta,Dev,2026-10-02,https:///jobs/1,Applied,hi\n"
        "Gamma,Lead,2026-10-03,https:// not available,Applied,hi\n",
    )

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=3, skipped=[], jobs=3, events=3),
        [
            ("pasted:acme-eng-82da35ff",),
            ("pasted:beta-dev-7a3fc084",),
            ("pasted:gamma-lead-b09ee459",),
        ],
        [
            ("pasted:acme-eng-82da35ff", "2026-10-01", "hi | URL: https://"),
            ("pasted:beta-dev-7a3fc084", "2026-10-02", "hi | URL: https:///jobs/1"),
            ("pasted:gamma-lead-b09ee459", "2026-10-03", "hi | URL: https:// not available"),
        ],
    )


def test_contact_without_url_company_or_work_type_is_skipped(tmp_path):
    src = tmp_path / "old.sqlite3"
    _contacts_db(src)
    with closing(sqlite3.connect(src)) as db, db:
        db.execute(
            "INSERT INTO job_search_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (4, "2026-09-03", "", "", "Email", "Applied", "", "", ""),
        )

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_contact_ledger(conn, src)

    assert report == ImportReport(imported=2, skipped=["entry 3", "entry 4"], jobs=2, events=2)


def test_csv_job_only_row_reports_a_job_without_an_event(tmp_path):
    path = _csv(tmp_path, "Acme,Eng,2026-10-01,,,\n")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_record_csv(conn, path)

    assert (report.jobs, report.events) == (1, 0)


def test_csv_name_match_is_logged(tmp_path, caplog):
    path = _csv(tmp_path, "Acme,Eng,2026-10-01,,Applied,\n")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn,
            url="https://jobs.acme.com/1",
            company="Acme",
            title="Eng",
            seen_at="2026-09-01",
        )
        with caplog.at_level(logging.WARNING, logger="callback.ledger_import"):
            import_record_csv(conn, path)

    assert [json.loads(record.message) for record in caplog.records] == [
        {"event": "ledger_import_name_match", "label": "line 2", "job_key": key}
    ]


def test_csv_and_contact_events_with_different_notes_are_both_kept(tmp_path):
    path = _csv(tmp_path, "Acme,Eng,2026-10-01,,Applied,CSV note\n")
    src = tmp_path / "old.sqlite3"
    _contacts_db(src)
    with closing(sqlite3.connect(src)) as db, db:
        db.execute("DELETE FROM job_search_entries WHERE id != 1")
        db.execute(
            "UPDATE job_search_entries SET date = ?, employer_name = ?, type_of_work = ?, "
            "outcome = ?, contact_detail = ?, notes = ? WHERE id = 1",
            ("2026-10-01", "Acme", "Eng", "Applied", "", "Contact note"),
        )

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_record_csv(conn, path)
        import_contact_ledger(conn, src)
        events = conn.execute("SELECT note FROM status_events ORDER BY id").fetchall()

    assert [tuple(row) for row in events] == [
        ("CSV note",),
        ("Contact method: Online | Contact note",),
    ]


def _run_dict(session_id, url="https://a.com/1", pdf_path=None):
    return {
        "session_id": session_id,
        "timestamp": "2026-10-01T10:00:00+00:00",
        "jd_url": url,
        "keywords": {"company": "Acme", "title": "Eng"},
        "pdf_path": pdf_path,
    }


def test_existing_run_leaves_its_job_untouched(tmp_path):
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "s1.json").write_text(json.dumps(_run_dict("s1", url="https://new.com/2")))

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(
            conn,
            ledger.RunRecord(
                session_id="s1", timestamp="2026-10-05T00:00:00+00:00", jd_url="https://a.com/1"
            ),
        )
        report = import_archives(conn, apps)
        jobs = conn.execute("SELECT job_key FROM jobs").fetchall()

    assert (report, [tuple(j) for j in jobs]) == (
        ImportReport(imported=0, skipped=["s1.json"]),
        [("https://a.com/1",)],
    )


def test_csv_url_descriptor_becomes_a_dated_note(tmp_path):
    path = _csv(tmp_path, "Acme,Eng,2026-10-01,via LinkedIn,,\nBeta,Dev,,not listed,,\n")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_record_csv(conn, path)
        events = conn.execute("SELECT job_key, status, recorded_at, note FROM status_events")
        stored = [tuple(e) for e in events]

    assert (report, stored) == (
        ImportReport(imported=1, skipped=["line 3"], jobs=2, events=1),
        [("pasted:acme-eng-82da35ff", "Note", "2026-10-01", "URL: via LinkedIn")],
    )


def test_csv_undated_url_descriptor_is_reported_as_lost(tmp_path, caplog):
    path = _csv(tmp_path, "Beta,Dev,,not listed,,\n")

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_record_csv(conn, path)

    reasons = [json.loads(r.message)["reason"] for r in caplog.records]
    assert reasons == [
        "status or note has no valid Recorded Date or Email Date; "
        "URL descriptor 'not listed' not kept"
    ]


def test_same_named_archives_in_two_roots_are_told_apart_by_root(tmp_path, caplog):
    _write_run(tmp_path / "a", "s1", "2026-10-01T10:00:00+00:00", 10)
    _write_run(tmp_path / "b", "s1", "2026-10-02T10:00:00+00:00", 90)

    with caplog.at_level(logging.WARNING), closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, [tmp_path / "a", tmp_path / "b"])

    assert [json.loads(r.message) for r in caplog.records] == [
        {
            "event": "ledger_import_duplicate_session",
            "session_id": "s1",
            "kept": f"{tmp_path / 'b'}/s1.json",
            "dropped": f"{tmp_path / 'a'}/s1.json",
        }
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-01", "2026-10-01"),
        ("2026-10-01T12:30:00", "2026-10-01"),
        ("2026-10-01 12:30:00+00:00", "2026-10-01"),
        ("10/1/2026", "2026-10-01"),
        ("10/1/26", "2026-10-01"),
        ("2026-10-01oops", None),
        ("2026-10-01Tinvalid", None),
        ("2026-13-01", None),
    ],
)
def test_iso_date_accepts_only_whole_values(raw, expected):
    assert _iso_date(raw) == expected


def test_pdf_next_to_the_archive_json_wins_over_other_matches(tmp_path):
    apps = tmp_path / "apps"
    (apps / "one").mkdir(parents=True)
    (apps / "two").mkdir()
    (apps / "one" / "s1.json").write_text(json.dumps(_run_dict("s1", pdf_path="/gone/r.pdf")))
    (apps / "one" / "r.pdf").write_bytes(b"%PDF")
    (apps / "two" / "r.pdf").write_bytes(b"%PDF")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, apps)
        stored = _pdf_path(conn, "s1")

    assert stored == str(apps / "one" / "r.pdf")


def _contacts_db_with_metadata(path, *, reportable):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE job_search_entries (id INTEGER PRIMARY KEY, date TEXT, "
            "employer_name TEXT, type_of_work TEXT, contact_type TEXT, outcome TEXT, "
            "contact_detail TEXT, person_contacted TEXT, notes TEXT, reportable INTEGER)"
        )
        db.execute("CREATE TABLE job_search_metadata (entry_id INTEGER, key TEXT, value TEXT)")
        db.execute(
            "INSERT INTO job_search_entries VALUES "
            "(1, '2026-09-01', 'Acme', 'Eng', 'Online', 'Applied', '', '', '', ?)",
            (reportable,),
        )
        db.executemany(
            "INSERT INTO job_search_metadata VALUES (1, ?, ?)",
            [
                ("SalaryRange", "100-120"),
                ("SourceURL", "not a url"),
                ("JobURL", "https://acme.com/j/9"),
                ("ReqID", "R-9"),
                ("Alpha", "x"),
            ],
        )


_METADATA_NOTE = (
    "{}: Online | Alpha: x | JobURL: https://acme.com/j/9 | ReqID: R-9 | SourceURL: not a url"
)


@pytest.mark.parametrize(
    ("reportable", "note"),
    [
        (
            1,
            _METADATA_NOTE.format("Contact method"),
        ),
        (
            0,
            "Not reportable | " + _METADATA_NOTE.format("Contact"),
        ),
    ],
)
def test_contact_metadata_gives_url_salary_and_note_parts(tmp_path, reportable, note):
    src = tmp_path / "old.sqlite3"
    _contacts_db_with_metadata(src, reportable=reportable)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_contact_ledger(conn, src)
        job = conn.execute("SELECT job_key, salary_range FROM jobs").fetchall()
        events = conn.execute("SELECT note FROM status_events").fetchall()

    assert ([tuple(j) for j in job], [tuple(e) for e in events]) == (
        [("https://acme.com/j/9", "100-120")],
        [(note,)],
    )


def test_urlless_contact_attaches_to_the_one_matching_job(tmp_path):
    src = tmp_path / "old.sqlite3"
    _contacts_db(src)
    with closing(sqlite3.connect(src)) as db, db:
        db.execute(
            "UPDATE job_search_entries SET employer_name = ' beta ', "
            "type_of_work = 'DEV' WHERE id = 2"
        )

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn, url="https://beta.com/9", company="Beta", title="Dev", seen_at="2026-09-01"
        )
        import_contact_ledger(conn, src)
        keys = conn.execute("SELECT DISTINCT job_key FROM status_events ORDER BY 1").fetchall()

    assert [tuple(k) for k in keys] == [("https://acme.com/job/1",), ("https://beta.com/9",)]


def test_urlless_csv_row_attaches_to_the_one_matching_job(tmp_path):
    csv_path = tmp_path / "record.csv"
    csv_path.write_text(
        "Company,Title,Recorded Date,URL,Status\n"
        "acme,  staff engineer,2026-10-02,Recruiter thread,Interview\n",
        encoding="utf-8",
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url="https://acme.com/jobs/1",
            company="Acme",
            title="Staff Engineer",
            seen_at="2026-10-01",
        )
        report = import_record_csv(conn, csv_path)
        jobs = conn.execute("SELECT job_key FROM jobs").fetchall()
        events = conn.execute("SELECT job_key, status FROM status_events").fetchall()

    assert (report.jobs, [tuple(j) for j in jobs], [tuple(e) for e in events]) == (
        0,
        [("https://acme.com/jobs/1",)],
        [("https://acme.com/jobs/1", "Interview")],
    )


def test_placeholder_salary_does_not_block_a_real_one(tmp_path):
    csv_path = tmp_path / "record.csv"
    csv_path.write_text(
        "Company,Title,Recorded Date,URL,Salary range,Status\n"
        "Acme,SWE,2026-09-01,https://acme.com/j/1,Not listed,Skipped\n",
        encoding="utf-8",
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_record_csv(conn, csv_path)
        before = conn.execute("SELECT salary_range FROM jobs").fetchall()
        ledger.upsert_job(
            conn,
            url="https://acme.com/j/1",
            company="Acme",
            title="SWE",
            seen_at="2026-09-02",
            salary_range="$150K-$180K",
        )
        after = conn.execute("SELECT salary_range FROM jobs").fetchall()

    assert ([tuple(r) for r in before], [tuple(r) for r in after]) == (
        [(None,)],
        [("$150K-$180K",)],
    )


def test_run_import_reuses_a_runless_scan_job_by_name(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        scanned = ledger.upsert_job(
            conn,
            url="https://www.linkedin.com/jobs/view/123",
            company="Acme",
            title="Staff Engineer",
            seen_at="2026-10-01",
        )
        run = ledger.RunRecord(
            session_id="s1",
            timestamp="2026-10-02T10:00:00+00:00",
            keywords={"company": "Acme", "title": "Staff Engineer"},
        )
        ledger.record_imported_run_if_absent(conn, run)
        runs = conn.execute("SELECT job_key FROM runs").fetchall()
        jobs = conn.execute("SELECT count(*) FROM jobs").fetchone()

    assert ([tuple(r) for r in runs], tuple(jobs)) == ([(scanned,)], (1,))


def test_contact_prefers_the_job_url_over_a_url_contact_detail(tmp_path):
    src = tmp_path / "old.sqlite3"
    _contacts_db_with_metadata(src, reportable=1)
    with closing(sqlite3.connect(src)) as db, db:
        db.execute(
            "UPDATE job_search_entries SET contact_detail = 'https://linkedin.com/in/recruiter'"
        )

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_contact_ledger(conn, src)
        jobs = [tuple(r) for r in conn.execute("SELECT job_key FROM jobs")]
        notes = [r[0] for r in conn.execute("SELECT note FROM status_events")]

    assert (jobs, ["https://linkedin.com/in/recruiter" in n for n in notes]) == (
        [("https://acme.com/j/9",)],
        [True],
    )


def test_archive_with_a_blank_session_id_is_skipped(tmp_path):
    apps = _archive(tmp_path, "  ", "https://jobs.example.com/a")

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        report = import_archives(conn, apps)
        counts = _counts(conn)

    assert (report.imported, report.skipped, tuple(counts)) == (0, ["  .json"], (0, 0, 0))


def _csv_with_salary(tmp_path, salary):
    csv_path = tmp_path / "salary.csv"
    csv_path.write_text(
        "Company,Title,Recorded Date,Email Date,URL,Salary range,Status,Notes\n"
        f"Acme,Engineer,2026-10-01,,https://jobs.acme.com/1/,{salary},Applied,\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.mark.parametrize(
    ("row_salary", "note"),
    [("$190K-$230K", "Salary range: $190K-$230K"), ("180000-220000", None)],
)
def test_csv_salary_that_differs_from_the_stored_one_goes_in_the_note(tmp_path, row_salary, note):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url="https://jobs.acme.com/1/",
            company="Acme",
            title="Engineer",
            seen_at="2026-09-01",
            salary_range="180000-220000",
        )
        import_record_csv(conn, _csv_with_salary(tmp_path, row_salary))
        salary = conn.execute("SELECT salary_range FROM jobs").fetchone()[0]
        notes = [r[0] for r in conn.execute("SELECT note FROM status_events")]

    assert (salary, notes) == ("180000-220000", [note])


@pytest.mark.parametrize("urlless_first", [True, False])
def test_csv_url_and_urlless_rows_join_one_job_in_either_order(tmp_path, urlless_first):
    rows = [
        "Acme,Eng,2026-10-01,,Saved,\n",
        "Acme,Eng,2026-10-02,https://jobs.acme.com/1,Applied,\n",
    ]
    path = _csv(tmp_path, "".join(rows if urlless_first else rows[::-1]))

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_record_csv(conn, path)
        jobs = [tuple(r) for r in conn.execute("SELECT url FROM jobs")]
        events = [
            tuple(r) for r in conn.execute("SELECT status FROM status_events ORDER BY status")
        ]

    assert (jobs, events) == ([("https://jobs.acme.com/1",)], [("Applied",), ("Saved",)])


def test_relinked_pdf_path_is_absolute_for_a_relative_archive_root(tmp_path, monkeypatch):
    _archive(tmp_path, "s1", "https://a.com/1", pdf_path="/home/other/x/resume.pdf")
    found = tmp_path / "apps" / "resume.pdf"
    found.write_bytes(b"%PDF")
    monkeypatch.chdir(tmp_path)

    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        import_archives(conn, Path("apps"))
        stored = _pdf_path(conn, "s1")

    assert stored == str(found.resolve())
