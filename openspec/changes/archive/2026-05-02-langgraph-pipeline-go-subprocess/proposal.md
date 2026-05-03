## Why

go-apply implements the apply workflow as a Go FSM inside an MCP server. pi-apply replaces that FSM with a LangGraph state graph in Python — making the orchestration layer defensible in an AI engineering interview and putting observable, traceable stateful agent design on the portfolio. The Go FSM cannot provide that signal; the rewrite can.

## What Changes

- **New**: Python MCP server (`pi-apply`) exposing the same 12-tool surface as go-apply
- **New**: LangGraph state graph owning the full apply workflow: `load_jd → score → tailor_t1 → tailor_t2 → finalize`, compiled with `interrupt_after` so each MCP tool call advances exactly one node
- **New**: Go subprocess bridge — thin Python wrappers that shell out to the go-apply binaries for `pdfrender` and `survival` diff, which stay in Go
- **New**: Disk-backed LangGraph checkpointer (`SqliteSaver`) for session persistence (replaces go-apply's `SessionStore`)
- **Removed**: Go FSM, Go session store, Go service layer — all replaced by LangGraph nodes
- All MCP tool names and argument schemas remain unchanged (Claude drives the same surface)
- **Walking skeleton scope**: `load_jd` accepts `jd_raw_text` only; Playwright URL fetching and PDF/docx parsing are deferred until the graph runs end-to-end

## Capabilities

### New Capabilities
- `langgraph-workflow`: LangGraph state graph with one node per workflow stage (`load_jd`, `score`, `tailor_t1`, `tailor_t2`, `finalize`), typed state via Pydantic, disk-backed checkpointer
- `go-subprocess-bridge`: Python caller that invokes go-apply subprocess binaries (`pdfrender`, `survival`) via `subprocess.run`, captures stdout/stderr, and raises on non-zero exit
- `mcp-server`: Python MCP server (`fastmcp` or `mcp` SDK) wiring each workflow stage to a named MCP tool, preserving go-apply's tool surface

### Modified Capabilities
<!-- none — pi-apply starts fresh with no existing specs -->

## Impact

- **New project**: pi-apply is a net-new Python repo; nothing in go-apply is modified
- **Runtime dependency**: go-apply binary must be on `PATH` (or configured via env var) for the subprocess bridge; pdfrender and survival diff are not re-implemented
- **Dependencies (walking skeleton)**: `langgraph`, `langchain-core`, `pydantic`, `fastmcp`; `pypdf`, `python-docx`, `playwright` deferred post-skeleton
- **Checkpointer storage**: `~/.local/share/pi-apply/sessions/` (mirrors go-apply's `DataDir` convention)
- **No multi-user, no API key**: single-user client state; LLM inference is the host agent (Claude), not pi-apply
