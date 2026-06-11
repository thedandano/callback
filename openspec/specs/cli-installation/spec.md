## ADDED Requirements

### Requirement: Installable CLI entry point
The package SHALL expose an installed console script named `callback` via `pyproject.toml` project scripts. The command SHALL route to a Typer application in `callback.cli`.

#### Scenario: Console script resolves to CLI app
- **WHEN** the package is installed with `uv tool install .`
- **THEN** the `callback` command is available on PATH
- **AND** invoking `callback --help` exits 0
- **AND** the help output lists `serve`, `setup-mcp`, `install-browsers`, `uninstall`, `update`, `logs`, `trace-check`, `config`, and `version`

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
- **THEN** the output lists `serve`, `setup-mcp`, `install-browsers`, `uninstall`, `update`, `logs`, `trace-check`, `config`, and `version`

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

### Requirement: CLI config command manages MCP env vars
The CLI SHALL provide `callback config` commands that set, unset, and list environment variables stored in the `callback` MCP server entries for Claude and Codex. The commands SHALL support `--target claude|codex|all`, defaulting to `all`.

#### Scenario: env set writes Claude and Codex env maps
- **WHEN** `callback config env set CALLBACK_TRACE_BACKEND langsmith` is invoked
- **THEN** Claude config contains `mcpServers["callback"].env.CALLBACK_TRACE_BACKEND = "langsmith"`
- **AND** Codex config contains `mcp_servers["callback"].env.CALLBACK_TRACE_BACKEND = "langsmith"`
- **AND** unrelated config keys remain present

#### Scenario: env list redacts secret-like values
- **GIVEN** `LANGSMITH_API_KEY` is configured in a `callback` MCP server env map
- **WHEN** `callback config env list` is invoked
- **THEN** stdout lists `LANGSMITH_API_KEY=********`
- **AND** the real value is only shown when `--show-secrets` is provided

#### Scenario: invalid env names are rejected
- **WHEN** `callback config env set bad-name value` is invoked
- **THEN** the command exits non-zero
- **AND** no MCP config file is written

### Requirement: CLI config status reports MCP env drift
The CLI SHALL provide `callback config status` as a read-only diagnostic command
for Claude and Codex `callback` MCP env maps. The command SHALL support
`--target claude|codex|all`, default to `all`, redact secret-like values unless
`--show-secrets` is provided, and MUST NOT create, normalize, or rewrite config
files.

#### Scenario: status reports same values
- **GIVEN** Claude and Codex both configure a `callback` env key with the same value
- **WHEN** `callback config status` is invoked
- **THEN** stdout includes that env key for both targets
- **AND** the status is `same`

#### Scenario: status reports drift and missing values
- **GIVEN** Claude and Codex configure different values for one env key
- **AND** another env key is present in only one target
- **WHEN** `callback config status` is invoked
- **THEN** stdout reports `different` for the changed key
- **AND** stdout reports `missing` for the partially configured key

#### Scenario: status is read-only for missing config files
- **GIVEN** the selected MCP config files do not exist
- **WHEN** `callback config status` is invoked
- **THEN** stdout reports `unset`
- **AND** no MCP config file is written

### Requirement: CLI config langsmith writes tracing env vars
The CLI SHALL provide `callback config langsmith` as the guided LangSmith setup command. It SHALL write `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`, `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` to the selected MCP host config env maps. Defaults SHALL be `LANGSMITH_ENDPOINT=https://api.smith.langchain.com` and `LANGSMITH_PROJECT=Callback`.

#### Scenario: LangSmith config writes expected env
- **WHEN** `callback config langsmith --api-key lsv2-key --project callback-demo` is invoked
- **THEN** both Claude and Codex `callback` MCP env maps contain the LangSmith tracing env vars
- **AND** `LANGSMITH_PROJECT` equals `callback-demo`
- **AND** `LANGSMITH_ENDPOINT` equals `https://api.smith.langchain.com`

#### Scenario: config changes require host restart
- **WHEN** `callback config langsmith` or `callback config env set` succeeds
- **THEN** stdout tells the user to restart the MCP host

### Requirement: CLI trace-check verifies LangSmith tracing setup
The CLI SHALL provide `callback trace-check` to verify that LangSmith tracing can be used from active environment variables or configured Claude/Codex MCP env maps. The command SHALL support `--target env|claude|codex|all`, defaulting to `env`, and SHALL NOT print secret values.

#### Scenario: trace-check reports missing required env
- **GIVEN** `LANGSMITH_API_KEY` is not present for the selected target
- **WHEN** `callback trace-check` is invoked
- **THEN** the command exits non-zero
- **AND** stderr says `LANGSMITH_API_KEY is required`

#### Scenario: trace-check verifies LangSmith API reachability
- **GIVEN** the selected target has `CALLBACK_TRACE_BACKEND=langsmith`, `LANGSMITH_TRACING=true`, and `LANGSMITH_API_KEY`
- **WHEN** `callback trace-check --target claude` is invoked
- **THEN** the command imports LangSmith, constructs a client, and calls `list_projects(limit=1)`
- **AND** stdout reports the target as ok without printing the API key

#### Scenario: trace-check can emit a safe test trace
- **GIVEN** LangSmith API reachability succeeds
- **WHEN** `callback trace-check --emit-test-trace` is invoked
- **THEN** the command emits one sanitized trace named `callback.trace_check`
- **AND** the trace contains no resume text, JD body text, wiki content, file paths, edits, or secrets

### Requirement: setup-mcp writes Claude MCP config idempotently
The CLI SHALL provide `callback setup-mcp` that writes a Claude MCP server entry to `~/.claude.json` under `mcpServers["callback"]` with command `"callback"` and args `["serve"]`. The operation SHALL preserve unrelated keys and MUST be idempotent.

#### Scenario: setup-mcp creates Claude config entry
- **GIVEN** a Claude config file without `mcpServers["callback"]`
- **WHEN** `callback setup-mcp` writes Claude config
- **THEN** the file contains `mcpServers["callback"].command` equal to `"callback"`
- **AND** the file contains `mcpServers["callback"].args` equal to `["serve"]`
- **AND** unrelated top-level keys remain present

#### Scenario: setup-mcp is idempotent for Claude config
- **GIVEN** a Claude config file already containing the expected `callback` MCP server entry
- **WHEN** `callback setup-mcp` runs twice
- **THEN** the config contains exactly one `callback` MCP server entry
- **AND** the second run does not change the parsed config object

#### Scenario: setup-mcp preserves Claude env map
- **GIVEN** a Claude config file already containing `mcpServers["callback"].env`
- **WHEN** `callback setup-mcp` rewrites the server entry
- **THEN** the existing `env` map remains present

### Requirement: setup-mcp writes Codex MCP config idempotently
The CLI SHALL provide `callback setup-mcp` that writes a Codex MCP server entry to `~/.codex/config.toml` under `mcp_servers["callback"]` with command `"callback"` and args `["serve"]`. The operation SHALL preserve unrelated keys when the existing TOML can be parsed and MUST be idempotent.

#### Scenario: setup-mcp creates Codex config entry
- **GIVEN** a Codex config file without a `callback` MCP server entry
- **WHEN** `callback setup-mcp` writes Codex config
- **THEN** the file contains a `mcp_servers["callback"]` table
- **AND** that table's `command` value equals `"callback"`
- **AND** that table's `args` value equals `["serve"]`
- **AND** unrelated parseable config keys remain present

#### Scenario: setup-mcp is idempotent for Codex config
- **GIVEN** a Codex config file already containing the expected `callback` MCP server entry
- **WHEN** `callback setup-mcp` runs twice
- **THEN** the config contains exactly one `callback` MCP server entry
- **AND** the second run does not change the parsed config object

#### Scenario: setup-mcp preserves Codex env map
- **GIVEN** a Codex config file already containing `mcp_servers["callback"].env`
- **WHEN** `callback setup-mcp` rewrites the server entry
- **THEN** the existing `env` table remains present

#### Scenario: setup-mcp rejects invalid Codex TOML
- **GIVEN** `~/.codex/config.toml` exists but cannot be parsed as TOML
- **WHEN** `callback setup-mcp` runs
- **THEN** the command exits non-zero
- **AND** the original file remains unchanged

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
