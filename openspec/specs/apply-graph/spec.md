# apply-graph Specification

## Purpose

Define the topology, interface, and behavior of the `apply_graph` — a 10-node LangGraph
state machine that orchestrates a single job application end-to-end. The graph runs without
interrupts (single `.invoke()` call from `jd_fetch` to `finalize`) and manages all state
persistence via an SQLite checkpointer.
## Requirements
### Requirement: Apply graph topology
The system SHALL provide a LangGraph `StateGraph` named `apply_graph` whose
nodes are wired in the linear order `jd_fetch → keywords_extract →
parse_initial → score_initial → tailor → render → parse_final → score_final →
report → finalize`, with `jd_fetch` as the entry point and `finalize` as the
finish point.

#### Scenario: Graph compiles successfully
- **WHEN** `build_apply_graph()` is called
- **THEN** the returned compiled graph exposes a `.nodes` collection containing
  exactly the ten node names listed above
- **AND** the graph compiles without raising

#### Scenario: Linear edge wiring
- **WHEN** the compiled apply graph is invoked with a valid initial state
- **THEN** every node in the linear chain executes exactly once in order
- **AND** the final state contains a value written by `finalize`

### Requirement: No interrupts in apply graph
The apply graph SHALL be compiled without any `interrupt_after` or
`interrupt_before` configuration. The graph MUST run from `jd_fetch` to
`finalize` in a single `.invoke()` call without pausing.

#### Scenario: Single-call execution to END
- **WHEN** `apply_graph.invoke(initial_state, config)` is called once
- **THEN** the graph reaches its finish point in that single call
- **AND** the returned state's `finalized` field is truthy

### Requirement: Apply MCP tool surface
The system SHALL expose exactly one MCP workflow tool named `apply` that drives
the apply graph end-to-end. Tool input MUST accept a `jd_url` string OR a
`jd_raw_text` string (one required), plus a `resume_path` string. The tool MUST
return a JSON envelope containing `session_id`, `status`, and `data`.

#### Scenario: apply tool runs graph to completion
- **WHEN** the `apply` MCP tool is invoked with `jd_raw_text` and `resume_path`
- **THEN** the graph runs from `jd_fetch` through `finalize`
- **AND** the returned envelope's `status` field equals `"ok"`
- **AND** the envelope's `data` field includes `pdf_path` and `report`

#### Scenario: apply tool rejects missing input
- **WHEN** the `apply` tool is invoked with neither `jd_url` nor `jd_raw_text`
- **THEN** the tool returns an envelope with `status: "error"`
- **AND** the error code identifies the missing input

### Requirement: Keystone round-trip nodes share implementation
The system SHALL implement `parse_initial` and `parse_final` as two distinct
node names bound to a shared underlying function, parameterized on which input
field to read and which output field to write. The same SHALL apply to
`score_initial` and `score_final`.

#### Scenario: parse_initial reads source resume
- **WHEN** `parse_initial` runs
- **THEN** it reads `state.resume_path` as input
- **AND** it writes the extracted text to `state.parsed_initial`

#### Scenario: parse_final reads rendered PDF
- **WHEN** `parse_final` runs
- **THEN** it reads `state.pdf_path` as input
- **AND** it writes the extracted text to `state.parsed_final`

#### Scenario: score nodes write to distinct fields
- **WHEN** `score_initial` runs against `parsed_initial`
- **THEN** it writes the score breakdown to `state.score_initial` only
- **WHEN** `score_final` runs against `parsed_final`
- **THEN** it writes the score breakdown to `state.score_final` only

### Requirement: render produces a real on-disk file
The `render` node SHALL write a real file at the path it returns as
`pdf_path`, even when implemented as a no-op. The file MUST exist before
`parse_final` runs. The file MAY be empty in the no-op skeleton.

#### Scenario: pdf_path resolves to existing file
- **WHEN** `render` completes
- **THEN** `state.pdf_path` is a non-empty string
- **AND** the file at that path exists on disk
- **AND** `parse_final` is able to open the path without raising

### Requirement: report emits uncovered_skills audit field
The `report` node SHALL write a `report` dict and an `uncovered_skills` list to
state. `uncovered_skills` MUST be a list (possibly empty) of JD-required skill
names that have no matching profile story.

#### Scenario: report contains both fields after run
- **WHEN** `report` completes
- **THEN** `state.report` is a non-null dict
- **AND** `state.uncovered_skills` is a list (possibly empty)

### Requirement: finalize archives a complete audit record
The `finalize` node SHALL write a JSON archive to
`~/.local/share/pi-apply/applications/<session_id>.json` containing fields:
`session_id`, `timestamp`, `jd_url`, `jd_text`, `keywords`,
`tailored_resume_text`, `pdf_path`, `scores.initial`, `scores.final`,
`scores.scoring_engine_version`, and `uncovered_skills`. The node MUST set
`state.finalized` to `true`.

#### Scenario: archive file written with all fields
- **WHEN** `finalize` completes after a successful apply run
- **THEN** the archive JSON file exists at the expected path
- **AND** the JSON document has every field listed in this requirement

### Requirement: Apply graph nodes are no-ops in this change
Every node implementation in the apply graph SHALL be a no-op stub that logs
its entry, writes a sentinel placeholder to its output state field(s), and
returns. The skeleton MUST NOT call any LLM, HTTP client, real parser, real
scorer, or PDF renderer.

#### Scenario: Sentinel values present after run
- **WHEN** the apply graph runs end-to-end on minimal placeholder input
- **THEN** each output field contains a sentinel value identifying which node
  wrote it (e.g. a string prefixed with `<noop:>` or a dict containing
  `"stub": True`)

