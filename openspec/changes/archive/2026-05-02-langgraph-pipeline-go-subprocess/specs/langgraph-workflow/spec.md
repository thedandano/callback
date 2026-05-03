## ADDED Requirements

### Requirement: Typed workflow state
The system SHALL define `ApplyState` as a Pydantic `BaseModel` containing all fields shared across workflow nodes: `session_id`, `jd_url`, `jd_raw_text`, `jd_text`, `keywords`, `resume_label`, `resume_content`, `scored_resumes`, `tailored_t1`, `tailored_t2`, `finalized`, and `error`. All fields SHALL be optional with `None` defaults except `session_id`.

#### Scenario: State initializes with session_id only
- **WHEN** a new `ApplyState` is constructed with only `session_id`
- **THEN** all other fields are `None` and no validation error is raised

#### Scenario: State carries error without losing prior data
- **WHEN** a node sets `error` on the state
- **THEN** all previously populated fields remain accessible on the same state object

### Requirement: LangGraph state graph with workflow nodes
The system SHALL define a `StateGraph` using `ApplyState` with nodes: `load_jd`, `score`, `tailor_t1`, `tailor_t2`, `finalize`. Edges SHALL be: `load_jd → score → tailor_t1 → tailor_t2 → finalize`. The graph SHALL be compiled with `interrupt_after=["load_jd","score","tailor_t1","tailor_t2"]` and a `SqliteSaver` checkpointer.

#### Scenario: Graph compiles without error
- **WHEN** the compiled graph is imported at server startup
- **THEN** no exception is raised and the graph object is non-None

#### Scenario: Graph interrupts after load_jd without running score
- **WHEN** the graph is invoked from START with initial state containing `jd_raw_text`
- **THEN** execution stops after `load_jd` and `score` has NOT yet run (checkpoint shows `load_jd` complete, `score` pending)

#### Scenario: Resuming after interrupt does not re-run completed nodes
- **WHEN** `update_state` injects `keywords` and `invoke(None, config)` is called after the `load_jd` interrupt
- **THEN** `load_jd` does not execute again and `score` runs exactly once

#### Scenario: Full pipeline advances through all nodes
- **WHEN** the graph is stepped through all five nodes via the interrupt/update_state/invoke pattern with `PI_APPLY_TEST_STUB=1`
- **THEN** the final state contains non-None values for `tailored_t2` and `finalized`

### Requirement: Disk-backed session persistence
The system SHALL use `SqliteSaver` pointing to `~/.local/share/pi-apply/sessions.db` as the LangGraph checkpointer. State SHALL persist across server restarts. A session SHALL be identified by a stable `thread_id` derived from `session_id`.

#### Scenario: Session survives restart
- **WHEN** the graph is partially advanced (e.g., `load_jd` complete) and the server process is restarted
- **THEN** invoking the graph with the same `thread_id` resumes from the last checkpoint rather than re-running completed nodes

#### Scenario: New session_id creates independent checkpoint
- **WHEN** two calls use different `session_id` values
- **THEN** their checkpoints are stored independently and do not interfere

### Requirement: Structured log at every node transition
Every node function SHALL emit a structured log entry at `INFO` level containing at minimum: node name, `session_id`, and input field names present (not values). Errors SHALL log at `ERROR` level with the exception message.

#### Scenario: Node entry is logged
- **WHEN** any workflow node is entered
- **THEN** a log line appears with `node`, `session_id`, and `input_fields` keys

#### Scenario: Node error is logged
- **WHEN** a node raises an exception
- **THEN** a log line at `ERROR` level appears with `node`, `session_id`, and `error` keys before the exception propagates
