# quality-gates

## ADDED Requirements

### Requirement: Pre-commit framework configured
The repository SHALL include a `.pre-commit-config.yaml` at the project root
and `pre-commit` SHALL be declared as a dev dependency in `pyproject.toml`.

#### Scenario: pre-commit installs hooks
- **WHEN** a developer runs `uv run pre-commit install`
- **THEN** the command exits 0
- **AND** subsequent `git commit` invocations trigger the configured hooks

### Requirement: Spaghetti-score pre-commit hook installed
The pre-commit configuration SHALL include a local hook that runs the
`ai-slop-score` CLI against the repository and reports the score and band
on every commit. The hook MUST be wired and runnable via
`uv run pre-commit run --all-files`.

The **threshold at which the hook blocks** is intentionally not specified
by this change — calibration is deferred to a follow-up change once real
implementations replace the no-op sentinel strings (which currently
saturate the `magic_literals` metric and skew the score upward in a way
that doesn't reflect real code quality). Until then, the wrapper's
`--threshold` flag (defaulting to 20) is configurable but the binding
"must be low" constraint does not apply to this skeleton change.

#### Scenario: Hook is installed and runnable
- **WHEN** a developer runs `uv run pre-commit run --all-files`
- **THEN** the hook executes and prints the score and band
- **AND** the exit code reflects the wrapper's current threshold setting

### Requirement: Spaghetti-score wrapper script
The repository SHALL include a `scripts/check_spaghetti.py` wrapper that:

- invokes the `ai-slop-score` CLI on the repo root
- parses the JSON output
- prints the score and band on a single line
- exits 0 if band is `low`, non-zero otherwise

The wrapper SHALL accept an optional `--threshold <int>` flag overriding the
default threshold of 20 (band `low` upper bound).

#### Scenario: Default threshold blocks at score 20
- **WHEN** the wrapper runs against a repo whose score is exactly 20
- **THEN** it exits non-zero

#### Scenario: Override threshold permits higher score
- **WHEN** the wrapper runs with `--threshold 40` against a repo whose score
  is 30
- **THEN** it exits 0
