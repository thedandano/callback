## Context

go-apply is a Go MCP server that owns the full apply workflow. pi-apply replaces the Go FSM and session layer with a LangGraph state graph while keeping the go-apply binaries for PDF rendering (`pdfrender`) and survival diff. The goal is a defensible LangGraph portfolio artifact with unchanged MCP tool surface.

Current state: empty repo, no existing Python code, no existing specs.

Constraints from DECISIONS.md and BRIEF.md:
- Walking skeleton first: no pgvector, no LLM-as-judge, no eval harness until the graph runs end-to-end
- One interface: MCP server only (no REST, no TUI, no headless CLI)
- Single user, local disk state — no coordination, no server state
- No CGo / ctypes — subprocess only for Go binaries

## Goals / Non-Goals

**Goals:**
- Python MCP server with the same tool names and argument schemas as go-apply (12 tools)
- LangGraph state graph with one node per workflow stage (load_jd, score, tailor_t1, tailor_t2, finalize)
- Pydantic-typed workflow state shared across all nodes
- Disk-backed LangGraph checkpointer (SqliteSaver) for session persistence across MCP calls
- Go subprocess bridge for pdfrender and survival binaries
- Structured logging at every node transition

**Non-Goals:**
- Playwright URL fetching and pypdf/python-docx document parsing — deferred post-skeleton; `load_jd` accepts `jd_raw_text` only in the walking skeleton
- PDF render via bridge in `tailor_t2` — deferred post-skeleton
- pgvector, embeddings, LLM-as-judge, RAG — deferred to Days 31-60
- LangSmith tracing wiring — deferred (walking skeleton first)
- Multi-user support, server state, coordination
- TUI, REST API, or any second interface

## Decisions

### LangGraph interrupt_after for MCP tool routing
The graph is compiled with `interrupt_after=["load_jd","score","tailor_t1","tailor_t2"]`. Each MCP tool call from Claude advances the graph exactly one node:
1. `load_jd` tool → `graph.invoke(initial_state, config)` — graph runs `load_jd`, then interrupts
2. `submit_keywords` tool → `graph.update_state(config, {"keywords": jd_json})` then `graph.invoke(None, config)` — resumes at `score`, then interrupts
3. `submit_tailor_t1` → `update_state(config, {"edits_t1": edits})` then `invoke(None, config)` — resumes at `tailor_t1`
4. `submit_tailor_t2` → `update_state(config, {"edits_t2": edits})` then `invoke(None, config)` — resumes at `tailor_t2`
5. `finalize` → `invoke(None, config)` — resumes at `finalize`, graph runs to END

This pattern reuses LangGraph's human-in-the-loop interrupt mechanism. `update_state` injects Claude's edits into the checkpoint before resuming — no re-running of prior nodes.

**Alternative rejected**: Per-tool minimal subgraphs sharing the same checkpoint. Rejected: more complex, harder to trace, no benefit for this single-user workflow.

### session_id = thread_id
`load_jd` mints a UUID v4 as `session_id` and returns it in the response envelope. Every subsequent workflow tool requires `session_id` as a mandatory argument. `thread_id = session_id` is passed on every graph call as `RunnableConfig({"configurable": {"thread_id": session_id}})`. This is the only key SqliteSaver uses to namespace checkpoints.

**Alternative rejected**: "default singleton" session. Rejected: masks the contract; breaks if two Claude sessions overlap.

### Tool-to-node mapping
| MCP tool | Graph node | Pattern |
|---|---|---|
| `load_jd` | `load_jd` | invoke from START |
| `submit_keywords` | `score` | update_state + invoke |
| `submit_tailor_t1` | `tailor_t1` | update_state + invoke |
| `submit_tailor_t2` | `tailor_t2` | update_state + invoke |
| `finalize` | `finalize` | invoke (runs to END) |
| `onboard_user` | — | bypass graph, data layer |
| `add_resume` | — | bypass graph, data layer |
| `get_config` | — | bypass graph, config |
| `update_config` | — | bypass graph, config |
| `compile_profile` | — | bypass graph, data layer |
| `create_story` | — | bypass graph, data layer |
| `preview_ats_extraction` | — | bypass graph, reads state |

Non-workflow tools bypass the graph entirely — no `invoke`, no `update_state`, no checkpoint write.

### Response envelope (matches go-apply exactly)
Every tool returns a JSON-encoded text result (not a plain Python object). Schema:
```json
{
  "session_id": "string (omitempty)",
  "status": "ok | needs_input | error",
  "next_action": "string (omitempty)",
  "data": "any (omitempty)",
  "error": {
    "stage": "string",
    "code": "string",
    "message": "string",
    "retriable": "bool"
  },
  "warnings": []
}
```
`next_action` values must match go-apply exactly: `"extract_keywords"`, `"tailor_t1"`, `"tailor_t2"`, `"finalize"`.

### SqliteSaver as checkpointer
LangGraph's `SqliteSaver` persists state to `~/.local/share/pi-apply/sessions.db`. The parent directory is created at startup with `mkdir(parents=True, exist_ok=True)` before SqliteSaver opens the file. Sessions are namespaced by `thread_id` (= `session_id`).

**Alternative rejected**: InMemorySaver. Rejected because it loses state on MCP server restart.

### Subprocess bridge as a thin isolated module
`bridge.py` is the only file that knows about the go-apply binary path. Resolution runs at module top level (imported once at server startup): `GO_APPLY_BIN` env var first, then `shutil.which("go-apply")`, then `EnvironmentError`. The server imports `bridge` at top level — fail-fast on startup, not on first use.

**Alternative rejected**: ctypes shared library. Rejected per DECISIONS.md — no sub-millisecond hot path.

### MCP server: `fastmcp`
Decorator-based tool registration (`@mcp.tool()`) keeps boilerplate minimal. Each workflow tool follows the update_state + invoke pattern; each non-workflow tool delegates directly to the data/config layer.

### Deterministic test stub mode
`PI_APPLY_TEST_STUB=1` env flag makes tailor nodes return canned output. Nodes accept an optional `tailor_fn` callable (default: real implementation; test: canned stub). This seam allows `pytest` to run the full pipeline without a live LLM.

## Risks / Trade-offs

- **go-apply binary not on PATH** → Mitigation: fail at startup with `EnvironmentError` pointing to `GO_APPLY_BIN` env var
- **Checkpointer schema drift** (LangGraph version bump changes SqliteSaver schema) → Mitigation: pin LangGraph version in `pyproject.toml`
- **Walking skeleton scope creep** (Playwright, PDF parsing, pdfrender bridge) → Mitigation: explicitly deferred in Non-Goals; `load_jd` accepts `jd_raw_text` only until skeleton is proven

## Migration Plan

1. Build pi-apply as a new repo — go-apply is unchanged
2. Register pi-apply as the MCP server in Claude Code settings (replaces go-apply entry)
3. Verify same tool surface works end-to-end with Claude
4. Rollback: re-point MCP settings to go-apply binary — no data migration needed

## Open Questions

- Which `fastmcp` version? Resolve at `uv add` time; pin in `pyproject.toml`.
