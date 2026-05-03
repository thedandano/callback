# graph-state-models Specification

## Purpose

Specify the Pydantic state models (`ApplyState` and `ProfileState`) that represent the
complete, immutable per-session state for both the apply and profile graphs. These models
define the contract between graph nodes and ensure type safety throughout the workflow.
## Requirements
### Requirement: ApplyState Pydantic model
The system SHALL provide a Pydantic `ApplyState` model that represents the
complete per-session state for the apply graph. The model MUST include the
following fields with the listed types:

- `session_id: str` (required)
- `jd_url: str | None`
- `jd_raw_text: str | None`
- `jd_text: str | None`
- `keywords: dict | None`
- `resume_path: str | None`
- `resume_label: str | None`
- `parsed_initial: str | None`
- `parsed_final: str | None`
- `score_initial: dict | None`
- `score_final: dict | None`
- `tailored: str | None`
- `pdf_path: str | None`
- `report: dict | None`
- `uncovered_skills: list | None`
- `finalized: bool | None`
- `error: str | None`

#### Scenario: Model accepts only session_id
- **WHEN** `ApplyState(session_id="abc")` is constructed
- **THEN** every other field defaults to `None`
- **AND** the model validates without raising

#### Scenario: Model rejects missing session_id
- **WHEN** `ApplyState()` is constructed without `session_id`
- **THEN** Pydantic raises a validation error

### Requirement: ProfileState Pydantic model
The system SHALL provide a Pydantic `ProfileState` model representing the
complete state for the profile graph, separate from `ApplyState`. The model
MUST include the following fields:

- `session_id: str` (required)
- `profile_exists: bool | None`
- `intake: dict | None` — raw onboarding data
- `compiled_profile: dict | None` — compiled skill→story graph
- `orphaned_skills: list | None`
- `current_story_target: str | None` — which orphan `create_story` is handling
- `error: str | None`

#### Scenario: Model accepts only session_id
- **WHEN** `ProfileState(session_id="xyz")` is constructed
- **THEN** every other field defaults to `None`
- **AND** the model validates without raising

#### Scenario: Models are independent classes
- **WHEN** both models are imported
- **THEN** `ApplyState` and `ProfileState` are distinct Python classes
- **AND** neither inherits from the other

### Requirement: Removal of legacy state fields
The system SHALL remove the legacy `ApplyState` fields used by the
walking-skeleton graph: `resume_content`, `scored_resumes`, `tailored_t1`,
`tailored_t2`, `edits_t1`, and `edits_t2`.

#### Scenario: Legacy fields are absent
- **WHEN** the new `ApplyState` is inspected
- **THEN** none of the listed legacy field names are defined on the model

