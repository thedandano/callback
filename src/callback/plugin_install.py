"""Data-driven harness install targets and install logic."""

import subprocess
from collections.abc import Callable


class PluginInstallError(Exception):
    """Raised when a runner fails to install for a target."""

    pass


def _subprocess_runner(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


DEFAULT_SOURCE = "thedandano/callback"
_INSTALL_ARGS: dict[str, tuple[str, ...]] = {
    "claude": ("plugin", "install", "callback@callback"),
    "codex": ("plugin", "add", "callback@callback"),
}


def resolve_targets(target: str) -> list[str]:
    """'both' -> ["claude", "codex"]; a known key -> [key]; anything else raises ValueError."""
    if target == "both":
        return list(_INSTALL_ARGS)
    if target in _INSTALL_ARGS:
        return [target]
    raise ValueError(f"Unknown target: {target}")


def commands(target: str, source: str | None = None) -> list[list[str]]:
    """Marketplace-add then plugin-install argv lists for one harness."""
    return [
        [target, "plugin", "marketplace", "add", source or DEFAULT_SOURCE],
        [target, *_INSTALL_ARGS[target]],
    ]


def install(
    targets: list[str],
    source: str | None = None,
    runner: Callable[[list[str]], None] = _subprocess_runner,
    print_only: bool = False,
) -> list[str]:
    """Run (or, with print_only, just list) the install commands for each target."""
    executed: list[str] = []
    for target in targets:
        for argv in commands(target, source):
            cmd_str = " ".join(argv)
            if not print_only:
                try:
                    runner(argv)
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise PluginInstallError(f"{target}: {cmd_str}: {exc}") from exc
            executed.append(cmd_str)
    return executed
