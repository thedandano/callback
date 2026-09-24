#!/usr/bin/env python3
"""Copy the real callback data dir, run the M2.5 migration on the copy, and diff index.md.

Never touches the real data. Prints the diff (empty means identical) and the
files the migration left behind that a user may want to clean up.
"""

import difflib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())

from callback import paths  # noqa: E402


def main() -> int:
    source = paths.data_dir()
    if not (source / "accomplishments.json").exists():
        print(f"no accomplishments.json under {source}; nothing to check")
        return 0
    scratch = Path(tempfile.mkdtemp(prefix="callback-migration-check-"))
    shutil.copytree(source, scratch / "callback")
    os.environ["XDG_DATA_HOME"] = str(scratch)
    os.environ.pop("CALLBACK_APPS_DIR", None)

    from callback.profile_nodes import compile_profile  # noqa: E402  (after env is set)
    from callback.repository import stories  # noqa: E402
    from callback.state import ProfileState  # noqa: E402

    label = "primary"
    before = (scratch / "callback" / "profile-wiki" / label / "index.md").read_text()
    written = stories.migrate_legacy_stories(label)
    compile_profile(ProfileState(session_id="migration-check"))
    after = (scratch / "callback" / "profile-wiki" / label / "index.md").read_text()
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            "index.md (before)",
            "index.md (after)",
            lineterm="",
        )
    )
    listed, warnings = stories.list_stories(label)
    print(f"migrated {written} pages; {len(listed)} stories readable; {len(warnings)} warnings")
    for w in warnings:
        print(f"  warning: {w}")
    print("index.md diff:" if diff else "index.md identical")
    print("\n".join(diff))
    leftovers = sorted(
        p.relative_to(source)
        for p in source.rglob("*")
        if ".k8sfix-bak" in p.name or p.parent.name.startswith("tmp")
    )
    if leftovers:
        print("left in place (not touched by callback):")
        for p in leftovers:
            print(f"  {p}")
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if diff or warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
