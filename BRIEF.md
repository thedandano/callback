# Pre-Build Brief — pi-apply v2 (Python LangGraph MCP Server)

**Differentiator:** LangGraph experience on a non-trivial, real-world stateful agent workflow — a concrete portfolio talking point about agent design that the Go version can't provide for an AI engineering career pivot.

**User:** Me, replacing the Go FSM with a LangGraph state graph so I have something defensible in a technical interview on stateful agent design.

**Smallest proof:** A LangGraph graph that ingests a JD and resume, runs through the workflow steps with visible logs at each node, delegates all computation to existing Go subprocess binaries, and produces output at the end.

**State owner:** Client — LangGraph checkpointer on local disk, persists across restarts, no coordination required.

**Interface:** MCP server (one interface — MCP protocol IS the portability layer; any compliant harness works without a second interface).
Second interface when: N/A — the protocol handles it.

---

**Red flags:**
- Differentiator is a learning/career goal, not a product capability. Legitimate — but scope discipline is critical. Any complexity beyond "teaches LangGraph" is wasted on a project with a finite maintenance horizon.
- Finite maintenance horizon declared upfront. Don't add polish that won't ship.

**Verdict:** Ready to build — with one constraint. Build only what the walking skeleton needs. The moment you feel the urge to add pgvector, LLM-as-judge, or an eval harness before the LangGraph graph runs end-to-end, stop. Floor before scaffold.
