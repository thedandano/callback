# v2-noop-graph-skeleton — Design

## Context

The walking-skeleton graph (Epic 0, complete) is a single linear LangGraph
pipeline with `interrupt_after=["load_jd","score","tailor_t1","tailor_t2"]`.
The host LLM advances it one node per MCP tool call.

The architecture vision agreed on 2026-05-01 (see
`~/Library/Mobile Documents/com~apple~CloudDocs/obsidian-vault/the-scriptorium/wiki/projects/pi-apply-v2-vision.md`)
splits this into two graphs:

- **Profile Graph** — interactive, infrequent, has interrupts. Owns three MCP
  tools (`onboard_user`, `compile_profile`, `create_story`) backed by one
  graph that re-enters at different nodes per tool.
- **Apply Graph** — fully automated, runs once per JD, no interrupts. Owns one
  MCP tool (`apply`). The keystone is the `render → parse_final → score_final`
  round-trip that re-extracts text from the rendered PDF to prove tailoring
  survived ATS parsing.

This change replaces the existing single graph with both new graphs, but every
node is a no-op stub. Real implementations land in subsequent changes.

## Goals / Non-Goals

**Goals:**
- Both graphs compile and run end-to-end on empty/placeholder state.
- All edges (linear + conditional + cycle) wire correctly and are visited under
  the expected inputs.
- State models cover every field every node will eventually read or write.
- MCP surface is final: 1 apply tool + 3 profile tools. Tool names match the
  graph entry points they trigger.
- Tests exercise: graph compilation, edge routing under each conditional input,
  full end-to-end traversal, MCP tool round-trip with empty state.
- Deterministic — no randomness, no time-dependent behavior in stubs.

**Non-Goals:**
- No real LLM calls. `keywords_extract` and `tailor` log "stub" and pass through.
- No real HTTP fetching. `jd_fetch` accepts URL or text and returns whichever is
  set verbatim.
- No real parsing or scoring math. `parse_*` returns a placeholder string;
  `score_*` returns a fixed dict.
- No real PDF rendering. `render` writes a 0-byte placeholder file at the
  expected path so `parse_final` has something to read.
- No `trafilatura`, no Anthropic SDK, no new runtime dependencies.
- No migration of in-flight sessions from the old graph — the prior
  walking-skeleton session DB is invalidated.
- No CLI or installer changes (Epic 1 scope).

## Decisions

### D1 — Two graphs, not one with mixed interrupt config

**Choice:** Two `StateGraph` instances compiled separately, each with its own
checkpointer file or its own thread-id namespace.

**Alternatives considered:**
- *Single graph with `interrupt_after=["onboard","create_story"]` only.*
  LangGraph supports this — but every apply run would still pass through the
  `check_profile` router and any apply session would share a state model with
  unused profile fields. The profile-vs-apply concern leak is structural.
- *No graph for profile (just standalone Python functions called by MCP tools).*
  Loses the cycle representation for the orphan loop and the typed state
  benefits. Goes against the LangGraph portfolio angle.

**Rationale:** Clean separation matches `go-apply`'s shape. Per-JD apply state
is per-session and ephemeral; profile state is durable and cross-session.
Mixing them in one graph is conceptually wrong.

### D2 — Two named nodes (`parse_initial`, `parse_final`) instead of a cycle

**Choice:** Separate node names that bind to a shared implementation function,
parameterized on which input field to read and which output field to write.

**Alternatives considered:**
- *Cycle with iteration counter:* requires stateful node logic (the node reads
  `state.iteration`) and a router that decides loop-vs-exit. Iteration count is
  statically known to be exactly 2 — no benefit to the dynamic shape. State
  collision risk if both passes write to the same field.
- *Two fully separate implementations:* duplicates extraction logic. Rejected.

**Rationale:** Static iteration count → unroll. Two names also make the trace
self-documenting (`parse_initial` ≠ `parse_final` semantically) and keep the
state model flat.

### D3 — Cycle in profile graph IS used, deliberately

**Choice:** `create_story → compile_profile` is a real cycle edge.

**Rationale:** Orphan count is dynamic (0..N at runtime). Unrolling N times
would require knowing N at design time. Cycle with conditional exit
(`check_orphans → END` when count = 0) is the natural shape.

### D4 — `ProfileState` is separate from `ApplyState`

**Choice:** Two Pydantic models, neither inherits from the other.

**Rationale:** They have different lifecycles. `ApplyState` is per-session (one
JD application). `ProfileState` is durable user data flushed to disk by
`compile_profile`. Apply nodes that need profile data read it from disk, not
from in-memory state. This avoids cross-graph state coupling.

### D5 — No-op nodes return placeholder values, not empty dicts

**Choice:** Each stub explicitly writes a sentinel value (e.g. `parsed_initial =
"<noop:parse_initial>"`, `score_initial = {"total": 0, "stub": True}`).

**Alternatives considered:**
- *Return `{}` and rely on `Optional` field defaults.* Then downstream nodes
  can't tell "the prior node ran and produced nothing" from "the prior node
  didn't run". Skeleton tests need to verify each node executed.

**Rationale:** Sentinel values let tests assert on the trace ("did
`parse_initial` actually run?") and make debug logs immediately readable.
Real implementations replace the sentinels with real values.

### D6 — `render` no-op writes a real (empty) file

**Choice:** Even as a no-op, `render` creates the file at `pdf_path` so
`parse_final` has a real path to read from.

**Rationale:** The keystone round-trip is end-to-end real-file I/O. If `render`
returns a path that doesn't exist, `parse_final` fails or has to special-case
the no-op state. Keeping the file write contract intact keeps the I/O shape
identical between stub and real implementations.

### D7 — MCP tool surface

**Choice:** 4 tools total.

| Tool | Graph | Entry node |
|---|---|---|
| `apply` | apply | `jd_fetch` |
| `onboard_user` | profile | `onboard` (skips `check_profile` router) |
| `compile_profile` | profile | `compile_profile` |
| `create_story` | profile | `create_story` |

**Rationale:** Each profile tool re-enters the graph at the relevant node.
`apply` runs the apply graph straight through to END. No legacy workflow tools
remain.

### D8 — Checkpointer path

**Choice:** Two SQLite files —
`~/.local/share/pi-apply/apply-sessions.db` and
`~/.local/share/pi-apply/profile-sessions.db`.

**Alternatives considered:**
- Single file with separate thread-id namespaces.

**Rationale:** Cleaner separation; one graph's session schema can evolve
without touching the other's DB. Either-or — if one-file works simpler in
practice during stubbing, can revisit.

## Risks / Trade-offs

- **[Risk]** Skeleton passes tests but real fill-ins reveal field-shape
  mismatches between nodes. → **Mitigation:** State model PR-reviewed before
  any node fills go in. Field types are concrete (e.g. `score_initial: dict`,
  not `Any`).
- **[Risk]** No-op `render` writes a 0-byte file that `parse_final` can't open.
  → **Mitigation:** `parse_final` no-op short-circuits when the file exists but
  is empty, returning a sentinel string. Real `parse_final` will use
  `pdfplumber` and require a valid PDF.
- **[Risk]** Cycle in profile graph creates infinite loops if `check_orphans`
  router has a bug. → **Mitigation:** Add a max-iteration guard in
  `check_orphans` (e.g., 10 orphans max per session) for the skeleton; revisit
  for real impl.
- **[Risk]** Tool surface change breaks the existing `/apply` slash command.
  → **Mitigation:** Update `.claude/commands/apply.md` in the same change to
  drive the new single `apply` tool.
- **[Trade-off]** Two checkpointer files add slight operational overhead vs.
  one. Worth it for the clean separation.
- **[Trade-off]** Sentinel-value stubs are "ugly" but make trace inspection
  trivial. Acceptable for skeleton phase only.

## Migration Plan

This is a breaking change with no data to migrate.

1. Land `state.py` first (both models, all fields). Tests pass on imports.
2. Land profile graph (graph.py additions, profile nodes as no-ops, profile
   tests).
3. Land apply graph (replaces current graph wiring, apply nodes as no-ops,
   apply tests).
4. Land server.py rewrite (4 tools, drops the old 5).
5. Update `.claude/commands/apply.md` for the new tool surface.
6. Delete obsolete tests; update `tests/test_state.py`, `tests/test_server.py`.

**Rollback:** Revert the change. The walking-skeleton tag (Epic 0 complete) is
the rollback point. Existing user installs won't auto-update; their old
sessions DB stays valid against the old code.

## Open Questions

- Will `compile_profile` MCP tool re-enter the profile graph at `compile_profile`
  even when `check_profile` would have routed elsewhere? **Decision:** yes,
  each profile tool maps to a graph entry node directly, bypassing the upstream
  router. This is documented in D7.
- Do we keep `bridge.py`'s `run_pdfrender` wired (currently unused)? **Decision:**
  leave `bridge.py` as-is. No-op `render` uses neither. Cleanup belongs to a
  separate change.
- Should the no-op nodes write structured logs in the same JSON shape as the
  current nodes? **Decision:** yes — same `_log_enter` helper, carries the
  observability contract forward unchanged.
