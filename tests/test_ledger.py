import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from unittest.mock import patch

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
        ("https://x.com/#!/job/2/?utm_source=a", "https://x.com#!/job/2"),
        ("https://mail.google.com/mail/#all/abc123", "https://mail.google.com/mail#all/abc123"),
        ("jobs.Example.com/a/", "https://jobs.example.com/a"),
        ("https://jobs.example.com/a", "https://jobs.example.com/a"),
    ],
)
def test_normalize_url_drops_tracking_noise_but_keeps_job_ids(raw, expected):
    assert ledger.normalize_url(raw) == expected


def test_gmail_style_fragments_give_different_keys():
    keys = [
        ledger.job_key(f"https://mail.google.com/mail/#all/{m}", None, None)
        for m in ("19e8b9f6", "19e8b9f7")
    ]
    assert keys == [
        "https://mail.google.com/mail#all/19e8b9f6",
        "https://mail.google.com/mail#all/19e8b9f7",
    ]


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


@pytest.mark.parametrize(
    "raw",
    [
        "https://jobs.example.com/1#description/requirements",
        "https://jobs.example.com/1#!details/requirements",
    ],
)
def test_normalize_url_drops_unrecognized_fragments(raw):
    assert ledger.normalize_url(raw) == "https://jobs.example.com/1"


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
        ("20261001", "2026-10-01T00:00:00+00:00"),
        ("", ""),
    ],
)
def test_canonical_timestamp_converts_to_utc_and_keeps_plain_dates(raw, expected):
    assert ledger.canonical_timestamp(raw) == expected


@pytest.mark.parametrize("raw", ["oops", "2026-02-31", "2026-00-01"])
def test_canonical_timestamp_warns_on_malformed_text(caplog, raw):
    with caplog.at_level("WARNING", logger="callback.ledger"):
        result = ledger.canonical_timestamp(raw)
    assert (result, [r.getMessage() for r in caplog.records]) == (
        raw,
        [f'{{"event": "ledger_timestamp_unparsed", "value": "{raw}"}}'],
    )


def test_blank_salary_never_blocks_a_later_range(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for salary in (" ", "$100K-$120K"):
            ledger.upsert_job(
                conn,
                url="https://a.com/1",
                company="Acme",
                title="Engineer",
                seen_at="2026-10-01",
                salary_range=salary,
            )
        stored = conn.execute("SELECT salary_range FROM jobs").fetchall()
    assert stored == [("$100K-$120K",)]


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


def test_job_key_by_name_matches_one_job_ignoring_case_and_spacing(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(conn, url=None, company="Acme  Co", title="Eng", seen_at="2026-10-01")
        ledger.upsert_job(conn, url="https://b.com/1", company="Beta", title="Dev", seen_at="")
        ledger.upsert_job(conn, url="https://b.com/2", company="beta", title="DEV", seen_at="")
        found = (
            ledger.job_key_by_name(conn, " acme co ", "ENG").job_key,
            ledger.job_key_by_name(conn, "Beta", "Dev").job_key,
            ledger.job_key_by_name(conn, "Gamma", "Dev").job_key,
        )

    assert found == ("pasted:acme-co-eng-04b335ed", None, None)


def _scanned_job(conn):
    return ledger.upsert_job(
        conn,
        url="https://www.linkedin.com/jobs/view/123",
        company="Acme",
        title="Engineer",
        seen_at="2026-10-01",
    )


def test_urlless_run_joins_the_one_runless_job_with_the_same_name(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        scanned = _scanned_job(conn)
        ledger.record_run(conn, _run(url=None))
        keys = conn.execute("SELECT job_key FROM runs").fetchall()
        jobs = conn.execute("SELECT job_key FROM jobs").fetchall()

    assert ([tuple(k) for k in keys], [tuple(j) for j in jobs]) == (
        [(scanned,)],
        [(scanned,)],
    )


def test_urlless_run_name_match_is_logged(tmp_path, caplog):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        scanned = _scanned_job(conn)
        with caplog.at_level(logging.INFO, logger="callback.ledger"):
            ledger.record_run(conn, _run(url=None))

    assert [json.loads(record.message) for record in caplog.records] == [
        {"event": "ledger_run_name_match", "session_id": "s1", "job_key": scanned}
    ]


def test_urlless_run_keeps_its_own_key_when_the_same_name_job_has_runs(tmp_path, caplog):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        scanned = _scanned_job(conn)
        ledger.record_run(conn, _run(session_id="s0", url=None))
        own = ledger.job_key(None, "Acme", "Engineer", "JD")
        with caplog.at_level(logging.WARNING, logger="callback.ledger"):
            ledger.record_run(conn, _run(session_id="s1", url=None))
        keys = conn.execute("SELECT session_id, job_key FROM runs ORDER BY 1").fetchall()

    warnings = [json.loads(r.message) for r in caplog.records if r.levelno == logging.WARNING]
    assert ([tuple(k) for k in keys], warnings) == (
        [("s0", scanned), ("s1", own)],
        [
            {"event": "ledger_run_name_match", "session_id": "s0", "job_key": scanned},
            {"event": "ledger_possible_twin_job", "matched_key": scanned, "own_key": own},
        ],
    )


def test_urlless_run_with_multiple_same_name_jobs_creates_and_logs_its_own_job(tmp_path, caplog):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        first = ledger.upsert_job(
            conn,
            url="https://jobs.example.com/first",
            company="Acme",
            title="Engineer",
            seen_at="2026-10-01",
        )
        second = ledger.upsert_job(
            conn,
            url="https://jobs.example.com/second",
            company="Acme",
            title="Engineer",
            seen_at="2026-10-01",
        )
        with caplog.at_level(logging.WARNING, logger="callback.ledger"):
            ledger.record_run(conn, _run(url=None))
        actual = {
            "jobs": [
                tuple(row) for row in conn.execute("SELECT job_key FROM jobs ORDER BY job_key")
            ],
            "runs": [
                tuple(row)
                for row in conn.execute("SELECT session_id, job_key FROM runs ORDER BY session_id")
            ],
            "warnings": [json.loads(record.message) for record in caplog.records],
        }

    own = ledger.job_key(None, "Acme", "Engineer", "JD")
    assert actual == {
        "jobs": [(first,), (second,), (own,)],
        "runs": [("s1", own)],
        "warnings": [
            {
                "event": "ledger_ambiguous_name_match",
                "session_id": "s1",
                "candidate_job_keys": [first, second],
                "action": "created_new_pasted_job",
            }
        ],
    }


def test_recorded_again_run_stays_on_the_job_it_already_has(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        job_a = _scanned_job(conn)
        ledger.record_run(conn, _run(url=None))
        ledger.upsert_job(
            conn,
            url="https://b.example.com/2",
            company="Acme",
            title="Engineer",
            seen_at="2026-10-02",
        )
        ledger.record_run(conn, _run(url=None))
        keys = conn.execute("SELECT job_key FROM runs").fetchall()
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    assert ([tuple(k) for k in keys], jobs) == ([(job_a,)], 2)


def test_placeholder_salary_is_stored_as_no_salary(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url="https://acme.com/j/1",
            company="Acme",
            title="SWE",
            seen_at="2026-09-01",
            salary_range=" N/A ",
        )
        stored = conn.execute("SELECT salary_range FROM jobs").fetchone()
    assert tuple(stored) == (None,)


def test_url_run_joins_pasted_job_that_already_carries_that_url(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        pasted = ledger.job_key(None, "Acme", "Engineer")
        ledger.upsert_job(
            conn,
            url=None,
            company="Acme",
            title="Engineer",
            seen_at="2026-10-01",
        )
        conn.execute(
            "UPDATE jobs SET url = ? WHERE job_key = ?",
            ("https://jobs.example.com/a", pasted),
        )
        ledger.record_run(conn, _run(url="https://jobs.example.com/a"))
        actual = {
            "runs": [tuple(r) for r in conn.execute("SELECT session_id, job_key FROM runs")],
            "jobs": [
                tuple(r) for r in conn.execute("SELECT job_key, url FROM jobs ORDER BY job_key")
            ],
        }

    assert actual == {
        "runs": [("s1", pasted)],
        "jobs": [(pasted, "https://jobs.example.com/a")],
    }


def _status(conn, key, status, day):
    ledger.add_status(conn, job_key=key, status=status, recorded_at=day, note=None, source="t")


def test_export_rows_shows_latest_status_and_latest_run_per_job(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, _run("s1", pdf="/a.pdf"))
        key = ledger.upsert_job(
            conn, url="https://jobs.example.com/a", company=None, title=None, seen_at="2026-10-01"
        )
        ledger.add_status(
            conn, job_key=key, status="Applied", recorded_at="2026-10-02", note="n1", source="t"
        )
        _status(conn, key, "Rejected", "2026-10-09")
        other = ledger.upsert_job(
            conn, url="https://b.com/1", company="B", title="Dev", seen_at="2026-10-03"
        )
        _status(conn, other, "Applied - confirmed", "2026-10-03")

        everything = ledger.export_rows(conn)
        applied_since = ledger.export_rows(conn, status_prefix="Applied", since="2026-10-03")
        applied_from_oct_1 = ledger.export_rows(conn, status_prefix="Applied", since="2026-10-01")

    acme = {
        "Company": "Acme",
        "Title": "Engineer",
        "URL": "https://jobs.example.com/a",
        "Salary range": None,
        "Status": "Rejected",
        "Status date": "2026-10-09",
        "Notes": None,
        "Score before": 50.0,
        "Score after": 70.0,
        "Resume PDF": "/a.pdf",
    }
    b = {
        "Company": "B",
        "Title": "Dev",
        "URL": "https://b.com/1",
        "Salary range": None,
        "Status": "Applied - confirmed",
        "Status date": "2026-10-03",
        "Notes": None,
        "Score before": None,
        "Score after": None,
        "Resume PDF": None,
    }
    assert (everything, applied_since, applied_from_oct_1) == ([acme, b], [b], [acme, b])


def test_export_rows_orders_run_timestamps_by_instant_not_text(tmp_path):
    earlier = _run("earlier").model_copy(
        update={
            "timestamp": "2026-10-01T18:00:00+00:00",
            "pdf_path": "/earlier.pdf",
            "scores": {"initial": {"total": 10.0}, "final": {"total": 20.0}},
        }
    )
    later = _run("later").model_copy(
        update={
            "timestamp": "2026-10-01T12:00:00-07:00",
            "pdf_path": "/later.pdf",
            "scores": {"initial": {"total": 30.0}, "final": {"total": 40.0}},
        }
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, earlier)
        ledger.record_run(conn, later)
        row = ledger.export_rows(conn)[0]
    assert (row["Score before"], row["Score after"], row["Resume PDF"]) == (
        30.0,
        40.0,
        "/later.pdf",
    )


def test_upsert_job_strips_metadata_and_replaces_existing_blanks(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn,
            url="https://a.com/1",
            company="  Acme  ",
            title="  Engineer  ",
            salary_range="  $100k  ",
            seen_at="2026-10-01",
        )
        conn.execute(
            "UPDATE jobs SET company = '', title = '', salary_range = '' WHERE job_key = ?", (key,)
        )
        ledger.upsert_job(
            conn,
            url="https://a.com/1",
            company="Beta",
            title="Developer",
            salary_range="$120k",
            seen_at="2026-10-02",
        )
        row = conn.execute(
            "SELECT company, title, salary_range FROM jobs WHERE job_key = ?", (key,)
        ).fetchone()
    assert row == ("Beta", "Developer", "$120k")


def test_find_job_returns_latest_status_or_not_found(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://a.com/1", company="A", title="Dev", seen_at="2026-10-01"
        )
        _status(conn, key, "Applied", "2026-10-01")
        _status(conn, key, "Rejected", "2026-10-05")
        found = ledger.find_job(conn, url="https://a.com/1/?utm_source=x", company=None, title=None)
        by_name = ledger.find_job(conn, url="https://other.com/9", company="a", title=" dev ")
        missing = ledger.find_job(conn, url="https://a.com/2", company=None, title=None)
        half_name = ledger.find_job(conn, url="https://a.com/3", company="A", title=None)

    hit = {"found": True, "company": "A", "title": "Dev", "status": "Rejected"}
    hit = {
        **hit,
        "status_date": "2026-10-05",
        "job_key": "https://a.com/1",
        "score_before": None,
        "score_after": None,
    }
    none = {
        "found": False,
        "company": None,
        "title": None,
        "status": None,
        "status_date": None,
        "job_key": None,
        "score_before": None,
        "score_after": None,
    }
    assert (found, by_name, missing, half_name) == (
        {**hit, "matched_by": "key"},
        {**hit, "matched_by": "company_title"},
        {**none, "matched_by": None},
        {**none, "matched_by": None},
    )


def test_find_job_normalizes_unicode_and_whitespace_and_returns_run_scores(tmp_path):
    run = _run().model_copy(
        update={
            "keywords": {"company": "MÜNCHEN GmbH", "title": "Senior  Engineer"},
            "scores": {"initial": {"total": 50.0}, "final": {"total": 70.0}},
        }
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, run)
        found = ledger.find_job(
            conn,
            url="https://other.example/job",
            company="münchen gmbh",
            title="Senior Engineer",
        )
    assert found == {
        "found": True,
        "company": "MÜNCHEN GmbH",
        "title": "Senior  Engineer",
        "status": None,
        "status_date": None,
        "job_key": "https://jobs.example.com/a",
        "score_before": 50.0,
        "score_after": 70.0,
        "matched_by": "company_title",
    }


def test_spreadsheet_safe_defuses_formulas_only():
    row = {
        "a": "=HYPERLINK(1)",
        "b": "Applied - confirmed",
        "c": "-5",
        "d": "\tx",
        "e": 3.5,
        "f": None,
        "g": "@x",
        "h": "+1",
        "i": "\rx",
        "j": "\nx",
    }
    assert ledger.spreadsheet_safe(row) == {
        "a": "'=HYPERLINK(1)",
        "b": "Applied - confirmed",
        "c": "'-5",
        "d": "'\tx",
        "e": 3.5,
        "f": None,
        "g": "'@x",
        "h": "'+1",
        "i": "'\rx",
        "j": "'\nx",
    }


def test_export_rows_status_filter_ignores_empty_and_escapes_wildcards(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for url, status in (("https://a.com/1", "Applied"), ("https://a.com/2", "A_plied")):
            key = ledger.upsert_job(conn, url=url, company="C", title=url, seen_at="2026-10-01")
            _status(conn, key, status, "2026-10-01")
        bare = ledger.upsert_job(
            conn, url="https://a.com/3", company="C", title="none", seen_at="2026-10-01"
        )
        everything = ledger.export_rows(conn, status_prefix="")
        underscore = ledger.export_rows(conn, status_prefix="A_p")
        percent = ledger.export_rows(conn, status_prefix="%")

    assert (
        [r["URL"] for r in everything],
        [r["URL"] for r in underscore],
        percent,
        bare,
    ) == (
        ["https://a.com/1", "https://a.com/2", "https://a.com/3"],
        ["https://a.com/2"],
        [],
        "https://a.com/3",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  https://a.com/1 ", "https://a.com/1"),
        ("HTTP://a.com/1", "HTTP://a.com/1"),
        ("Gmail thread: Jane", None),
        ("linkedin.com", None),
        ("  ", None),
        (None, None),
    ],
)
def test_url_or_none_accepts_only_http_urls(value, expected):
    assert ledger.url_or_none(value) == expected


def _update(**fields) -> ledger.StatusUpdate:
    base = {"status": "Applied", "recorded_at": "2026-10-01", "source": "t"}
    return ledger.StatusUpdate(**{**base, **fields})


def test_record_status_writes_job_and_event_in_one_transaction(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        with (
            patch.object(ledger, "_insert_status", side_effect=sqlite3.OperationalError("locked")),
            pytest.raises(sqlite3.OperationalError),
        ):
            ledger.record_status(conn, _update(url="https://a.com/1", company="A", title="E"))
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()

    assert jobs == (0,)


def test_export_events_filters_on_the_event_itself_newest_first(tmp_path):
    events = [("Applied", "2026-09-20"), ("Applied", "2026-10-01"), ("Rejected", "2026-10-10")]
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for i, (status, date) in enumerate(events):
            url = f"https://a.com/{i % 2}"
            ledger.record_status(
                conn, _update(status=status, recorded_at=date, url=url, company="A", title="E")
            )
        applied = ledger.export_events(conn, status_prefix="applied", since="2026-09-25")
        everything = ledger.export_events(conn)

    assert (applied, [row["Date"] for row in everything]) == (
        [
            {
                "Date": "2026-10-01",
                "Company": "A",
                "Title": "E",
                "URL": "https://a.com/1",
                "Status": "Applied",
                "Notes": None,
                "Source": "t",
            }
        ],
        ["2026-10-10", "2026-10-01", "2026-09-20"],
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-01T12:00:00-07:00", "2026-10-01T19:00:00+00:00"),
        ("2026-10-01T12:00:00", "2026-10-01T12:00:00+00:00"),
        ("2026-10-01T12:00:00.250000+00:00", "2026-10-01T12:00:00.250000+00:00"),
        ("20261001T120000+00:00", "2026-10-01T12:00:00+00:00"),
        ("2026-W40-4T12:00:00+00:00", "2026-10-01T12:00:00+00:00"),
    ],
)
def test_canonical_timestamp_is_utc_iso(raw, expected):
    assert ledger.canonical_timestamp(raw) == expected


def test_canonical_timestamp_keeps_unparseable_value_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="callback.ledger"):
        result = ledger.canonical_timestamp("not a time")
    assert (result, [json.loads(r.message)["event"] for r in caplog.records]) == (
        "not a time",
        ["ledger_timestamp_unparsed"],
    )


def test_runs_with_basic_and_week_date_timestamps_order_by_instant(tmp_path):
    basic = _run("basic").model_copy(
        update={
            "timestamp": "20261001T120000+00:00",
            "pdf_path": "/basic.pdf",
            "scores": {"initial": {"total": 1.0}, "final": {"total": 2.0}},
        }
    )
    week = _run("week").model_copy(
        update={
            "timestamp": "2026-W40-4T13:00:00+00:00",
            "pdf_path": "/week.pdf",
            "scores": {"initial": {"total": 3.0}, "final": {"total": 4.0}},
        }
    )
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_run(conn, basic)
        ledger.record_run(conn, week)
        stored = conn.execute("SELECT finalized_at FROM runs ORDER BY session_id").fetchall()
        row = ledger.export_rows(conn)[0]
        found = ledger.find_job(conn, url="https://jobs.example.com/a", company=None, title=None)
    assert (stored, row["Resume PDF"], (found["score_before"], found["score_after"])) == (
        [("2026-10-01T12:00:00+00:00",), ("2026-10-01T13:00:00+00:00",)],
        "/week.pdf",
        (3.0, 4.0),
    )


def test_imported_run_stores_canonical_timestamp(tmp_path):
    run = _run("imp").model_copy(update={"timestamp": "2026-10-01T12:00:00-07:00"})
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_imported_run_if_absent(conn, run)
        stored = conn.execute("SELECT finalized_at FROM runs").fetchone()
    assert stored == ("2026-10-01T19:00:00+00:00",)


def test_record_status_without_url_reuses_job_matching_company_and_title(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for day, company in (("2026-10-01", "MÜNCHEN GmbH"), ("2026-10-02", "münchen gmbh")):
            ledger.record_status(conn, _update(recorded_at=day, company=company, title="Engineer"))
        jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        events = conn.execute("SELECT COUNT(*) FROM status_events").fetchone()
    assert (jobs, events) == ((1,), (2,))


def test_status_filter_is_unicode_case_insensitive_prefix(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.record_status(
            conn, _update(status="Überprüft", url="https://a.com/1", company="A", title="E")
        )
        rows = ledger.export_rows(conn, status_prefix="über")
        events = ledger.export_events(conn, status_prefix="über")
        none = ledger.export_events(conn, status_prefix="x_")
    assert ([row["Status"] for row in rows], [e["Status"] for e in events], none) == (
        ["Überprüft"],
        ["Überprüft"],
        [],
    )


def test_export_contacts_keeps_contact_notes_and_applications_only(tmp_path):
    events = [
        ("Applied - confirmed", None),
        ("already applied", None),
        ("Seen", "Contact method: phone | Notes: called"),
        ("Seen", "just browsing"),
        ("Rejected", None),
        ("Needs review - not applied", None),
        ("Applied", "Not reportable | Contact: Email"),
        ("Applied", "  NOT REPORTABLE  "),
    ]
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        for i, (status, note) in enumerate(events):
            ledger.record_status(
                conn,
                _update(
                    status=status,
                    note=note,
                    recorded_at=f"2026-10-0{i + 1}",
                    url=f"https://a.com/{i}",
                    company="A",
                    title="E",
                ),
            )
        rows = ledger.export_contacts(conn)
    assert [(row["Status"], row["Notes"]) for row in rows] == [
        ("Seen", "Contact method: phone | Notes: called"),
        ("already applied", None),
        ("Applied - confirmed", None),
    ]


def test_find_job_flags_a_key_match_with_a_different_title(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url="https://acme.com/careers#backend",
            company="Acme",
            title="Backend Engineer",
            seen_at="2026-10-01",
        )
        kinds = [
            ledger.find_job(
                conn, url="https://acme.com/careers#designer", company="Acme", title=title
            )["matched_by"]
            for title in ("Product Designer", "backend  ENGINEER", None)
        ]
    assert kinds == ["key_title_mismatch", "key", "key"]


def test_find_job_flags_a_key_match_with_a_missing_stored_title(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        ledger.upsert_job(
            conn,
            url="https://acme.com/careers#unlabeled",
            company="Acme",
            title=None,
            seen_at="2026-10-01",
        )
        found = ledger.find_job(
            conn,
            url="https://acme.com/careers#backend",
            company="Acme",
            title="Backend Engineer",
        )
    assert found["matched_by"] == "key_title_mismatch"


def test_record_status_by_job_key_ignores_a_placeholder_salary(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(
            conn, url="https://a.com/1", company="A", title="E", seen_at="2026-10-01"
        )
        for salary in ("Not listed", "$150K-$180K"):
            ledger.record_status(
                conn,
                _update(job_key=key, salary_range=salary, status="Seen", recorded_at="2026-10-02"),
            )
        stored = conn.execute("SELECT salary_range FROM jobs").fetchall()
    assert stored == [("$150K-$180K",)]


def test_record_status_by_pasted_job_key_fills_blank_job_metadata(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.job_key(None, "Acme", "Engineer")
        ledger.record_status(
            conn,
            _update(company="Acme", title="Engineer", recorded_at="2026-10-01"),
        )
        ledger.record_status(
            conn,
            _update(
                job_key=key,
                url="https://jobs.acme.com/engineer/",
                company="Acme",
                title="Engineer",
                recorded_at="2026-10-02",
            ),
        )
        stored = conn.execute(
            "SELECT job_key, url, company, title FROM jobs WHERE job_key = ?", (key,)
        ).fetchone()
    assert stored == (key, "https://jobs.acme.com/engineer", "Acme", "Engineer")


def test_find_job_by_url_finds_a_pasted_job_that_later_got_that_url(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(conn, url=None, company="Acme", title="Eng", seen_at="2026-10-01")
        ledger.record_status(
            conn,
            _update(job_key=key, url="https://acme.com/jobs/9", status="Seen"),
        )
        found = ledger.find_job(
            conn, url="https://acme.com/jobs/9/?utm_source=x", company=None, title=None
        )
    assert (found["found"], found["job_key"], found["matched_by"]) == (True, key, "key")


def test_record_status_by_url_lands_on_the_pasted_job_that_has_that_url(tmp_path):
    with closing(ledger.connect(tmp_path / "l.db")) as conn:
        key = ledger.upsert_job(conn, url=None, company="Acme", title="Eng", seen_at="2026-10-01")
        ledger.record_status(
            conn, _update(job_key=key, url="https://acme.com/jobs/9", status="Seen")
        )
        ledger.record_status(conn, _update(url="https://acme.com/jobs/9", status="Applied"))
        rows = conn.execute("SELECT job_key, status FROM status_events ORDER BY id").fetchall()
    assert rows == [(key, "Seen"), (key, "Applied")]
