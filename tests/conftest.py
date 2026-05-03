import importlib
import os
import sys

import pytest


@pytest.fixture(autouse=True)
def restore_bridge_module(tmp_path):
    """Restore pi_apply.bridge in sys.modules after tests that evict it.

    Resolution tests (test_resolution_*) pop the module to re-trigger import-time
    resolution. Without this fixture the next test's bare `import pi_apply.bridge`
    would call _resolve_binary() against the real environment, failing in CI.
    """
    yield
    if "pi_apply.bridge" not in sys.modules:
        fake_bin = tmp_path / "go-apply"
        fake_bin.touch()
        old = os.environ.get("GO_APPLY_BIN")
        os.environ["GO_APPLY_BIN"] = str(fake_bin)
        try:
            importlib.import_module("pi_apply.bridge")
        finally:
            if old is None:
                os.environ.pop("GO_APPLY_BIN", None)
            else:
                os.environ["GO_APPLY_BIN"] = old
