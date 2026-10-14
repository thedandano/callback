from contextlib import closing

import pytest

from callback import ledger


def _run(session_id="s1", url="https://jobs.example.com/a", pdf="/p.pdf") -> ledger.RunRecord:
    return ledger.RunRecord(
        session_id=session_id,
        timestamp="2026-10-12T10:00:00+00:00",
        jd_url=url,
        jd_text="JD",
        keywords={"company": "Acme", "title": "Engineer"},
        tailored_resume_text="resume",
        pdf_path=pdf,
        scores={"initial": {"total": 50.0}, "final": {"total": 70.0}},
        outcome={"no_coverage": False, "reason": None},
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://Jobs.Example.com/a/?utm_source=x&gh_jid=7&gh_src=abc#top",
            "https://jobs.example.com/a?gh_jid=7",
        ),
        (
            "https://www.indeed.com/viewjob?jk=abc123&from=serp&tk=x&vjs=3",
            "https://www.indeed.com/viewjob?jk=abc123",
        ),
        (
            "https://careers.example.com/job?domain=example.com&microsite=x&pid=42&location=SF",
            "https://careers.example.com/job?pid=42",
        ),
        (
            "https://www.ziprecruiter.com/job-redirect?match_token=abc&utm_source=x",
            "https://www.ziprecruiter.com/job-redirect?match_token=abc",
        ),
        ("HTTP://jobs.example.com/a", "https://jobs.example.com/a"),
        ("https://jobs.example.com/a", "https://jobs.example.com/a"),
    ],
)
def test_normalize_url_drops_tracking_noise_but_keeps_job_ids(raw, expected):
    assert ledger.normalize_url(raw) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("https://jobs.example.com/a/", "Acme", "Eng"), "https://jobs.example.com/a"),
        ((None, "Acme", "Senior Engineer"), "pasted:acme-senior-engineer"),
        ((None, None, None), "pasted:job"),
    ],
)
def test_job_key_uses_url_or_falls_back_to_company_and_title(args, expected):
    assert ledger.job_key(*args) == expected


def test_connect_uses_wal_and_creates_tables(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert (mode, tables) == ("wal", {"jobs", "runs", "status_events"})


def test_record_run_twice_keeps_one_run_and_the_latest_values(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, _run(pdf="/old.pdf"))
        ledger.record_run(conn, _run(pdf="/new.pdf"))
        rows = conn.execute(
            "SELECT r.session_id, j.job_key, j.company, j.title, r.pdf_path "
            "FROM runs r JOIN jobs j ON j.job_key = r.job_key"
        ).fetchall()
    assert rows == [("s1", "https://jobs.example.com/a", "Acme", "Engineer", "/new.pdf")]


def test_two_runs_for_one_posting_share_one_job(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, _run("s1", "https://jobs.example.com/a/"))
        ledger.record_run(conn, _run("s2", "https://jobs.example.com/a?utm_medium=e"))
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM jobs), (SELECT COUNT(*) FROM runs)"
        ).fetchone()
    assert counts == (1, 2)


def test_upsert_job_stores_the_normalized_url(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn, url="https://a.com/1/", company="A", title="Eng", seen_at="2026-10-01"
        )
        rows = conn.execute("SELECT job_key, url FROM jobs").fetchall()
    assert rows == [("https://a.com/1", "https://a.com/1")]


@pytest.mark.parametrize(
    ("seen_first", "seen_second"),
    [("2026-10-01", ""), ("", "2026-10-01")],
)
def test_an_empty_seen_at_never_clobbers_first_seen(tmp_path, seen_first, seen_second):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for seen in (seen_first, seen_second):
            ledger.upsert_job(conn, url="https://a.com/1", company="A", title="E", seen_at=seen)
        first_seen = conn.execute("SELECT first_seen FROM jobs").fetchall()
    assert first_seen == [("2026-10-01",)]


def test_add_status_is_append_only_and_ignores_exact_repeats(tmp_path):
    events = [("Applied", "2026-10-01"), ("Applied", "2026-10-01"), ("Rejected", "2026-10-05")]
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://x.com/1", company="X", title="Eng", seen_at="2026-10-01"
        )
        added = [
            ledger.add_status(conn, job_key=key, status=s, recorded_at=d, note=None, source="t")
            for s, d in events
        ]
        rows = conn.execute("SELECT status, recorded_at FROM status_events ORDER BY id").fetchall()
    assert (added, rows) == (
        [True, False, True],
        [("Applied", "2026-10-01"), ("Rejected", "2026-10-05")],
    )
