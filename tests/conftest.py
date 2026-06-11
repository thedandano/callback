import importlib
import os
import sys

import pytest


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


@pytest.fixture(autouse=True)
def restore_bridge_module(tmp_path):
    """Restore callback.bridge in sys.modules after tests that evict it.

    Resolution tests (test_resolution_*) pop the module to re-trigger import-time
    resolution. Without this fixture the next test's bare `import callback.bridge`
    would call _resolve_binary() against the real environment, failing in CI.
    """
    yield
    if "callback.bridge" not in sys.modules:
        fake_bin = tmp_path / "go-apply"
        fake_bin.touch()
        old = os.environ.get("GO_APPLY_BIN")
        os.environ["GO_APPLY_BIN"] = str(fake_bin)
        try:
            importlib.import_module("callback.bridge")
        finally:
            if old is None:
                os.environ.pop("GO_APPLY_BIN", None)
            else:
                os.environ["GO_APPLY_BIN"] = old
