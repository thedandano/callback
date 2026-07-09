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
