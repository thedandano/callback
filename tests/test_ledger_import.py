import json
import logging
import sqlite3
from contextlib import closing

import pytest

from callback import ledger
from callback.ledger_import import (
    ImportReport,
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
            ImportReport(imported=1, skipped=["notes.json"]),
            ImportReport(imported=1, skipped=["line 4"]),
            (3, 1, 1),
        ),
        (
            ImportReport(imported=0, skipped=["notes.json"]),
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

    assert (report, stored) == (ImportReport(imported=0, skipped=[]), "/new.pdf")


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
        (ImportReport(imported=2, skipped=["entry 3"]), (2, 0, 2)),
        (ImportReport(imported=0, skipped=["entry 3"]), (2, 0, 2)),
        [
            ("https://acme.com/job/1", "Acme", "Engineer"),
            ("pasted:beta-dev", "Beta", "Dev"),
        ],
        [
            ("Applied", "2026-09-01", "Contact: Online | via site", "contacts-import"),
            ("Emailed", "2026-09-02", "Contact: Email | a@b.com | Person: Pat", "contacts-import"),
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
        ImportReport(imported=1, skipped=["line 3"]),
        [("pasted:acme-eng",)],
        [("pasted:acme-eng", "2026-10-01", "hi | URL: via quick apply")],
    )


def test_csv_dates_are_normalized_so_formats_dedupe(tmp_path):
    path = _csv(
        tmp_path,
        "Acme,Eng,10/1/2026,,Applied,\nAcme,Eng,2026-10-01,,Applied,\n"
        "Acme,Eng,10/2/26,,Seen,\nAcme,Eng,Oct 3,,Seen,\n",
    )

    result = _import_csv(tmp_path, path)

    assert result == (
        ImportReport(imported=2, skipped=["line 5"]),
        [("pasted:acme-eng",)],
        [
            ("pasted:acme-eng", "2026-10-01", None),
            ("pasted:acme-eng", "2026-10-02", None),
        ],
    )


def test_csv_labels_follow_real_lines_after_multiline_cells(tmp_path):
    path = _csv(tmp_path, 'Acme,Eng,2026-10-01,,Applied,"two\nlines"\n,,,,Applied,\n')

    report, _, _ = _import_csv(tmp_path, path)

    assert report == ImportReport(imported=1, skipped=["line 4"])


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

    assert keys == [("pasted:acme-engineer-platform",)]


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
        ImportReport(imported=1, skipped=["entry 1", "entry 3"]),
        [("2026-09-02",)],
    )
