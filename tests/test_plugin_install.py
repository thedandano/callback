import pytest

from callback.plugin_install import PluginInstallError, install, resolve_targets


def test_resolve_both_returns_claude_and_codex():
    keys = [t.key for t in resolve_targets("both")]
    assert keys == ["claude", "codex"]


def test_resolve_single_target():
    assert [t.key for t in resolve_targets("claude")] == ["claude"]


def test_resolve_unknown_raises():
    with pytest.raises(ValueError):
        resolve_targets("emacs")


# --- default git-source (no explicit source) ---


def test_default_source_claude_uses_git_ref():
    out = install(resolve_targets("claude"), print_only=True)
    assert out == [
        "claude plugin marketplace add thedandano/callback",
        "claude plugin install callback@callback",
    ]


def test_default_source_codex_uses_owner_repo_source():
    out = install(resolve_targets("codex"), print_only=True)
    assert out == [
        "codex plugin marketplace add thedandano/callback",
        "codex plugin add callback@callback",
    ]


# --- explicit source override ---


def test_print_only_returns_commands_without_running():
    ran = []
    out = install(
        resolve_targets("claude"),
        source="/repo",
        runner=lambda argv: ran.append(argv),
        print_only=True,
    )
    assert ran == []
    assert out == [
        "claude plugin marketplace add /repo",
        "claude plugin install callback@callback",
    ]


def test_install_runs_each_command_via_runner():
    ran = []
    result = install(
        resolve_targets("claude"),
        source="/repo",
        runner=lambda argv: ran.append(argv),
        print_only=False,
    )
    assert ran == [
        ["claude", "plugin", "marketplace", "add", "/repo"],
        ["claude", "plugin", "install", "callback@callback"],
    ]
    assert result == [
        "claude plugin marketplace add /repo",
        "claude plugin install callback@callback",
    ]


def test_runner_failure_raises_plugin_install_error():
    def boom(argv):
        raise OSError("claude not found")

    with pytest.raises(PluginInstallError, match="claude"):
        install(
            resolve_targets("claude"),
            source="/repo",
            runner=boom,
            print_only=False,
        )
