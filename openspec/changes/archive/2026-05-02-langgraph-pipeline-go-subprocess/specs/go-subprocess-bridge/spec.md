## ADDED Requirements

### Requirement: Binary path resolution at startup
The system SHALL resolve the go-apply binary path once at import time using `GO_APPLY_BIN` env var first, falling back to `shutil.which("go-apply")`. If neither resolves to an executable file, the module SHALL raise `EnvironmentError` with a message that names the `GO_APPLY_BIN` env var.

#### Scenario: Binary found via PATH
- **WHEN** `GO_APPLY_BIN` is unset and `go-apply` is on `PATH`
- **THEN** the resolved path points to the binary and no error is raised

#### Scenario: Binary found via env var
- **WHEN** `GO_APPLY_BIN` is set to a valid executable path
- **THEN** the resolved path equals that value and no error is raised

#### Scenario: Binary not found raises at import
- **WHEN** `GO_APPLY_BIN` is unset and `go-apply` is not on `PATH`
- **THEN** importing the module raises `EnvironmentError` containing the string `GO_APPLY_BIN`

### Requirement: Subprocess invocation with explicit error handling
The system SHALL expose `run_pdfrender(args: list[str]) -> bytes` and `run_survival(args: list[str]) -> str` functions. Both SHALL invoke the resolved binary via `subprocess.run` with `check=False`, capture stdout and stderr, and raise `SubprocessError` (a custom exception) if the return code is non-zero. The `SubprocessError` SHALL include the command, return code, and decoded stderr.

#### Scenario: Successful pdfrender call returns bytes
- **WHEN** `run_pdfrender` is called with valid args and the binary exits 0
- **THEN** the function returns the raw stdout bytes without raising

#### Scenario: Non-zero exit raises SubprocessError
- **WHEN** the binary exits with a non-zero return code
- **THEN** `SubprocessError` is raised with `returncode`, `cmd`, and `stderr` attributes populated

#### Scenario: SubprocessError includes stderr content
- **WHEN** the binary exits non-zero and wrote to stderr
- **THEN** the raised `SubprocessError.stderr` contains the decoded stderr output

### Requirement: No silent fallbacks
The system SHALL NOT catch `SubprocessError` internally. Callers (LangGraph nodes) are responsible for handling errors. No default output SHALL be returned when the subprocess fails.

#### Scenario: Caller receives SubprocessError unmodified
- **WHEN** the binary fails and a node calls `run_pdfrender`
- **THEN** `SubprocessError` propagates to the node without wrapping or suppression
