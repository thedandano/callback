# jd-keyword-contract Specification

## Purpose

Define the contract by which `callback` accepts host-extracted JD keyword data
(JDData). This capability establishes that JD keyword reasoning is owned by the
host (the LLM in the calling MCP client), not by `callback` itself, and
specifies the JDData shape, validation rules, and handoff protocol used by
`load_jd` and `submit_keywords`.

## Requirements

### Requirement: Host-owned JD keyword extraction
The system SHALL treat keyword extraction as host-owned reasoning. `callback` MUST NOT infer, paraphrase, rank, or generate JD keywords internally during the keyword handoff.

#### Scenario: load_jd returns extraction instructions
- **WHEN** `load_jd` succeeds
- **THEN** the response data includes `jd_text`
- **AND** the response data includes `extraction_protocol`
- **AND** `next_action` is `"extract_keywords"`

#### Scenario: keyword acceptance does not extract
- **WHEN** `submit_keywords` is called
- **THEN** the system validates and stores the host-provided JDData
- **AND** the system does not inspect `jd_text` to infer additional keywords

### Requirement: JDData contract
The system SHALL accept host-provided JDData using this JSON-compatible contract: `title`, `company`, `required`, `preferred`, `location`, `seniority`, `required_years`, `team`, `key_responsibilities`, `pay_range_min`, and `pay_range_max`.

#### Scenario: Full JDData payload accepted
- **WHEN** `submit_keywords` receives valid JSON containing every JDData field
- **THEN** the response has `status="ok"`
- **AND** the stored `keywords` data preserves those fields with their values

#### Scenario: Optional fields may be omitted
- **WHEN** `submit_keywords` receives valid JSON with only `title`, `company`, and `required`
- **THEN** the response has `status="ok"`
- **AND** omitted optional fields do not require invented values

### Requirement: JDData validation
The system SHALL reject invalid JDData before storing it. The system MUST reject malformed JSON, non-list `required`, non-list `preferred`, non-list `key_responsibilities`, unsupported `seniority`, and JDData with no title, company, required keywords, or preferred keywords. If `seniority` is omitted or empty, the system SHALL default it to `"mid"`.

#### Scenario: Malformed JSON rejected
- **WHEN** `submit_keywords` receives a `jd_json` string that cannot be parsed as JSON
- **THEN** the response has `status="error"`
- **AND** the error code is `"invalid_jd"`

#### Scenario: Empty JDData rejected
- **WHEN** `submit_keywords` receives `{}` or an equivalent payload with no title, company, required keywords, or preferred keywords
- **THEN** the response has `status="error"`
- **AND** the error code is `"jd_empty"`

#### Scenario: Missing seniority defaults to mid
- **WHEN** `submit_keywords` receives otherwise valid JDData without `seniority`
- **THEN** the stored `keywords.seniority` value is `"mid"`

### Requirement: submit_keywords response includes sections, score_gap, wiki_index, and orphaned_required
The system SHALL extend the `submit_keywords` success response to include four additional fields in `data`: `sections` (the loaded SectionMap as a JSON object, keyed by section name), `score_gap` (an object with `required_missing: list[str]` and `preferred_missing: list[str]` computed from the initial score against the submitted JDData), `wiki_index` (the full markdown content of `index.md` for the session's `resume_label`, or null if no wiki exists), and `orphaned_required` (a list of required keywords that appear in the candidate's SectionMap skills but have no corresponding story page in the wiki). The existing fields (`session_id`, `status`, `next_action`) are unchanged. When `orphaned_required` is non-empty, `next_action` MUST be `"add_story_first"`. When `wiki_index` is null, `next_action` MUST be `"onboard_resume_first"`. Otherwise `next_action` MUST be `"fetch_wiki_then_tailor"`.

#### Scenario: Extended response returned on success with full coverage
- **WHEN** `submit_keywords` receives valid JDData and sections exist for the resume_label
- **THEN** `data.sections` is a non-null JSON object with at least `experience` and `skills` keys
- **AND** `data.score_gap.required_missing` is a list (possibly empty) of uncovered required keywords
- **AND** `data.score_gap.preferred_missing` is a list (possibly empty) of uncovered preferred keywords
- **AND** `data.wiki_index` is a non-empty markdown string
- **AND** `data.orphaned_required` is an empty list
- **AND** `next_action` is `"fetch_wiki_then_tailor"`

#### Scenario: orphaned_required populated when skill exists but has no story
- **WHEN** `submit_keywords` receives JDData requiring ["Go", "Kafka"] and the resume covers "Go" but not "Kafka", and "Kafka" appears in the SectionMap skills but has no wiki story page
- **THEN** `data.orphaned_required` contains `"Kafka"`
- **AND** `next_action` is `"add_story_first"`

#### Scenario: genuine gap not flagged as orphan
- **WHEN** `submit_keywords` receives a required keyword that does not appear in the SectionMap skills AND has no wiki story page
- **THEN** that keyword appears in `data.score_gap.required_missing`
- **AND** that keyword does NOT appear in `data.orphaned_required`

#### Scenario: wiki_index is null when no wiki exists
- **WHEN** `submit_keywords` succeeds but no wiki has been generated for the resume_label
- **THEN** `data.wiki_index` is null
- **AND** `data.orphaned_required` is an empty list or absent
- **AND** `next_action` is `"onboard_resume_first"` rather than `"fetch_wiki_then_tailor"`

#### Scenario: score_gap reflects initial scoring
- **WHEN** `submit_keywords` receives JDData requiring ["Go", "Kubernetes", "gRPC"] and the resume covers "Go" and "Kubernetes" but not "gRPC"
- **THEN** `data.score_gap.required_missing` contains `"gRPC"`
- **AND** `data.score_gap.required_missing` does NOT contain `"Go"` or `"Kubernetes"`

### Requirement: Sections delivered to host before tailor
The system SHALL include the loaded `SectionMap` (serialized as JSON) in the `submit_keywords` response under the `sections` field, alongside `score_gap` and `wiki_index`. This gives the host complete context — section structure, keyword gaps, and wiki navigation — in a single response before tailor reasoning begins.

#### Scenario: sections included in submit_keywords response
- **WHEN** `submit_keywords` succeeds and sections exist for the resume_label
- **THEN** response `data.sections` is a non-null JSON object
- **AND** `data.sections.experience` is a non-empty list
- **AND** `data.score_gap.required_missing` is a list of keyword strings not covered by the initial resume

#### Scenario: score_gap correctly identifies missing required keywords
- **WHEN** a resume covers 3 of 5 required keywords
- **THEN** `data.score_gap.required_missing` contains exactly the 2 uncovered keywords
- **AND** `data.score_gap.preferred_missing` contains uncovered preferred keywords
