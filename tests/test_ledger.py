import hashlib
import json
import logging
import sqlite3
from contextlib import closing

import pytest

from callback import ledger
from scripts import build_fetch_fixtures


def _run(
    session_id: str = "s1", url: str | None = "https://jobs.example.com/a", pdf: str = "/p.pdf"
) -> ledger.RunRecord:
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
            "https://www.indeed.com/viewjob?from=serp&jk=abc123",
        ),
        (
            "https://careers.example.com/job?domain=example.com&microsite=x&pid=42&location=SF",
            "https://careers.example.com/job?domain=example.com&location=SF&microsite=x&pid=42",
        ),
        (
            "https://www.ziprecruiter.com/job-redirect?match_token=abc&utm_source=x",
            "https://www.ziprecruiter.com/job-redirect?match_token=abc",
        ),
        (
            "https://x.taleo.net/jobdetail.ftl?job=111&lang=en&sort=date&page=2",
            "https://x.taleo.net/jobdetail.ftl?job=111&lang=en&page=2&sort=date",
        ),
        ("HTTP://jobs.example.com/a", "https://jobs.example.com/a"),
        ("http://jobs.example.com:80/a", "https://jobs.example.com/a"),
        ("https://jobs.example.com:443/a", "https://jobs.example.com/a"),
        ("https://jobs.example.com:8443/a", "https://jobs.example.com:8443/a"),
        ("https://x.com/#/job/1", "https://x.com#/job/1"),
        ("https://x.com/#!/job/2", "https://x.com#!/job/2"),
        ("jobs.Example.com/a/", "https://jobs.example.com/a"),
        ("https://jobs.example.com/a", "https://jobs.example.com/a"),
    ],
)
def test_normalize_url_drops_tracking_noise_but_keeps_job_ids(raw, expected):
    assert ledger.normalize_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://x.taleo.net/careersection/2/jobdetail.ftl?job=111",
            "https://x.taleo.net/careersection/2/jobdetail.ftl?job=111",
        ),
        (
            "https://career4.successfactors.com/career?career_job_req_id=5&company=acme",
            "https://career4.successfactors.com/career?career_job_req_id=5&company=acme",
        ),
        (
            "https://www.linkedin.com/jobs/search/?currentJobId=1&trk=x",
            "https://www.linkedin.com/jobs/search?currentJobId=1",
        ),
        (
            "https://jobs.example.com/view?jobid=1",
            "https://jobs.example.com/view?jobid=1",
        ),
    ],
)
def test_job_identifying_params_are_kept_in_normalized_url(raw, expected):
    assert ledger.normalize_url(raw) == expected


def test_tracking_params_are_dropped_case_insensitively_and_the_rest_sorted():
    raw = "https://jobs.example.com/v?UTM_Source=x&TrackingId=9&b=2&Lever-Source=y&a=1&FBCLID=z"
    assert ledger.normalize_url(raw) == "https://jobs.example.com/v?a=1&b=2"


def test_normalize_url_checks_the_outer_url_before_adding_https():
    raw = "jobs.example.com/view?next=https://apply.example/id"
    assert (
        ledger.normalize_url(raw)
        == "https://jobs.example.com/view?next=https%3A%2F%2Fapply.example%2Fid"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x.com/#/job/1?utm_source=x", "https://x.com#/job/1"),
        ("https://x.com/#/job/1/", "https://x.com#/job/1"),
    ],
)
def test_normalize_url_normalizes_route_fragments(raw, expected):
    assert ledger.normalize_url(raw) == expected


def test_protocol_relative_url_matches_the_absolute_url():
    actual = ledger.normalize_url("//jobs.example.com/a")
    assert (
        actual == ledger.normalize_url("https://jobs.example.com/a") == "https://jobs.example.com/a"
    )


def test_expected_keywords_falls_back_to_archive_when_ledger_dir_is_unreadable(
    tmp_path, monkeypatch, caplog
):
    expected_dir = tmp_path / "extract"
    expected_dir.mkdir()
    apps_dir = tmp_path / "apps"
    (apps_dir / "2026-10-01").mkdir(parents=True)
    (apps_dir / "2026-10-01" / "s1.json").write_text(json.dumps({"keywords": {"required": ["Go"]}}))

    def denied(_path=None):
        raise PermissionError("data dir not writable")

    monkeypatch.setattr(build_fetch_fixtures, "EXTRACT_DIR", expected_dir)
    monkeypatch.setattr(build_fetch_fixtures.paths, "apps_dir", lambda: apps_dir)
    monkeypatch.setattr(build_fetch_fixtures.ledger, "connect", denied)
    with caplog.at_level(logging.INFO, logger="scripts.build_fetch_fixtures"):
        actual = build_fetch_fixtures._expected_keywords("board", {"archived_session": "s1"})
    events = [json.loads(r.getMessage())["event"] for r in caplog.records]
    assert (actual, events) == (
        {"required": ["Go"]},
        ["ledger_expected_keywords_lookup_failed", "ledger_expected_keywords_source"],
    )


def test_normalize_url_keeps_ref_values_that_identify_distinct_jobs():
    first = ledger.normalize_url("https://jobs.example.com/view?ref=REQ-1")
    second = ledger.normalize_url("https://jobs.example.com/view?ref=REQ-2")
    assert (first, second) == (
        "https://jobs.example.com/view?ref=REQ-1",
        "https://jobs.example.com/view?ref=REQ-2",
    )


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("https://jobs.example.com/a/", "Acme", "Eng"), "https://jobs.example.com/a"),
        ((None, "Acme", "Senior Engineer"), "pasted:acme-senior-engineer-208d27d4"),
        ((None, None, None), "pasted:job-953efe8f"),
        (("   ", "Acme", "Eng"), "pasted:acme-eng-82da35ff"),
        ((None, "ACME", "  eng "), "pasted:acme-eng-82da35ff"),
    ],
)
def test_job_key_uses_url_or_falls_back_to_company_and_title(args, expected):
    assert ledger.job_key(*args) == expected


def _jd_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


@pytest.mark.parametrize(
    ("company", "title", "jd_text", "expected"),
    [
        (None, None, "JD one", f"pasted:job-{_jd_hash('JD one')}"),
        ("Acme", None, "JD one", f"pasted:acme-{_jd_hash('JD one')}"),
        (None, None, None, "pasted:job-953efe8f"),
        ("Acme", "Eng", "JD one", "pasted:acme-eng-82da35ff"),
    ],
)
def test_job_key_hashes_jd_text_when_company_or_title_is_missing(company, title, jd_text, expected):
    assert ledger.job_key(None, company, title, jd_text) == expected


def test_unlabeled_pasted_runs_with_different_jd_text_get_separate_jobs(tmp_path):
    runs = [
        _run(sid, url=None).model_copy(update={"keywords": None, "jd_text": text})
        for sid, text in (("s1", "JD one"), ("s2", "JD two"))
    ]
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for run in runs:
            ledger.record_run(conn, run)
        rows = conn.execute("SELECT session_id, job_key FROM runs ORDER BY session_id").fetchall()
    assert rows == [
        ("s1", f"pasted:job-{_jd_hash('JD one')}"),
        ("s2", f"pasted:job-{_jd_hash('JD two')}"),
    ]


def test_upsert_job_uses_jd_text_to_separate_unlabeled_pasted_jobs(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        first = ledger.upsert_job(
            conn,
            url=None,
            company=None,
            title=None,
            seen_at="2026-10-12",
            jd_text="First pasted job",
        )
        second = ledger.upsert_job(
            conn,
            url=None,
            company=None,
            title=None,
            seen_at="2026-10-12",
            jd_text="Second pasted job",
        )
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert (first != second, count) == (True, (2,))


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


def test_record_run_sets_salary_range_from_keyword_pay_bounds(tmp_path):
    run = _run().model_copy(
        update={
            "keywords": {
                "company": "Acme",
                "title": "Engineer",
                "pay_range_min": 150000.0,
                "pay_range_max": 200000.0,
            }
        }
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, run)
        salary_range = conn.execute("SELECT salary_range FROM jobs").fetchone()
    assert salary_range == ("150000-200000",)


def test_record_run_keeps_an_existing_salary_range(tmp_path):
    run = _run().model_copy(
        update={"keywords": {"company": "Acme", "title": "Engineer", "pay_range_min": 150000.0}}
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url=run.jd_url,
            company=run.company,
            title=run.title,
            seen_at=run.timestamp,
            salary_range="180000-220000",
        )
        ledger.record_run(conn, run)
        salary_range = conn.execute("SELECT salary_range FROM jobs").fetchone()
    assert salary_range == ("180000-220000",)


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


def test_add_status_keeps_distinct_sources_and_notes_for_the_same_day(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://x.com/1", company="X", title="Eng", seen_at="2026-10-01"
        )
        added = [
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01",
                note="Email",
                source="gmail",
            ),
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01",
                note="Portal",
                source="csv",
            ),
        ]
        events = conn.execute("SELECT source, note FROM status_events ORDER BY id").fetchall()
    assert (added, events) == ([True, True], [("gmail", "Email"), ("csv", "Portal")])


def test_add_status_canonicalizes_timestamps_before_deduplicating(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://x.com/1", company="X", title="Eng", seen_at="2026-10-01"
        )
        added = [
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01T12:00:00-04:00",
                note="Portal",
                source="csv",
            ),
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01T16:00:00+00:00",
                note="Portal",
                source="csv",
            ),
            ledger.add_status(
                conn,
                job_key=key,
                status="Saved",
                recorded_at="2026-10-01",
                note="Portal",
                source="csv",
            ),
        ]
        events = conn.execute(
            "SELECT status, recorded_at FROM status_events ORDER BY id"
        ).fetchall()
    assert (added, events) == (
        [True, False, True],
        [("Applied", "2026-10-01T16:00:00+00:00"), ("Saved", "2026-10-01")],
    )


def test_add_status_rejects_null_source_but_ignores_an_exact_repeat(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://x.com/1", company="X", title="Eng", seen_at="2026-10-01"
        )
        with pytest.raises(sqlite3.IntegrityError):
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01",
                note=None,
                source=None,  # type: ignore[arg-type]
            )
        added = [
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01",
                note=None,
                source="csv",
            ),
            ledger.add_status(
                conn,
                job_key=key,
                status="Applied",
                recorded_at="2026-10-01",
                note=None,
                source="csv",
            ),
        ]
    assert added == [True, False]


def test_job_key_uses_jd_text_when_labels_are_whitespace_only():
    keys = [
        ledger.job_key(None, " ", "\t", "First pasted job"),
        ledger.job_key(None, " ", "\t", "Second pasted job"),
    ]
    assert keys == [
        f"pasted:job-{_jd_hash('First pasted job')}",
        f"pasted:job-{_jd_hash('Second pasted job')}",
    ]


def test_expected_keywords_reads_the_matching_ledger_run_before_legacy_archive(
    tmp_path, monkeypatch, caplog
):
    expected_dir = tmp_path / "extract"
    expected_dir.mkdir()
    ledger_path = tmp_path / "ledger.db"
    monkeypatch.setattr(build_fetch_fixtures, "EXTRACT_DIR", expected_dir)
    monkeypatch.setattr(build_fetch_fixtures.paths, "ledger_path", lambda: ledger_path)
    with closing(ledger.connect(ledger_path)) as conn:
        ledger.record_run(
            conn, _run("archived-session").model_copy(update={"keywords": {"required": ["Python"]}})
        )
    with caplog.at_level(logging.INFO, logger="scripts.build_fetch_fixtures"):
        actual = build_fetch_fixtures._expected_keywords(
            "board", {"archived_session": "archived-session"}
        )
    messages = [record.getMessage() for record in caplog.records]
    assert (
        actual,
        any('"ledger_expected_keywords_source"' in message for message in messages),
    ) == (
        {"required": ["Python"]},
        True,
    )


def test_unparseable_url_is_logged_and_kept_as_typed(caplog):
    with caplog.at_level(logging.WARNING, logger="callback.ledger"):
        actual = ledger.normalize_url("  http://[bad  ")
    messages = [r.getMessage() for r in caplog.records]
    assert (actual, len(messages), '"ledger_url_unparsed"' in messages[0]) == (
        "http://[bad",
        1,
        True,
    )


def test_blank_url_is_stored_as_null(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(conn, url="  ", company="Acme", title="Eng", seen_at="2026-10-01")
        rows = conn.execute("SELECT job_key, url FROM jobs").fetchall()
    assert rows == [("pasted:acme-eng-82da35ff", None)]


def test_a_failed_run_leaves_no_job_behind(tmp_path):
    bad = _run().model_copy(update={"outcome": {"x": object()}})
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        with pytest.raises(TypeError):
            ledger.record_run(conn, bad)
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert jobs == (0,)


def test_missing_keywords_are_stored_as_sql_null(tmp_path):
    run = _run().model_copy(update={"keywords": None})
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, run)
        rows = conn.execute("SELECT keywords FROM runs").fetchall()
    assert rows == [(None,)]


def test_company_and_title_ignore_non_text_values():
    run = _run().model_copy(update={"keywords": {"company": ["Acme"], "title": "  Eng  "}})
    assert (run.company, run.title) == (None, "Eng")


def test_connect_closes_and_logs_when_setup_fails(tmp_path, caplog):
    path = tmp_path / "l.db"
    path.write_bytes(b"this is not a sqlite database" * 100)
    with (
        caplog.at_level(logging.WARNING, logger="callback.ledger"),
        pytest.raises(sqlite3.DatabaseError),
    ):
        ledger.connect(path)
    messages = [r.getMessage() for r in caplog.records]
    assert (len(messages), '"ledger_open_failed"' in messages[0]) == (1, True)


def test_add_status_for_an_unknown_job_is_rejected(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn, pytest.raises(sqlite3.IntegrityError):
        ledger.add_status(
            conn, job_key="nope", status="Applied", recorded_at="d", note=None, source="t"
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("Acme", "C++ Engineer"), ("ACME", "c++   engineer")),
        (("Acme", "Engineer \u2013 Backend"), ("acme", "ENGINEER \u2013 backend")),
    ],
)
def test_pasted_job_key_ignores_case_and_spacing_for_lossy_titles(first, second):
    assert ledger.job_key(None, *first) == ledger.job_key(None, *second)


def test_pasted_job_key_keeps_the_company_title_boundary():
    keys = (
        ledger.job_key(None, "Meta Platforms", "Engineer"),
        ledger.job_key(None, "Meta", "Platforms Engineer"),
    )
    assert keys == (
        "pasted:meta-platforms-engineer-be6a1bae",
        "pasted:meta-platforms-engineer-55afff7e",
    )


def test_normalize_url_keeps_a_blank_valued_param_that_names_the_posting():
    actual = [
        ledger.normalize_url("https://jobs.example.com/opening?R1234"),
        ledger.normalize_url("https://jobs.example.com/opening?R9999"),
        ledger.normalize_url("https://jobs.example.com/opening?R1234&utm_source=x"),
    ]
    assert actual == [
        "https://jobs.example.com/opening?R1234=",
        "https://jobs.example.com/opening?R9999=",
        "https://jobs.example.com/opening?R1234=",
    ]


def test_first_seen_is_the_earliest_moment_across_offsets(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for stamp in ("2026-10-01T23:00:00-07:00", "2026-10-02T01:00:00+00:00"):
            ledger.upsert_job(conn, url="https://a.com/1", company=None, title=None, seen_at=stamp)
        first_seen = conn.execute("SELECT first_seen FROM jobs").fetchall()
    assert first_seen == [("2026-10-02T01:00:00+00:00",)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-01T23:00:00-07:00", "2026-10-02T06:00:00+00:00"),
        ("2026-10-01T10:00:00", "2026-10-01T10:00:00+00:00"),
        ("2026-10-01", "2026-10-01"),
        ("", ""),
    ],
)
def test_canonical_timestamp_converts_to_utc_and_keeps_plain_dates(raw, expected):
    assert ledger.canonical_timestamp(raw) == expected


def test_connect_creates_the_status_event_identity_index_on_a_fresh_ledger(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        names = [row[1] for row in conn.execute("PRAGMA index_list(status_events)")]
    assert names == ["status_events_identity"]


def test_blank_labels_and_seen_at_never_block_later_values(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(conn, url="https://a.com/1", company=" ", title="", seen_at=" ")
        ledger.upsert_job(
            conn, url="https://a.com/1", company="Acme", title="Engineer", seen_at="2026-10-01"
        )
        row = conn.execute("SELECT company, title, first_seen FROM jobs").fetchone()
    assert (tuple(row), ledger.canonical_timestamp("  2026-10-01 ")) == (
        ("Acme", "Engineer", "2026-10-01"),
        "2026-10-01",
    )
