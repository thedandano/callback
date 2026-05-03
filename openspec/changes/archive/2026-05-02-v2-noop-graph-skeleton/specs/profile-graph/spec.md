# profile-graph

## ADDED Requirements

### Requirement: Profile graph topology
The system SHALL provide a LangGraph `StateGraph` named `profile_graph`
containing the nodes `check_profile`, `onboard`, `compile_profile`,
`check_orphans`, and `create_story`. The graph MUST wire these edges:

- `check_profile` → `onboard` (when profile is missing)
- `check_profile` → `check_orphans` (when profile exists, skipping `onboard`
  and `compile_profile`)
- `onboard` → `compile_profile`
- `compile_profile` → `check_orphans`
- `check_orphans` → `create_story` (when orphans exist)
- `check_orphans` → END (when no orphans remain)
- `create_story` → `compile_profile` (cycle, recompile)

#### Scenario: Graph compiles successfully
- **WHEN** `build_profile_graph()` is called
- **THEN** the returned compiled graph contains exactly the five named nodes
- **AND** the graph compiles without raising

#### Scenario: First-run path executes onboard
- **WHEN** the graph runs with state where `profile_exists` is false
- **THEN** the execution trace includes `check_profile`, `onboard`,
  `compile_profile`, and `check_orphans`

#### Scenario: Existing-profile path skips onboard and compile
- **WHEN** the graph runs with state where `profile_exists` is true
- **THEN** the execution trace includes `check_profile` and `check_orphans`
- **AND** the trace does NOT include `onboard`
- **AND** the trace does NOT include `compile_profile`

### Requirement: Profile graph routers
`check_profile` and `check_orphans` SHALL be implemented as conditional-edge
router functions that read state and route without writing user-facing data.

#### Scenario: check_profile routes by profile_exists
- **WHEN** `check_profile` is invoked
- **THEN** it returns the next-node label `"onboard"` when
  `state.profile_exists` is false
- **AND** it returns `"check_orphans"` when `state.profile_exists` is true

#### Scenario: check_orphans routes by orphan count
- **WHEN** `check_orphans` is invoked
- **THEN** it returns `"create_story"` when `state.orphaned_skills` is
  non-empty
- **AND** it returns the END sentinel when `state.orphaned_skills` is empty
  or `None`

### Requirement: Profile graph cycle terminates
The cycle `create_story → compile_profile → check_orphans` SHALL terminate
when no orphaned skills remain. The skeleton implementation MUST NOT loop
indefinitely.

#### Scenario: Cycle drains orphan list and exits
- **WHEN** the graph starts with three orphaned skills and `create_story`
  removes one orphan per iteration in the no-op stub
- **THEN** the graph reaches END after exactly three `create_story` invocations
- **AND** `compile_profile` is invoked after each `create_story` invocation

### Requirement: Profile graph interrupts
The profile graph SHALL be compiled with `interrupt_after=["onboard",
"create_story"]`. No other nodes may interrupt.

#### Scenario: Graph pauses after onboard
- **WHEN** the profile graph is invoked from a state where `onboard` will run
- **THEN** the first `.invoke()` call returns control after `onboard` completes
- **AND** the next `.invoke(None, config)` call resumes at `compile_profile`

#### Scenario: Graph pauses after create_story
- **WHEN** the profile graph reaches `create_story`
- **THEN** the invocation returns control after `create_story` completes
- **AND** the next resume call routes back to `compile_profile`

### Requirement: Profile MCP tool surface
The system SHALL expose three MCP tools — `onboard_user`, `compile_profile`,
and `create_story` — each backed by the same profile graph. Each tool MUST
enter the graph at the node matching its name (or, in the case of
`onboard_user`, at `onboard`, bypassing the upstream `check_profile` router).

#### Scenario: onboard_user enters at onboard node
- **WHEN** the `onboard_user` MCP tool is called
- **THEN** the first node executed is `onboard`
- **AND** `check_profile` does NOT execute

#### Scenario: compile_profile enters at compile_profile node
- **WHEN** the `compile_profile` MCP tool is called
- **THEN** the first node executed is `compile_profile`

#### Scenario: create_story enters at create_story node
- **WHEN** the `create_story` MCP tool is called
- **THEN** the first node executed is `create_story`

### Requirement: Profile graph nodes are no-ops in this change
Every node implementation in the profile graph SHALL be a no-op stub that
logs its entry, writes sentinel placeholder values to its state fields, and
returns. The skeleton MUST NOT collect real user data, perform real
compilation, or perform real keyword extraction.

#### Scenario: onboard writes sentinel intake
- **WHEN** `onboard` runs
- **THEN** it writes a sentinel value to the state field that holds raw
  intake data
- **AND** does not raise

#### Scenario: compile_profile writes sentinel compiled record
- **WHEN** `compile_profile` runs
- **THEN** it writes a sentinel dict to the state field that holds the
  compiled profile
- **AND** writes a sentinel `orphaned_skills` list

### Requirement: Profile graph checkpointer separation
The profile graph SHALL use a SQLite checkpointer file at
`~/.local/share/pi-apply/profile-sessions.db`, distinct from the apply graph's
checkpointer.

#### Scenario: Profile graph DB file is distinct
- **WHEN** both graphs are built and used
- **THEN** the profile graph writes only to `profile-sessions.db`
- **AND** the apply graph writes only to `apply-sessions.db`
