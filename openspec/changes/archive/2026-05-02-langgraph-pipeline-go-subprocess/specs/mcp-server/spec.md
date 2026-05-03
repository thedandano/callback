## ADDED Requirements

### Requirement: MCP tool surface matches go-apply (12 tools)
The server SHALL expose exactly 12 MCP tools with identical names and argument schemas to go-apply. Required arguments SHALL remain required; optional arguments SHALL remain optional.

| Tool | Required args | Optional args |
|---|---|---|
| `onboard_user` | — | `resume_content`, `resume_label`, `skills`, `accomplishments`, `sections` |
| `add_resume` | `resume_content`, `resume_label` | `sections` |
| `get_config` | — | — |
| `update_config` | `key`, `value` | — |
| `load_jd` | — (one of jd_url/jd_raw_text required by logic) | `jd_url`, `jd_raw_text` |
| `submit_keywords` | `session_id`, `jd_json` | — |
| `submit_tailor_t1` | `session_id`, `edits` | — |
| `submit_tailor_t2` | `session_id`, `edits` | — |
| `preview_ats_extraction` | `session_id` | — |
| `finalize` | `session_id` | `cover_letter` |
| `compile_profile` | — | `skills`, `remove_skills`, `stories` |
| `create_story` | `skill`, `story_type`, `job_title`, `situation`, `behavior`, `impact` | `is_new_job`, `job_start_date`, `job_end_date`, `jd_context` |

#### Scenario: Tool list contains exactly 12 tools
- **WHEN** an MCP client requests the tool list from pi-apply
- **THEN** the response contains exactly 12 tool names matching the table above

#### Scenario: update_config requires key and value
- **WHEN** `update_config` is called without `key`
- **THEN** the server returns a missing-required-argument error before invoking any handler

### Requirement: load_jd accepts jd_url or jd_raw_text exclusively
Exactly one of `jd_url` or `jd_raw_text` SHALL be provided. Providing both or neither is an error.

#### Scenario: Both arguments provided returns invalid_input error
- **WHEN** `load_jd` is called with both `jd_url` and `jd_raw_text` populated
- **THEN** the server returns `{"status":"error","error":{"stage":"load_jd","code":"invalid_input","message":"exactly one of jd_url or jd_raw_text is required","retriable":false}}`

#### Scenario: Neither argument provided returns invalid_input error
- **WHEN** `load_jd` is called with neither `jd_url` nor `jd_raw_text`
- **THEN** the server returns an envelope with `error.code="invalid_input"`

### Requirement: Response envelope format
Every workflow tool SHALL return a JSON-encoded text result (not a plain Python object or dict dump) with the following schema:
```
{
  "session_id": string (omitempty),
  "status": "ok" | "needs_input" | "error",
  "next_action": string (omitempty),
  "data": any (omitempty),
  "error": { "stage": string, "code": string, "message": string, "retriable": bool } (omitempty),
  "warnings": [] (omitempty)
}
```
`next_action` values SHALL match go-apply exactly: `"extract_keywords"` (after `load_jd`), `"tailor_t1"` (after `submit_keywords`), `"tailor_t2"` (after `submit_tailor_t1`), `"finalize"` (after `submit_tailor_t2`). `finalize` returns no `next_action`.

#### Scenario: load_jd success returns envelope with next_action
- **WHEN** `load_jd` succeeds with valid `jd_raw_text`
- **THEN** the response is a JSON string with `status="ok"`, a non-empty `session_id`, `next_action="extract_keywords"`, and `data.jd_text` populated

#### Scenario: submit_keywords success returns next_action tailor_t1
- **WHEN** `submit_keywords` succeeds
- **THEN** `next_action="tailor_t1"` is present in the envelope

### Requirement: session_id minted by load_jd, required on all workflow tools
`load_jd` SHALL mint a UUID v4 as `session_id` and return it in the envelope. Every subsequent workflow tool (`submit_keywords`, `submit_tailor_t1`, `submit_tailor_t2`, `preview_ats_extraction`, `finalize`) SHALL require `session_id` as a mandatory argument. `thread_id = session_id` is used as the LangGraph checkpoint key.

#### Scenario: load_jd returns session_id
- **WHEN** `load_jd` is called with valid input
- **THEN** the envelope contains a non-empty `session_id` UUID string

#### Scenario: Unknown session_id returns session_not_found
- **WHEN** any workflow tool is called with a `session_id` not present in the checkpoint store
- **THEN** the server returns `{"status":"error","error":{"stage":"<tool>","code":"session_not_found","retriable":false}}`

### Requirement: Workflow ordering is enforced
Calling a workflow tool before its prerequisite SHALL return an `invalid_state` error. The valid ordering is: `load_jd` → `submit_keywords` → `submit_tailor_t1` → `submit_tailor_t2` → `finalize`.

#### Scenario: submit_keywords before load_jd returns invalid_state
- **WHEN** `submit_keywords` is called with a valid `session_id` that has not yet run `load_jd`
- **THEN** the server returns `{"status":"error","error":{"code":"invalid_state","retriable":false}}`

#### Scenario: submit_tailor_t1 before submit_keywords returns invalid_state
- **WHEN** `submit_tailor_t1` is called before `submit_keywords` has been called for that session
- **THEN** the server returns an envelope with `error.code="invalid_state"`

#### Scenario: finalize before submit_keywords returns invalid_state
- **WHEN** `finalize` is called before `submit_keywords` has been called for that session
- **THEN** the server returns an envelope with `error.code="invalid_state"`

### Requirement: Non-workflow tools bypass the graph
The tools `onboard_user`, `add_resume`, `get_config`, `update_config`, `compile_profile`, `create_story`, and `preview_ats_extraction` SHALL NOT invoke the LangGraph graph, write to the checkpoint store, or require `session_id`. They SHALL delegate directly to the data/config layer and return a plain JSON result.

#### Scenario: get_config returns config without session_id
- **WHEN** `get_config` is called with no arguments
- **THEN** the server returns the config fields without requiring or consuming a `session_id`

#### Scenario: Non-workflow tool called without onboarding returns error
- **WHEN** `onboard_user` is called with neither resume nor skills content
- **THEN** the server returns a structured error (no graph state is written)

### Requirement: Fail-fast startup on missing binary
The server SHALL fail to start if the go-apply binary cannot be resolved. The error SHALL identify `GO_APPLY_BIN`.

#### Scenario: Server exits non-zero when binary is missing
- **WHEN** the MCP server is started without go-apply on `PATH` and without `GO_APPLY_BIN` set
- **THEN** the process exits with a non-zero code and logs an error containing `GO_APPLY_BIN`

### Requirement: Structured JSON logging
The server SHALL emit structured JSON logs to stderr. Log level is configurable via `LOG_LEVEL` env var (default `INFO`). Each entry SHALL include `timestamp`, `level`, and `tool` or `node` and `session_id` where applicable.

#### Scenario: Tool invocation produces a log entry
- **WHEN** any MCP tool is invoked
- **THEN** a JSON log line appears on stderr with `tool` and (for workflow tools) `session_id` fields

#### Scenario: LOG_LEVEL=DEBUG enables full payload logging
- **WHEN** `LOG_LEVEL=DEBUG` is set and a tool is invoked
- **THEN** log entries include the input argument names and values
