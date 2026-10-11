import sys

import pytest


@pytest.fixture(autouse=True)
def isolate_xdg_env(monkeypatch):
    """Delete every XDG override so an inherited value from a developer's real
    shell can never redirect a test at real data/state/config directories —
    e.g. a migration test moving/deleting a real legacy database instead of
    the disposable one it created for itself."""
    for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolate_server_db(tmp_path, monkeypatch):
    """Redirect SQLite DBs to tmp dir before server import."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    for mod in ("callback.server", "callback.apply_graph", "callback.profile_graph"):
        sys.modules.pop(mod, None)

    import callback.server  # noqa: F401

    yield

    for mod in ("callback.server", "callback.apply_graph", "callback.profile_graph"):
        sys.modules.pop(mod, None)


@pytest.fixture
def decisions(monkeypatch):
    """Capture record_decision labels.

    Stands in for an open LangSmith span: every accepted label lands in the
    returned dict, exactly as it would land in the span's metadata.
    """
    # With tracing switched on in the shell, trace_node would run the real langsmith
    # traceable, which calls the function patched below and gets the fake.
    monkeypatch.delenv("CALLBACK_TRACE_BACKEND", raising=False)
    captured: dict[str, object] = {}

    class _FakeRunTree:
        metadata = captured

    monkeypatch.setattr("langsmith.run_helpers.get_current_run_tree", lambda: _FakeRunTree())
    return captured
