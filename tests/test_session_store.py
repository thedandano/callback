import logging
import os
import stat
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.types import RunnableConfig  # pyright: ignore[reportPrivateImportUsage]

from callback import paths
from callback.session_store import _delete_if_still_stale, checkpoint_time, open_checkpointer
from callback.state import TailoredResume


def _cfg(thread_id: str) -> RunnableConfig:
    return RunnableConfig(configurable={"thread_id": thread_id, "checkpoint_ns": ""})


def test_checkpoint_time_decodes_the_uuid6_timestamp():
    actual = checkpoint_time("1f1beb99-0588-66d4-8009-4dccb8b18086")
    assert actual == datetime(2026, 10, 2, 23, 32, 42, 514402, tzinfo=UTC)


def test_open_prunes_only_threads_idle_past_the_cutoff(tmp_path):
    db = tmp_path / "s.db"
    checkpoint = empty_checkpoint()
    open_checkpointer(db).put(_cfg("t1"), checkpoint, {}, {})
    created = checkpoint_time(checkpoint["id"])

    kept = open_checkpointer(db, now=created + timedelta(hours=23)).get_tuple(_cfg("t1"))
    pruned = open_checkpointer(db, now=created + timedelta(hours=25)).get_tuple(_cfg("t1"))

    assert (kept is not None, pruned is None) == (True, True)


def test_tailored_resume_round_trips_without_unregistered_type_warning(tmp_path, caplog):
    saver = open_checkpointer(tmp_path / "s.db")
    resume = TailoredResume(name="Jane Doe")
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"tailored": resume}
    saver.put(_cfg("t1"), checkpoint, {}, {})

    with caplog.at_level(logging.WARNING):
        stored = saver.get_tuple(_cfg("t1"))
    assert stored is not None
    loaded = stored.checkpoint["channel_values"]["tailored"]

    warnings = [r.getMessage() for r in caplog.records if "unregistered type" in r.getMessage()]
    assert (loaded, warnings) == (resume, [])


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_open_makes_the_session_folder_private(tmp_path):
    folder = tmp_path / "sessions"
    open_checkpointer(folder / "s.db")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_open_refuses_a_symlinked_session_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(PermissionError, match="refusing unsafe session dir"):
        open_checkpointer(link / "s.db")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_open_refuses_a_session_folder_the_owner_cannot_traverse(tmp_path):
    folder = tmp_path / "sessions"
    folder.mkdir()
    folder.chmod(0o600)
    with pytest.raises(PermissionError, match="lock the owner out"):
        open_checkpointer(folder / "s.db")


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
def test_open_refuses_a_session_folder_others_can_read(tmp_path):
    folder = tmp_path / "sessions"
    folder.mkdir()
    folder.chmod(0o755)
    with pytest.raises(PermissionError, match="refusing unsafe session dir"):
        open_checkpointer(folder / "s.db")


def test_delete_skips_a_thread_that_got_a_fresh_checkpoint_after_it_was_picked(tmp_path):
    db = tmp_path / "s.db"
    saver = open_checkpointer(db)
    old = empty_checkpoint()
    saver.put(_cfg("t1"), old, {}, {})
    now = checkpoint_time(old["id"]) + timedelta(hours=25)  # t1 looks stale when picked
    saver.put(_cfg("t1"), {**empty_checkpoint(), "id": _uuid6_at(now)}, {}, {})  # then it resumes

    deleted = _delete_if_still_stale(saver, "t1", now)

    assert (deleted, saver.get_tuple(_cfg("t1")) is not None) == (False, True)


def test_session_dir_name_has_no_uid_where_getuid_is_missing(monkeypatch):
    monkeypatch.delattr(os, "getuid", raising=False)

    assert paths.session_dir().name == "callback"


def _uuid6_at(moment: datetime) -> str:
    ticks = int((moment - datetime(1582, 10, 15, tzinfo=UTC)).total_seconds() * 10_000_000)
    high = ((ticks >> 12) << 16) | (6 << 12) | (ticks & 0xFFF)
    return str(uuid.UUID(int=(high << 64) | (0x8000 << 48) | 1))


def test_open_moves_recent_legacy_threads_and_removes_the_old_db(tmp_path):
    legacy = tmp_path / "state" / "s.db"
    old_saver = open_checkpointer(legacy)
    fresh, stale = empty_checkpoint(), empty_checkpoint()
    stale["id"] = _uuid6_at(datetime.now(UTC) - timedelta(hours=48))
    old_saver.put(_cfg("fresh"), fresh, {}, {})
    old_saver.put(_cfg("stale"), stale, {}, {})
    old_saver.conn.close()

    saver = open_checkpointer(tmp_path / "new" / "s.db", legacy_paths=(legacy,))

    assert (
        saver.get_tuple(_cfg("fresh")) is not None,
        saver.get_tuple(_cfg("stale")) is None,
        legacy.exists(),
    ) == (True, True, False)


def test_open_moves_threads_from_the_original_data_dir_too(tmp_path):
    state_legacy = tmp_path / "state" / "s.db"
    data_legacy = tmp_path / "data" / "s.db"
    old_saver = open_checkpointer(data_legacy)
    old_saver.put(_cfg("from-data"), empty_checkpoint(), {}, {})
    old_saver.conn.close()

    saver = open_checkpointer(tmp_path / "new" / "s.db", legacy_paths=(state_legacy, data_legacy))

    assert (
        saver.get_tuple(_cfg("from-data")) is not None,
        data_legacy.exists(),
    ) == (True, False)


def test_malformed_legacy_checkpoint_id_keeps_the_old_db_and_opens(tmp_path):
    legacy = tmp_path / "state" / "s.db"
    old_saver = open_checkpointer(legacy)
    old_saver.put(_cfg("bad"), empty_checkpoint(), {}, {})
    old_saver.conn.execute("UPDATE checkpoints SET checkpoint_id = 'not-a-uuid'")
    old_saver.conn.commit()
    old_saver.conn.close()

    saver = open_checkpointer(tmp_path / "new" / "s.db", legacy_paths=(legacy,))

    assert (
        saver.get_tuple(_cfg("bad")),
        legacy.exists(),
    ) == (None, True)


def test_threads_from_state_and_data_legacy_dbs_both_move(tmp_path):
    state_legacy = tmp_path / "state" / "s.db"
    data_legacy = tmp_path / "data" / "s.db"
    for path, thread in ((state_legacy, "from-state"), (data_legacy, "from-data")):
        old_saver = open_checkpointer(path)
        old_saver.put(_cfg(thread), empty_checkpoint(), {}, {})
        old_saver.conn.close()

    saver = open_checkpointer(tmp_path / "new" / "s.db", legacy_paths=(state_legacy, data_legacy))

    assert (
        saver.get_tuple(_cfg("from-state")) is not None,
        saver.get_tuple(_cfg("from-data")) is not None,
        state_legacy.exists(),
        data_legacy.exists(),
    ) == (True, True, False, False)
