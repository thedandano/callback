# accomplishments-repository Specification

## Purpose

Persist `CreatedStory` records and raw onboarding accomplishments text to
`~/.local/share/callback/accomplishments.json`. Provides save, retrieve, and
list operations with stable sequential slug IDs and atomic writes.

## Requirements

### Requirement: CreatedStory schema stored in accomplishments.json
The system SHALL persist `CreatedStory` records to `~/.local/share/callback/accomplishments.json` with the following fields: `id` (slug, e.g. `"story-001"`), `primary_skill` (str), `skills` (list[str]), `story_type` (str), `job_title` (str), `situation` (str), `behavior` (str), `impact` (str). The file SHALL include a top-level `schema_version: "1"` field and an `onboard_text` field for raw onboarding accomplishments text.

#### Scenario: Story saved with all fields and correct schema_version
- **WHEN** `save_story(story)` is called with a fully populated `CreatedStory`
- **THEN** the story is appended to `accomplishments.json`
- **AND** the file contains `"schema_version": "1"` at the top level
- **AND** the saved record contains all fields: `id`, `primary_skill`, `skills`, `situation`, `behavior`, `impact`, `story_type`, `job_title`

### Requirement: Story IDs assigned as sequential slugs
The system SHALL assign story IDs as zero-padded sequential slugs: `"story-001"`, `"story-002"`, etc. The next ID SHALL be derived from the current count of stories in `accomplishments.json` plus one. IDs SHALL be stable — once assigned, an ID is never reassigned.

#### Scenario: First story receives id story-001
- **WHEN** `save_story` is called on an empty `accomplishments.json`
- **THEN** the saved story has `"id": "story-001"`

#### Scenario: Subsequent stories receive sequential IDs
- **WHEN** `accomplishments.json` already contains two stories and `save_story` is called
- **THEN** the new story has `"id": "story-003"`

### Requirement: Stories retrieved individually and as a list
The system SHALL provide `get_story(id: str) -> CreatedStory` and `list_stories() -> list[CreatedStory]`. `get_story` SHALL raise `StoryNotFoundError` if the ID does not exist.

#### Scenario: Round-trip save and retrieve by ID
- **WHEN** a story is saved via `save_story` and then fetched via `get_story(story.id)`
- **THEN** the returned story matches the saved record field-for-field

#### Scenario: list_stories returns all saved stories
- **WHEN** three stories have been saved
- **THEN** `list_stories()` returns a list of three `CreatedStory` objects

#### Scenario: get_story raises on unknown ID
- **WHEN** `get_story("story-999")` is called and that ID does not exist
- **THEN** `StoryNotFoundError` is raised

### Requirement: Onboard text stored alongside created stories
The system SHALL store raw onboarding accomplishments text in `accomplishments.json` under the `onboard_text` field. This field is written by `onboard_user` and is distinct from `created_stories`.

#### Scenario: onboard_text persisted and readable
- **WHEN** `save_onboard_text("- Led a team of 5 engineers...")` is called
- **THEN** `accomplishments.json` contains `"onboard_text"` with the provided text
- **AND** existing `created_stories` are preserved unchanged

### Requirement: accomplishments.json written atomically
The system SHALL write `accomplishments.json` via a temp-file-then-rename pattern to prevent partial writes.

#### Scenario: File is valid JSON after concurrent write
- **WHEN** `save_story` completes without error
- **THEN** `accomplishments.json` is valid JSON readable by `json.loads`
