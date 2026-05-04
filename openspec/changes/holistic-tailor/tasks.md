## 1. SectionMap Data Model

- [x] 1.1 Create `pi_apply/section_map.py` with `SectionMap`, `SkillsSection`, `ExperienceEntry`, `ProjectEntry`, `EducationEntry` Pydantic models mirroring go-apply's schema
- [x] 1.2 Add `context_line: str | None` to `ExperienceEntry` (V4 per-role context line)
- [x] 1.3 Implement `apply_edit(section_map, edit) -> EditResult` function handling summary, skills (flat + categorized), experience bullets, experience context lines, and project desc/bullets
- [x] 1.4 Implement `validate_edit_target(section_map, edit) -> str | None` that returns rejection reason or None
- [x] 1.5 Add `SectionMap` JSON serialization round-trip tests in `tests/test_section_map.py`
- [x] 1.6 Add `apply_edit` unit tests covering: valid summary replace, skills add (flat), skills replace (categorized), exp bullet replace, exp out-of-bounds rejection, project desc replace, non-editable section rejection

## 2. Profile Wiki Module

- [x] 2.1 Create `pi_apply/wiki.py` with `WikiStore` class: `wiki_root(resume_label)`, `write_index(resume_label, content)`, `write_experience_page(resume_label, company_slug, content)`, `read_index(resume_label) -> str | None`, `read_pages(resume_label, page_ids) -> dict[str, str]`
- [x] 2.2 Implement `company_slug(company_name) -> str` (lowercase, hyphenated, alphanumeric only)
- [x] 2.3 Add `get_wiki_pages` MCP tool in `server.py`: accepts `session_id`, `page_ids: list[str]`; loads wiki from profile store; returns `{status, pages: dict[str, str]}`
- [x] 2.4 Add unit tests for `WikiStore` in `tests/test_wiki.py`: read/write round-trip, missing page returns empty string, company_slug edge cases

## 3. Extractor — SectionMap Output

- [x] 3.1 Extend `pi_apply/extractor.py` with `extract_sections(text: str) -> SectionMap` that parses resume text into a structured SectionMap (use header detection from go-apply's `isHeaderLine` approach)
- [x] 3.2 Handle Skills section: detect flat vs categorized (colon-delimited categories)
- [x] 3.3 Handle Experience section: parse company/role/dates from headers; collect bullets under each entry
- [x] 3.4 Handle Projects section: parse name and description; collect bullets
- [x] 3.5 Handle Summary: capture text between header and next section
- [x] 3.6 Add `tests/test_extractor_sections.py` with a representative markdown resume fixture covering all five editable sections

## 4. Profile Graph — Onboarding + Compile

- [x] 4.1 Implement `onboard` node in `profile_nodes.py`: call `extract_sections` on the resume file, write `sections.json` to `profile-wiki/<resume_label>/`, store `resume_label` and `sections` in `ProfileState`
- [x] 4.2 Update `ProfileState` in `state.py`: add `resume_label: str | None`, `resume_path: str | None`, `sections: dict | None`, `wiki_path: str | None`
- [x] 4.3 Implement `compile_profile` node: returns `{status: needs_wiki_pages, sections, intake, resume_label}` for host to generate wiki pages (no LLM calls — design decision: wiki writing in MCP tool layer)
- [x] 4.4 `compile_profile` MCP tool: two-phase — phase 1 returns sections+intake, phase 2 accepts host-generated wiki_pages and writes via WikiStore
- [x] 4.5 Add `tests/test_profile_graph.py` cases for: sections written at onboarding, onboard raises without resume_path, compile_profile returns needs_wiki_pages, sections present in response

**Note:** `extract_sections` was added to `extractor.py` as part of M4 (M3 tasks were marked done in tasks.md but the function was absent from main — minimal implementation unblocks M4; full M3 coverage remains outstanding).

## 5. Apply Graph — parse_initial + score_initial

- [ ] 5.1 Update `parse_initial` node in `apply_nodes.py`: load `sections.json` from `profile-wiki/<resume_label>/`; if missing, return `next_action: "onboard_resume_first"` and halt; store `sections` in `ApplyState`
- [ ] 5.2 Update `ApplyState` in `state.py`: add `sections: dict | None`, `score_gap: dict | None`, `wiki_index: str | None`, `tailored_sections: dict | None`
- [ ] 5.3 Update `score_initial` node: compute `score_gap` (`required_missing`, `preferred_missing`) from `scorer.compute_score` output; store in `ApplyState`
- [ ] 5.4 Update `submit_keywords` response in `server.py`: include `sections`, `score_gap`, `wiki_index`, and `tailor_instructions` (V4 voice constraints string) in `data`; set `next_action: "fetch_wiki_then_tailor"` when wiki exists, else `"onboard_resume_first"`

## 6. Apply Graph — submit_tailor

- [ ] 6.1 Implement `tailor` node in `apply_nodes.py`: validate that `tailored_sections` has been injected; apply edits from `ApplyState.pending_edits` via `apply_edit`; collect `edits_applied`, `edits_rejected`, `uncovered_skills` (skills not echoed in any bullet); store `tailored_sections`
- [ ] 6.2 Add `pending_edits: list | None` to `ApplyState`
- [ ] 6.3 Implement `submit_tailor` MCP tool in `server.py`: validates `edits[]` input, injects `pending_edits` into graph state, resumes graph through `tailor` node; returns `{edits_applied, edits_rejected, uncovered_skills, score_final}`
- [ ] 6.4 Add `tests/test_apply_graph.py` cases: valid edits applied, out-of-bounds target rejected, non-editable section rejected, uncovered_skills populated correctly, session_not_found error

## 7. Render — SectionMap to Text

- [ ] 7.1 Implement `sections_to_text(section_map: SectionMap) -> str` in `section_map.py`: canonical section order (contact, summary, skills, experience, projects, education, certifications, awards); ATS-safe plain text (no markdown bold/italic in body)
- [ ] 7.2 Update `render` node to call `sections_to_text` on `tailored_sections` when available; fall back to `tailored` text blob if not
- [ ] 7.3 Add round-trip test: `SectionMap` → text → `extract_sections` recovers equivalent structure

## 8. Integration + Smoke

- [ ] 8.1 Update `scripts/smoke_apply.py` to exercise the full new flow: `load_jd` → `submit_keywords` (verify sections + wiki_index in response) → `get_wiki_pages` → `submit_tailor` (with sample edits) → assert `edits_applied` non-empty and `score_final > score_initial`
- [ ] 8.2 Add `tests/test_apply_e2e_tailor.py` integration test marked `@pytest.mark.integration`: full apply graph run with a fixture resume and fixture JDData, asserting score improvement after tailor
- [ ] 8.3 Run `uv run python scripts/check_spaghetti.py` and fix any new violations
