# Project Charter — callback v2 (Python LangGraph MCP Server)

This brief records the original project intent. For day-to-day agent guidance,
use `AGENTS.md`; it contains the current architecture pattern, commands, module
map, and change discipline.

**Differentiator:** LangGraph experience on a non-trivial, real-world stateful agent workflow — a concrete portfolio talking point about agent design that the Go version can't provide for an AI engineering career pivot.

**User:** Me, replacing the Go FSM with a LangGraph state graph so I have something defensible in a technical interview on stateful agent design.

**Current walking-skeleton proof:** A stdio MCP server backed by LangGraph state graphs that ingests a JD and resume, pauses for host-owned reasoning at explicit handoff points, runs deterministic scoring/rendering/archival steps, and returns concrete application artifacts.

**Legacy note:** Early sketches expected most computation to delegate to the Go `go-apply` binary. The current Python server owns the main walking-skeleton path directly. `bridge.py` remains only as a dead legacy adapter (wired into nothing at runtime; kept for its tests).

**State owner:** Client — LangGraph checkpointer on local disk, persists across restarts, no coordination required.

**Interface:** MCP server (one interface — MCP protocol IS the portability layer; any compliant harness works without a second interface).
Second interface when: N/A — the protocol handles it.

---

**Red flags:**
- Differentiator is a learning/career goal, not a product capability. Legitimate — but scope discipline is critical. Any complexity beyond "teaches LangGraph" is wasted on a project with a finite maintenance horizon.
- Finite maintenance horizon declared upfront. Don't add polish that won't ship.

**Verdict:** Keep building only what the walking skeleton needs. The moment you feel the urge to add pgvector, LLM-as-judge, provider clients, RAG, or an eval harness, stop unless an explicit proposal makes that complexity serve the ATS-gate North Star.
