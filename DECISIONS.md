# Architectural Decisions — pi-apply

Context: This document captures the key decisions made during the go-apply architectural review session (2026-04-30) that shape the pi-apply design.

---

## What pi-apply is

A Python MCP server that replaces the Go MCP server (go-apply). LangGraph owns the workflow state and orchestration. Claude remains the user-facing interface — nothing changes about how it's used day-to-day.

```
Claude (interface, same as today)
  → Python MCP server  ← new, built with LangGraph
      → LangGraph state graph owns workflow state
      → Go subprocess: pdfrender  (kept — fpdf is the right tool)
      → Go subprocess: survival   (kept — pure function, already works)
```

---

## What moves to Python

| Component | Why |
|---|---|
| FSM / session state | LangGraph's checkpointer IS this — keeping both is duplication |
| Scorer | Trivial port; weights are already JSON |
| Profile compiler | Pure assembler, easier to evolve alongside the agent |
| Loader / dispatcher | pypdf, python-docx, unstructured are better Python options |
| Fetcher (JD scraping) | Playwright > chromedp for solo maintenance |

## What stays in Go (as subprocess binaries)

| Component | Why |
|---|---|
| survival diff | Pure function, already works, no reason to rewrite |

**pdfrender correction (discovered during POC):** go-apply's PDF renderer is an internal Go service, not a CLI subprocess. It cannot be called as `go-apply pdfrender`. PDF rendering was implemented directly in Python using `fpdf2` instead. The Go bridge (`bridge.py`) exposes `run_pdfrender` for future use but it is not wired in the current implementation.

---

## Key decisions

### LangGraph as the orchestrator, not a wrapper
LangGraph must own meaningful work — not just proxy calls to Go binaries. The FSM, session state, and workflow transitions live in LangGraph. If LangGraph is a thin wrapper, the portfolio story inverts (Go does the work, Python does nothing).

### MCP is the portability layer
One interface: MCP server. Any harness that speaks MCP (Claude, Hermes) works without a second interface. No TUI, no headless CLI, no REST API. The protocol handles portability.

### State owner: client
LangGraph checkpointer persists to local disk. One user, one machine, no coordination. This is client state — not server state. A shared service was considered and rejected: no multi-user requirement.

### No CGo / ctypes
CGo shared library was considered and rejected. No sub-millisecond hot path. PDF rendering is not latency-sensitive. Subprocess is cleaner, testable, debuggable.

### Scope discipline
The differentiator is learning, not a new product capability. Any feature beyond "makes the LangGraph graph run end-to-end" is out of scope until the walking skeleton works. pgvector, LLM-as-judge, and eval harness are deferred.

---

## Walking skeleton (smallest proof)

A LangGraph state graph that:
1. Ingests a job description and resume
2. Passes through the workflow steps (load_jd → score → tailor_t1 → tailor_t2 → finalize)
3. Logs each node transition
4. Calls Go subprocess binaries for PDF rendering and survival diff
5. Produces a tailored resume at the end

If this runs clean, LangGraph can replace the Go FSM. Build this first.

---

## 90-day positioning plan (from recruiter review, 2026-04-30)

- **Days 1–30:** Walking skeleton. LangGraph state graph running end-to-end, LangSmith tracing wired, Pydantic-typed tool layer.
- **Days 31–60:** Add AI-eng signal — embeddings for skill matching, LLM-as-judge eval for tailoring quality, RAG over accomplishments store. Write one blog post: "Why I rebuilt my Go MCP server on LangGraph."
- **Days 61–90:** Apply. Go repo stays public as v1. Python repo is the headline. The rewrite is the interview story.

---

## Interview narrative

"I designed a Go MCP server to learn the protocol and FSM design mechanically. Once I understood the architecture, I rebuilt the orchestration layer in Python on LangGraph — because that's where the eval tooling, observability, and hiring market live. The Go pdfrender and survival diff stay as subprocess tools where fpdf remains the right fit. The MCP tool surface is unchanged, so Claude can still drive it exactly as before."
