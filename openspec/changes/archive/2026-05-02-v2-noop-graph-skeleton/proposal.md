# v2-noop-graph-skeleton

## Why

The walking-skeleton graph (5 linear nodes with interrupts) needs to be replaced
with the v2 two-graph topology agreed in the architecture vision: an interactive
**Profile Graph** (5 nodes, with interrupts) and an automated **Apply Graph**
(10 nodes, no interrupts) — including the keystone `render → parse_final →
score_final` round-trip that proves tailoring survived ATS parsing.

Stubbing all nodes as no-ops first lets us validate graph topology, edge wiring,
conditional routing, state model, and MCP boundaries in isolation — before any
LLM calls, scoring logic, or rendering work lands. Vertical-slice discipline:
build the skeleton, prove it compiles and runs end-to-end with empty data, then
fill nodes one at a time in subsequent changes.

## What Changes

- **BREAKING**: Replace single-graph topology (`load_jd → extract → score →
  tailor_t1 → tailor_t2 → finalize`) with two separate LangGraph graphs.
- **BREAKING**: Collapse `tailor_t1` + `tailor_t2` into a single `tailor` node.
- **BREAKING**: Remove the four `interrupt_after` points from the apply pipeline
  (`load_jd`, `score`, `tailor_t1`, `tailor_t2`). Apply graph runs end-to-end.
- **BREAKING**: Collapse the five workflow MCP tools (`load_jd`,
  `submit_keywords`, `submit_tailor_t1`, `submit_tailor_t2`, `finalize`) into a
  single `apply` MCP tool that runs the apply graph straight through.
- Add **Apply Graph**: 10 nodes wired linearly — `jd_fetch → keywords_extract →
  parse_initial → score_initial → tailor → render → parse_final → score_final →
  report → finalize`.
- Add **Profile Graph**: 5 nodes with conditional routing — `check_profile →
  {onboard | check_orphans} → compile_profile → check_orphans → {create_story |
  END}` with a cycle from `create_story` back to `compile_profile`.
- Add three profile MCP tools: `onboard_user`, `compile_profile`, `create_story`
  — each enters the profile graph at the appropriate point.
- Extend `ApplyState` with new fields: `parsed_initial`, `parsed_final`,
  `score_initial`, `score_final`, `tailored`, `report`, `uncovered_skills`.
- Introduce `ProfileState` Pydantic model for the profile graph (separate from
  `ApplyState`).
- All node implementations are **no-ops**: each logs entry, passes through
  required state fields with placeholder values, and returns. No LLM calls,
  no real parsing, no real scoring, no real rendering.
- Both graphs compile, persist via `SqliteSaver`, and run end-to-end on empty
  state without errors.
- Add a `pre-commit` framework configuration with a local hook that runs the
  `ai-slop-score` CLI against the repo and reports the score and band on
  every commit. The hook ships with `pre-commit` as a dev dependency and a
  small wrapper script. **Threshold calibration (i.e. the binding "must
  be low" gate) is deferred** to a follow-up change once real
  implementations replace the no-op sentinel strings — those currently
  saturate the `magic_literals` metric and skew the score in a way that
  isn't representative of finished code.

## Capabilities

### New Capabilities

- `apply-graph`: The automated apply pipeline graph — 10 nodes, no interrupts,
  drives a JD-to-archived-application flow. Owns the `apply` MCP tool surface
  and the `ApplyState` shape.
- `profile-graph`: The interactive profile graph — 5 nodes with two routers, two
  interrupts, and a cycle. Owns the three profile MCP tools (`onboard_user`,
  `compile_profile`, `create_story`) and the `ProfileState` shape.
- `graph-state-models`: Typed Pydantic state models for both graphs, defining
  the field-level contract every node reads from and writes to.
- `quality-gates`: Local pre-commit hook that runs `ai-slop-score` and
  blocks commits whose band is not `low`. Owns the wrapper script,
  `.pre-commit-config.yaml`, and the threshold contract.

### Modified Capabilities

<!-- None — `openspec/specs/` is empty (greenfield post-skeleton). -->

## Impact

- **Replaces**: `pi_apply/nodes.py`, `pi_apply/graph.py`, `pi_apply/state.py`,
  `pi_apply/server.py` workflow tools.
- **Tests**: replaces `tests/test_graph.py` and `tests/test_nodes.py`; updates
  `tests/test_server.py` for new tool surface and `tests/test_state.py` for new
  fields and the second state model.
- **Carries forward unchanged**: `pi_apply/scorer.py`, `pi_apply/extractor.py`,
  `pi_apply/bridge.py` — nodes will call into them once no-ops are filled in.
- **MCP host integration**: the `/apply` slash command and `~/.claude.json` MCP
  config will continue to work; tool names change, surface narrows.
- **No new runtime dependencies** in this change. `trafilatura` and any LLM
  client land later when the no-ops are filled.
- **Storage**: SQLite checkpointer path unchanged
  (`~/.local/share/pi-apply/sessions.db`), but the graph schema persisted there
  changes — any prior in-flight session is invalidated by this change.
