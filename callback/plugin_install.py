"""Data-driven harness install targets and install logic."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field


class PluginInstallError(Exception):
    """Raised when a runner fails to install for a target."""

    pass


def _subprocess_runner(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


@dataclass(frozen=True)
class HarnessTarget:
    """Configuration for a single harness (Claude or Codex).

    Attributes:
        key: Logical identifier (e.g. "claude", "codex").
        cli: The CLI binary name (first argv element).
        marketplace_add: Subcommand tokens for the marketplace-add step.
        install: Subcommand tokens for the plugin-install step (no source arg).
        default_source: Git source used when no explicit source is provided.
    """

    key: str
    cli: str
    marketplace_add: tuple[str, ...] = field(default_factory=tuple)
    install: tuple[str, ...] = field(default_factory=tuple)
    default_source: str = ""

    def commands(self, source: str | None = None) -> list[list[str]]:
        """Generate marketplace add + plugin install commands.

        Args:
            source: Explicit source (local path or git ref). When None, falls
                    back to ``self.default_source`` (the published git source).

        Returns:
            List of argv lists: [marketplace add, plugin install].
        """
        resolved = source if source else self.default_source
        return [
            [self.cli, *self.marketplace_add, resolved],
            [self.cli, *self.install],
        ]


HARNESS_TARGETS: dict[str, HarnessTarget] = {
    "claude": HarnessTarget(
        key="claude",
        cli="claude",
        marketplace_add=("plugin", "marketplace", "add"),
        install=("plugin", "install", "callback@callback"),
        default_source="thedandano/callback",
    ),
    "codex": HarnessTarget(
        key="codex",
        cli="codex",
        marketplace_add=("plugin", "marketplace", "add"),
        install=("plugin", "add", "callback@callback"),
        default_source="thedandano/callback",
    ),
}


def resolve_targets(target: str) -> list[HarnessTarget]:
    """Resolve a target string to a list of HarnessTargets.

    Args:
        target: One of "both", "claude", or "codex".

    Returns:
        List of HarnessTarget instances in order.

    Raises:
        ValueError: If target is unknown.
    """
    if target == "both":
        return list(HARNESS_TARGETS.values())
    if target in HARNESS_TARGETS:
        return [HARNESS_TARGETS[target]]
    raise ValueError(f"Unknown target: {target}")


def install(
    targets: list[HarnessTarget],
    source: str | None = None,
    runner: Callable[[list[str]], None] = _subprocess_runner,
    print_only: bool = False,
) -> list[str]:
    """Install the plugin on each target harness.

    Args:
        targets: List of HarnessTarget instances to install on.
        source: Explicit source (local path or git ref). When None, each target
                uses its ``default_source`` (the published git source).
        runner: Callable that executes a command (argv list).
                Raises an exception on failure.
                Defaults to a subprocess.run wrapper.
        print_only: If True, return commands without running them.
                    If False, execute via runner and return executed commands.

    Returns:
        List of command strings (space-joined argv).

    Raises:
        PluginInstallError: If runner fails for a target.
    """
    executed: list[str] = []

    for target in targets:
        commands = target.commands(source)
        for argv in commands:
            cmd_str = " ".join(argv)
            if print_only:
                executed.append(cmd_str)
            else:
                try:
                    runner(argv)
                    executed.append(cmd_str)
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise PluginInstallError(f"{target.key}: {cmd_str}: {exc}") from exc

    return executed
