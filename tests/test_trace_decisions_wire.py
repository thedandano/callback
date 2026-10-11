"""End-to-end check that decision labels reach the LangSmith payload.

Real langsmith.traceable, mocked HTTP session: no network.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from unittest.mock import MagicMock

from langgraph.graph import END, StateGraph
from langsmith import Client, traceable
from pydantic import BaseModel

import callback.observability as observability

LABEL_KEYS = ("in_tool", "in_node", "in_async", "in_thread")


class _State(BaseModel):
    session_id: str = "s1"
    jd_text: str | None = None


async def _async_work() -> None:
    observability.record_decision("in_async", True)
    await asyncio.to_thread(observability.record_decision, "in_thread", True)


@observability.trace_node("apply", "first")
def _first(state: _State) -> dict:
    asyncio.run(_async_work())
    observability.record_decision("in_node", "yes")
    return {"jd_text": "secret job text"}


def _build_graph():
    builder = StateGraph(_State)
    builder.add_node("first", _first)
    builder.set_entry_point("first")
    builder.add_edge("first", END)
    return builder.compile()


def _labels_sent_on_close(session: MagicMock) -> dict[str, dict]:
    """Per span name: the decision labels in the PATCH that closes the span."""
    sent: dict[str, dict] = {}
    for call in session.request.call_args_list:
        if call.args[0] != "PATCH":
            continue
        body = json.loads(call.kwargs["data"])
        metadata = (body.get("extra") or {}).get("metadata", {})
        sent[body["name"]] = {k: metadata[k] for k in LABEL_KEYS if k in metadata}
    return sent


def test_labels_reach_the_payload_from_tool_node_and_async_code(monkeypatch):
    session = MagicMock()
    client = Client(
        api_url="http://localhost:1984", api_key="x", session=session, auto_batch_tracing=False
    )
    monkeypatch.setenv("CALLBACK_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test")
    monkeypatch.setattr(observability, "_get_traceable", lambda: partial(traceable, client=client))
    graph = _build_graph()

    @observability.trace_tool("load_jd", graph_name="apply")
    def tool(session_id: str) -> dict:
        observability.record_decision("in_tool", "yes")
        observability.invoke_graph_without_native_tracing(
            graph, _State(), {"configurable": {"thread_id": session_id}}
        )
        return {"status": "ok", "session_id": session_id}

    tool("s1")

    actual = _labels_sent_on_close(session)
    expected = {
        "callback.apply.first": {
            "in_tool": "yes",
            "in_node": "yes",
            "in_async": True,
            "in_thread": True,
        },
        "callback.apply.load_jd": {"in_tool": "yes"},
    }
    assert actual == expected
