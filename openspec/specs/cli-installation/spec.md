## ADDED Requirements

### Requirement: Installable CLI entry point
The package SHALL expose an installed console script named `callback` via `pyproject.toml` project scripts. The command SHALL route to a Typer application in `callback.cli`.

#### Scenario: Console script resolves to CLI app
- **WHEN** the package is installed with `uv tool install .`
- **THEN** the `callback` command is available on PATH
- **AND** invoking `callback --help` exits 0
- **AND** the help output lists `serve`, `install-browsers`, `uninstall`, `update`, `logs`, `trace-check`, `config`, and `version`

### Requirement: CLI serve command starts MCP server
The `callback serve` command SHALL call `_ensure_browsers()` before starting the server. All other behaviour from the existing requirement remains unchanged.

#### Scenario: Serve command uses existing server entrypoint
- **WHEN** `callback serve` is invoked
- **THEN** `_ensure_browsers()` is called first
- **AND** it then starts the same MCP server implementation exposed by `callback.server`
- **AND** the server remains stdio-only
- **AND** no graph, scorer, or tool envelope behavior changes

#### Scenario: help output lists all commands
- **WHEN** `callback --help` is invoked
- **THEN** the output lists `serve`, `install-browsers`, `uninstall`, `update`, `logs`, `trace-check`, `config`, and `version`

### Requirement: CLI version command reports installed package version
The CLI SHALL provide `callback version`, which prints the installed package version from `importlib.metadata.version("callback")`.

#### Scenario: Version command prints project version
- **WHEN** `callback version` is invoked for an installed package
- **THEN** the command exits 0
- **AND** stdout contains the version declared for the installed `callback` distribution

### Requirement: CLI logs command tails server log
The CLI SHALL provide `callback logs`, which tails `~/.local/state/callback/server.log`. If the log file does not exist, the command SHALL return a clear non-zero error and MUST NOT create fake log content.

#### Scenario: Logs command tails existing log file
- **GIVEN** `~/.local/state/callback/server.log` exists
- **WHEN** `callback logs` is invoked
- **THEN** the command streams lines from that file

#### Scenario: Logs command reports missing log file
- **GIVEN** `~/.local/state/callback/server.log` does not exist
- **WHEN** `callback logs` is invoked
- **THEN** the command exits non-zero
- **AND** stderr names the missing log path

### Requirement: CLI config command manages a settings file callback owns
The CLI SHALL provide `callback config` commands that set, unset, and list
environment variable overrides stored in `~/.config/callback/env.json` (or
`$XDG_CONFIG_HOME/callback/env.json`), a settings file callback reads itself
at process startup. These commands SHALL NOT write to any MCP host's config
file (e.g. `~/.claude.json`, `~/.codex/config.toml`).

#### Scenario: env set writes the settings file
- **WHEN** `callback config env set CALLBACK_TRACE_BACKEND langsmith` is invoked
- **THEN** `~/.config/callback/env.json` contains `CALLBACK_TRACE_BACKEND = "langsmith"`
- **AND** other keys already present in the file remain present
- **AND** no MCP host config file is created or modified

#### Scenario: env list redacts secret-like values
- **GIVEN** `LANGSMITH_API_KEY` is configured in the settings file
- **WHEN** `callback config env list` is invoked
- **THEN** stdout lists `LANGSMITH_API_KEY=********`
- **AND** the real value is only shown when `--show-secrets` is provided

#### Scenario: invalid env names are rejected
- **WHEN** `callback config env set bad-name value` is invoked
- **THEN** the command exits non-zero
- **AND** the settings file is not created or modified

### Requirement: CLI config status reports settings and legacy host entries
The CLI SHALL provide `callback config status` as a read-only diagnostic
command. It SHALL print the contents of `~/.config/callback/env.json`,
redacting secret-like values unless `--show-secrets` is provided, and MUST NOT
create, normalize, or rewrite any file. It SHALL also warn, without writing
anything, if a legacy `callback` MCP server entry is still present in
`~/.claude.json` or `~/.codex/config.toml` from an old `setup-mcp` install,
naming `callback uninstall` as the way to remove it.

#### Scenario: status reports settings file contents
- **GIVEN** the settings file configures one or more env keys
- **WHEN** `callback config status` is invoked
- **THEN** stdout includes each configured env key
- **AND** secret-like values are redacted unless `--show-secrets` is provided

#### Scenario: status is read-only for a missing settings file
- **GIVEN** the settings file does not exist
- **WHEN** `callback config status` is invoked
- **THEN** stdout reports `(none)`
- **AND** the settings file is not created

#### Scenario: status warns about a legacy duplicate server entry
- **GIVEN** `~/.claude.json` or `~/.codex/config.toml` still has a `callback` MCP server entry
- **WHEN** `callback config status` is invoked
- **THEN** stderr contains a warning naming that host's config path
- **AND** the warning tells the user to run `callback uninstall`
- **AND** neither host config file is modified

### Requirement: CLI config langsmith writes tracing env vars
The CLI SHALL provide `callback config langsmith` as the guided LangSmith setup command. It SHALL write `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`, `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` into the settings file. Defaults SHALL be `LANGSMITH_ENDPOINT=https://api.smith.langchain.com` and `LANGSMITH_PROJECT=Callback`.

#### Scenario: LangSmith config writes expected env
- **WHEN** `callback config langsmith --api-key lsv2-key --project callback-demo` is invoked
- **THEN** the settings file contains the LangSmith tracing env vars
- **AND** `LANGSMITH_PROJECT` equals `callback-demo`
- **AND** `LANGSMITH_ENDPOINT` equals `https://api.smith.langchain.com`

#### Scenario: config changes require host restart
- **WHEN** `callback config langsmith` or `callback config env set` succeeds
- **THEN** stdout tells the user to restart the MCP host

### Requirement: CLI trace-check verifies LangSmith tracing setup
The CLI SHALL provide `callback trace-check` to verify that LangSmith tracing
can be used from the effective environment: process environment variables
merged with the settings file, process values winning. It SHALL NOT print
secret values.

#### Scenario: trace-check reports missing required env
- **GIVEN** `LANGSMITH_API_KEY` is not present in the process environment or the settings file
- **WHEN** `callback trace-check` is invoked
- **THEN** the command exits non-zero
- **AND** stderr says `LANGSMITH_API_KEY is required`

#### Scenario: trace-check verifies LangSmith API reachability
- **GIVEN** the effective environment has `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`, and `LANGSMITH_API_KEY`
- **WHEN** `callback trace-check` is invoked
- **THEN** the command imports LangSmith, constructs a client, and calls `list_projects(limit=1)`
- **AND** stdout reports ok without printing the API key

#### Scenario: trace-check can emit a safe test trace
- **GIVEN** LangSmith API reachability succeeds
- **WHEN** `callback trace-check --emit-test-trace` is invoked
- **THEN** the command emits one sanitized trace named `callback.trace_check`
- **AND** the trace contains no resume text, JD body text, wiki content, file paths, edits, or secrets

### Requirement: install-browsers command installs Playwright Chromium

The CLI SHALL provide `callback install-browsers` that runs `playwright install chromium` using `sys.executable -m playwright` to ensure the correct isolated-env Python is used. The command SHALL exit with playwright's return code.

#### Scenario: install-browsers succeeds
- **WHEN** `callback install-browsers` is invoked
- **THEN** it invokes `[sys.executable, "-m", "playwright", "install", "chromium"]` as a subprocess
- **AND** it exits with that subprocess's return code

### Requirement: serve command checks browser availability at startup

The `callback serve` command SHALL call `_ensure_browsers()` before starting the MCP server. `_ensure_browsers()` SHALL run `playwright install chromium` with stdout and stderr captured. If the subprocess exits non-zero, it SHALL emit a structured warning log to stderr and continue — it SHALL NOT abort server startup.

#### Scenario: browsers already installed — server starts normally
- **WHEN** `callback serve` is invoked and Chromium is already installed
- **THEN** `_ensure_browsers()` completes in under one second
- **AND** the MCP server starts normally

#### Scenario: browser install fails — server warns and continues
- **WHEN** `callback serve` is invoked and `playwright install chromium` exits non-zero
- **THEN** a structured warning is logged to stderr with `"event": "browser_install_failed"`
- **AND** the MCP server starts normally
- **AND** `load_jd` with a URL may fail later with a crawl4ai error

### Requirement: uninstall command removes MCP server entries

The CLI SHALL provide `callback uninstall` that removes the `callback` entry from `mcpServers` in `~/.claude.json` and from `mcp_servers` in `~/.codex/config.toml`. If either file does not exist, the command SHALL skip it silently. The command SHALL preserve all other keys.

#### Scenario: uninstall removes Claude entry
- **GIVEN** `~/.claude.json` contains `mcpServers["callback"]`
- **WHEN** `callback uninstall` is invoked
- **THEN** `mcpServers["callback"]` is absent from the file
- **AND** all other top-level keys are preserved

#### Scenario: uninstall skips missing config files
- **GIVEN** neither `~/.claude.json` nor `~/.codex/config.toml` exist
- **WHEN** `callback uninstall` is invoked
- **THEN** the command exits 0 without error

### Requirement: uninstall --purge deletes all data directories

When `callback uninstall --purge` is invoked, the command SHALL delete `~/.local/share/callback/` and `~/.local/state/callback/` in addition to removing MCP server entries. If a directory does not exist, it SHALL be skipped silently.

#### Scenario: purge deletes data and state dirs
- **GIVEN** `~/.local/share/callback/` and `~/.local/state/callback/` exist
- **WHEN** `callback uninstall --purge` is invoked
- **THEN** both directories are deleted
- **AND** MCP server entries are removed from both config files

#### Scenario: uninstall without --purge preserves data dirs
- **GIVEN** `~/.local/share/callback/` exists
- **WHEN** `callback uninstall` is invoked without `--purge`
- **THEN** `~/.local/share/callback/` still exists after the command

### Requirement: update command upgrades the installed tool

The CLI SHALL provide `callback update` that runs `uv tool upgrade callback` as a subprocess and exits with that subprocess's return code.

#### Scenario: update invokes uv tool upgrade
- **WHEN** `callback update` is invoked
- **THEN** it invokes `["uv", "tool", "upgrade", "callback"]` as a subprocess
- **AND** it exits with that subprocess's return code
