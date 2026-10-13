import logging
import stat
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.types import RunnableConfig  # pyright: ignore[reportPrivateImportUsage]

from callback.session_store import checkpoint_time, open_checkpointer
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


def test_open_makes_the_session_folder_private(tmp_path):
    folder = tmp_path / "sessions"
    open_checkpointer(folder / "s.db")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_open_refuses_a_symlinked_session_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(PermissionError, match="refusing unsafe session dir"):
        open_checkpointer(link / "s.db")


def test_open_refuses_a_session_folder_others_can_read(tmp_path):
    folder = tmp_path / "sessions"
    folder.mkdir()
    folder.chmod(0o755)
    with pytest.raises(PermissionError, match="refusing unsafe session dir"):
        open_checkpointer(folder / "s.db")
