"""Tests for pi_apply.server MCP tool registration and routing."""

import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

from pi_apply.jd_data import EXTRACTION_PROTOCOL

PARTIAL_JD_JSON = """
{
  "title": "Backend Engineer",
  "company": "ExampleCo",
  "required": ["Python"]
}
"""

EXPECTED_PARTIAL_KEYWORDS = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
    "preferred": [],
    "location": None,
    "seniority": "mid",
    "required_years": 0.0,
    "team": None,
    "key_responsibilities": [],
    "pay_range_min": None,
    "pay_range_max": None,
}


def _expected_load_jd_workflow(session_id: str) -> dict:
    return {
        "phase": "keyword_extraction",
        "next_tool": "submit_keywords",
        "host_task": (
            "Extract compact JDData JSON from data.jd_text using "
            "data.extraction_protocol, then call submit_keywords."
        ),
        "required_input": {
            "session_id": session_id,
            "jd_json": "<compact JDData JSON string>",
        },
    }


def _missing_ats_format_gap() -> list[dict]:
    return [
        {
            "expected": expected,
            "observed": None,
            "matched": False,
            "closeable_by": "source_pdf",
        }
        for expected in ("Experience", "Education", "Skills")
    ]


def _tool_names(server) -> set[str]:
    components = server.mcp.local_provider._components
    return {component.name for key, component in components.items() if key.startswith("tool:")}


def test_apply_handoff_tools_registered():
    import pi_apply.server as server

    expected = {
        "load_jd",
        "submit_keywords",
        "submit_tailor",
        "get_wiki_pages",
        "onboard_user",
        "compile_profile",
        "create_story",
        "check_update",
    }

    assert _tool_names(server) == expected


def test_legacy_apply_tool_absent():
    import pi_apply.server as server

    legacy = {
        "apply",
        "submit_tailor_t1",
        "submit_tailor_t2",
        "finalize",
        "preview_ats_extraction",
        "add_resume",
        "get_config",
        "update_config",
    }

    assert _tool_names(server).intersection(legacy) == set()


def test_run_starts_mcp_without_browser_install():
    import pi_apply.server as server

    with (
        patch.object(server, "_ensure_browsers") as ensure_browsers,
        patch.object(server, "_log") as log,
        patch.object(server.mcp, "run") as mcp_run,
    ):
        server.run()

    ensure_browsers.assert_not_called()
    mcp_run.assert_called_once_with(transport="stdio", show_banner=False)
    assert [call.args[1]["event"] for call in log.call_args_list] == [
        "server_start",
        "server_stop",
    ]


def test_run_logs_crash_before_raising_explicit_error():
    import pi_apply.server as server

    error = RuntimeError("transport failed")
    with (
        patch.object(server, "_log") as log,
        patch.object(server, "_log_exception") as log_exception,
        patch.object(server.mcp, "run", side_effect=error),
        pytest.raises(RuntimeError, match="pi-apply MCP stdio server crashed") as exc_info,
    ):
        server.run()

    actual = {
        "cause": exc_info.value.__cause__,
        "crash_event": log_exception.call_args.args[0]["event"],
        "events": [call.args[1]["event"] for call in log.call_args_list],
    }
    expected = {
        "cause": error,
        "crash_event": "server_crash",
        "events": ["server_start", "server_stop"],
    }

    assert actual == expected


def test_run_logs_crash_traceback_before_raising():
    import pi_apply.server as server

    captured_payloads: list[dict] = []
    original_log_exception = server._log_exception

    def fake_log_exception(payload: dict) -> None:
        original_log_exception(payload)
        captured_payloads.append(payload)

    with (
        patch.object(server, "_write_log_line"),
        patch.object(server.logger, "exception"),
        patch.object(server, "_log"),
        patch.object(server, "_log_exception", side_effect=fake_log_exception),
        patch.object(server.mcp, "run", side_effect=RuntimeError("transport failed")),
        pytest.raises(RuntimeError, match="pi-apply MCP stdio server crashed"),
    ):
        server.run()

    assert "RuntimeError: transport failed" in captured_payloads[0]["traceback"]


def test_load_jd_rejects_missing_jd_input():
    from pi_apply.server import load_jd

    result = json.loads(load_jd())
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "missing_input",
            "message": "neither jd_url nor jd_raw_text provided",
            "retriable": False,
        },
    }

    assert result == expected


def test_load_jd_returns_handoff_envelope():
    from pi_apply.server import load_jd

    jd_text = "Python engineer needed"

    with patch("pi_apply.server.list_resumes", return_value=["resume"]):
        result = json.loads(load_jd(jd_raw_text=jd_text))
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {
            "jd_text": jd_text,
            "extraction_protocol": EXTRACTION_PROTOCOL,
        },
        "workflow": _expected_load_jd_workflow(session_id),
    }

    assert result == expected


def test_load_jd_trace_payload_carries_jd_text_and_full_output_data(monkeypatch):
    import pi_apply.server as server
    from pi_apply.server import load_jd

    captured: dict = {}

    class FakeGraph:
        def invoke(self, initial_state, config):
            return {"jd_text": "secret jd body"}

    def fake_traceable(**options):
        def decorator(func):
            def wrapped(*args, **kwargs):
                result = func(*args, **kwargs)
                captured["inputs"] = options["process_inputs"](
                    {
                        "session_id": args[0],
                        "jd_raw_text": args[1],
                        "jd_url": None,
                        "resume_label": "resume",
                    }
                )
                captured["outputs"] = options["process_outputs"](result)
                return result

            return wrapped

        return decorator

    monkeypatch.setenv("PI_APPLY_TRACE_BACKEND", "langsmith")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-secret")

    with (
        patch.object(server, "list_resumes", return_value=["resume"]),
        patch.object(server, "build_apply_graph", return_value=FakeGraph()),
        patch("pi_apply.observability._get_traceable", return_value=fake_traceable),
    ):
        result = json.loads(load_jd(jd_raw_text="secret jd body"))

    # Full business content is present in trace; contact PII is redacted (none here).
    # jd_raw_text survives in inputs; full output data is present (not minimized).
    actual = {
        "status": result["status"],
        "input_jd_raw_text": captured["inputs"]["jd_raw_text"],
        "output_data_has_jd_text": "jd_text" in captured["outputs"]["data"],
        "output_data_has_extraction_protocol": "extraction_protocol" in captured["outputs"]["data"],
    }
    expected = {
        "status": "ok",
        "input_jd_raw_text": "secret jd body",
        "output_data_has_jd_text": True,
        "output_data_has_extraction_protocol": True,
    }

    assert actual == expected


def test_load_jd_returns_error_when_session_store_is_readonly():
    from pi_apply.server import load_jd

    class ReadonlyGraph:
        def invoke(self, initial_state, config):
            raise sqlite3.OperationalError("attempt to write a readonly database")

    with (
        patch("pi_apply.server.list_resumes", return_value=["resume"]),
        patch("pi_apply.server.build_apply_graph", return_value=ReadonlyGraph()),
    ):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed"))

    expected = {
        "session_id": result["session_id"],
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "session_store_error",
            "message": "unable to create or update apply session store",
            "retriable": True,
        },
    }
    assert result == expected


def test_load_jd_returns_error_when_unexpected_exception_escapes_graph():
    from pi_apply.server import load_jd

    class BrokenGraph:
        def invoke(self, initial_state, config):
            raise ValueError("boom")

    with (
        patch("pi_apply.server.list_resumes", return_value=["resume"]),
        patch("pi_apply.server.build_apply_graph", return_value=BrokenGraph()),
    ):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed"))

    expected = {
        "session_id": result["session_id"],
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "unexpected_error",
            "message": "unexpected load_jd failure; inspect pi-apply logs",
            "retriable": False,
        },
    }
    assert result == expected


def test_configure_logging_writes_server_log(tmp_path):
    import logging

    from pi_apply.server import configure_logging

    log_path = tmp_path / "server.log"
    configure_logging(log_path)

    logging.getLogger("pi_apply.server").info("test log line")

    assert "test log line" in log_path.read_text(encoding="utf-8")


def test_load_jd_accepts_url_with_raw_text_fallback():
    from pi_apply.server import load_jd

    jd_url = "https://example.test/job"
    jd_text = "# Python Engineer\n\nBuild Python services and own APIs."
    fetch_mock = AsyncMock(return_value=jd_text)

    with (
        patch("pi_apply.apply_nodes.fetch_url_to_markdown", fetch_mock),
        patch("pi_apply.server.list_resumes", return_value=["resume"]),
    ):
        result = json.loads(
            load_jd(
                jd_url=jd_url,
                jd_raw_text="Python engineer fallback text",
            )
        )
    session_id = result["session_id"]
    uuid.UUID(session_id)
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {
            "jd_text": jd_text,
            "extraction_protocol": EXTRACTION_PROTOCOL,
        },
        "workflow": _expected_load_jd_workflow(session_id),
    }

    assert result == expected
    fetch_mock.assert_awaited_once_with(jd_url)


def test_submit_keywords_stores_jddata_and_routes_missing_wiki_to_onboarding():
    from pi_apply.server import load_jd, submit_keywords

    with patch("pi_apply.server.list_resumes", return_value=["resume"]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    session_id = loaded["session_id"]

    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "onboard_resume_first",
        "data": {
            "keywords": EXPECTED_PARTIAL_KEYWORDS,
            "score_gap": {
                "required_missing": result["data"]["score_gap"]["required_missing"],
                "preferred_missing": result["data"]["score_gap"]["preferred_missing"],
            },
            "ats_format_gap": _missing_ats_format_gap(),
            "orphaned_required": result["data"]["orphaned_required"],
        },
        "workflow": {
            "phase": "onboard_resume",
            "next_tool": "onboard_user",
            "host_task": result["workflow"]["host_task"],
            "required_input": {
                "resume_path": "<path to PDF, DOCX, TXT, or Markdown resume>",
                "skills_path": "<optional path to skills file>",
                "accomplishments_path": "<optional path to accomplishments file>",
            },
        },
    }

    assert result == expected
    assert "restart this job flow with load_jd" in result["workflow"]["host_task"]


def test_submit_keywords_rejects_invalid_jd_json():
    from pi_apply.server import submit_keywords

    session_id = "session-123"
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_jd",
            "message": "jd_json must encode an object",
            "retriable": True,
        },
        "session_id": session_id,
    }

    assert json.loads(submit_keywords(session_id=session_id, jd_json="[]")) == expected


def test_submit_keywords_rejects_empty_jd_json():
    from pi_apply.server import submit_keywords

    session_id = "session-123"
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_jd",
            "message": "required skills must not be empty",
            "retriable": True,
        },
        "session_id": session_id,
    }

    assert json.loads(submit_keywords(session_id=session_id, jd_json="{}")) == expected


def test_submit_keywords_rejects_unknown_session():
    from pi_apply.server import submit_keywords

    session_id = "missing-session"
    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_session",
            "message": "session_id was not found; call load_jd before submit_keywords",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_submit_keywords_rejects_blank_session_with_session_id():
    from pi_apply.server import submit_keywords

    session_id = ""
    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_session",
            "message": "session_id was not found; call load_jd before submit_keywords",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_submit_keywords_rejects_session_not_waiting_for_keywords():
    from pi_apply.server import load_jd, submit_keywords

    with patch("pi_apply.server.list_resumes", return_value=["resume"]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    session_id = loaded["session_id"]
    submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON)

    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))
    expected = {
        "status": "error",
        "error": {
            "stage": "submit_keywords",
            "code": "invalid_state",
            "message": "session is not waiting for keyword submission",
            "retriable": False,
        },
        "session_id": session_id,
    }

    assert result == expected


def test_submit_keywords_ats_format_gap_has_three_entries():
    """submit_keywords returns one ATS gap entry per required header."""
    from pi_apply.server import load_jd, submit_keywords

    with patch("pi_apply.server.list_resumes", return_value=["resume"]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    session_id = loaded["session_id"]

    result = json.loads(submit_keywords(session_id=session_id, jd_json=PARTIAL_JD_JSON))

    actual = {
        "entry_count": len(result["data"]["ats_format_gap"]),
        "entries": result["data"]["ats_format_gap"],
    }
    expected = {
        "entry_count": 3,
        "entries": _missing_ats_format_gap(),
    }
    assert actual == expected


def test_submit_keywords_tailor_instructions_include_project_guidance(tmp_path, monkeypatch):
    from pi_apply.server import load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "project_guidance_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [
            {
                "company": "ACME",
                "role": "Engineer",
                "bullets": ["Built Python services"],
            }
        ],
        "projects": [
            {
                "name": "Search Lab",
                "description": "Explored ranking systems",
                "bullets": ["Built prototype search APIs"],
            }
        ],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(resume_label, "Python evidence in dated experience")

    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    result = json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=PARTIAL_JD_JSON))

    instructions = result["data"]["tailor_instructions"]
    actual = {
        "next_action": result["next_action"],
        "workflow_phase": result["workflow"]["phase"],
        "workflow_next_tool": result["workflow"]["next_tool"],
        "allowed_next_tools": result["workflow"]["allowed_next_tools"],
        "required_input": result["workflow"]["required_input"],
        "host_task_mentions_sections": "data.sections" in result["workflow"]["host_task"],
        "mentions_project_descriptions": "existing project descriptions or bullets" in instructions,
        "mentions_wiki_source": "source resume or profile wiki" in instructions,
        "rejects_invented_project_facts": "MUST NOT invent project facts" in instructions,
        "rejects_keyword_only_text": "keyword-only text" in instructions,
        "keeps_skills_coverage_dated": "dated experience bullet" in instructions,
    }
    expected = {
        "next_action": "fetch_wiki_then_tailor",
        "workflow_phase": "tailor_evidence",
        "workflow_next_tool": "get_wiki_pages",
        "allowed_next_tools": ["get_wiki_pages", "submit_tailor"],
        "required_input": {
            "session_id": loaded["session_id"],
            "page_ids": ["experience/<page-id>.md"],
        },
        "host_task_mentions_sections": True,
        "mentions_project_descriptions": True,
        "mentions_wiki_source": True,
        "rejects_invented_project_facts": True,
        "rejects_keyword_only_text": True,
        "keeps_skills_coverage_dated": True,
    }
    assert actual == expected


def test_submit_keywords_returns_ranked_project_candidates(tmp_path, monkeypatch):
    from pi_apply.server import load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "project_candidate_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [
            {
                "company": "ACME",
                "role": "Engineer",
                "bullets": ["Built Python services"],
            }
        ],
        "projects": [
            {
                "name": "Howe-2",
                "description": "Nonprofit website",
                "bullets": ["Built adoption site with Node.js"],
            }
        ],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(
        resume_label,
        "\n".join(
            [
                "# Profile Index",
                "- [Personal Voice LLM](experience/story-013.md)",
                "- [Amazon GenAI Work](experience/story-006.md)",
                "- [pi-apply](experience/story-012.md)",
            ]
        ),
    )
    store.write_page(
        resume_label,
        "experience/story-013.md",
        """# Personal Voice LLM — Gemma Fine-Tuning — May 2026

**Job Title:** Project

Skills: Python, RAG, ChatML, QLoRA, LLMs

**Situation:** Personal voice model work.

**Behavior:** Built a Python pipeline that packaged ChatML records for LLM fine-tuning.

**Impact:** Produced 17,027 records and used blind A/B ranking.
""",
    )
    store.write_page(
        resume_label,
        "experience/story-006.md",
        """# Amazon GenAI Work

**Job Title:** Software Development Engineer II

Skills: Python, RAG, LLMs
""",
    )
    store.write_page(
        resume_label,
        "experience/story-012.md",
        """# pi-apply — LangGraph Resume Tailoring MCP Server — April 2026

**Job Title:** Project

Skills: Python, MCP, LangGraph, SQL

**Situation:** Resume tailoring workflow.

**Behavior:** Built a Python MCP server.

**Impact:** Improved an ATS score by 7.36 points.
""",
    )
    jd_json = json.dumps(
        {
            "title": "GenAI Engineer",
            "company": "Co",
            "required": ["Python", "RAG", "LLMs", "ChatML"],
            "preferred": ["MCP"],
        }
    )

    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="GenAI engineer needed"))
        result = json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=jd_json))

    candidates = result["data"]["project_candidates"]
    recommendation = result["data"]["project_swap_recommendation"]
    actual = {
        "candidate_names": [c["name"] for c in candidates],
        "top_page_id": candidates[0]["page_id"],
        "top_required_matched": candidates[0]["required_matched"],
        "top_preferred_matched": candidates[0]["preferred_matched"],
        "recommendation_target": recommendation["replace_target"],
        "recommendation_candidate": recommendation["candidate"]["name"],
    }
    expected = {
        "candidate_names": [
            "Personal Voice LLM — Gemma Fine-Tuning — May 2026",
            "pi-apply — LangGraph Resume Tailoring MCP Server — April 2026",
        ],
        "top_page_id": "experience/story-013.md",
        "top_required_matched": ["Python", "RAG", "LLMs", "ChatML"],
        "top_preferred_matched": [],
        "recommendation_target": "proj-0",
        "recommendation_candidate": "Personal Voice LLM — Gemma Fine-Tuning — May 2026",
    }
    assert actual == expected


def test_submit_keywords_recommends_project_append_and_trim_candidates(tmp_path, monkeypatch):
    from pi_apply.server import load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "project_append_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [
            {
                "company": "ACME",
                "role": "Engineer",
                "bullets": [
                    "Built Python services",
                    "Mentored teammates",
                ],
            }
        ],
        "projects": [
            {
                "name": "Howe-2",
                "description": "Nonprofit website",
                "bullets": ["Built AWS adoption site"],
            }
        ],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(
        resume_label,
        "\n".join(
            [
                "# Profile Index",
                "- [Personal Voice LLM](experience/story-013.md)",
            ]
        ),
    )
    store.write_page(
        resume_label,
        "experience/story-013.md",
        """# Personal Voice LLM — Gemma Fine-Tuning — May 2026

**Job Title:** Project

Skills: Python, RAG, ChatML, LLMs

**Behavior:** Built a Python pipeline for RAG and ChatML records.
""",
    )
    jd_json = json.dumps(
        {
            "title": "GenAI Engineer",
            "company": "Co",
            "required": ["Python", "RAG", "ChatML"],
            "preferred": ["AWS"],
        }
    )

    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="GenAI engineer needed"))
        result = json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=jd_json))

    layout = result["data"]["project_layout_recommendation"]
    trim_candidates = result["data"]["trim_candidates"]
    actual = {
        "layout_strategy": layout["strategy"],
        "layout_add_target": layout["add_target"],
        "layout_max_visible_projects": layout["max_visible_projects"],
        "layout_candidate": layout["candidate"]["name"],
        "trim_targets": [candidate["target"] for candidate in trim_candidates],
        "first_trim_score": trim_candidates[0]["score"],
        "first_trim_required": trim_candidates[0]["required_matched"],
        "project_trim_preferred": trim_candidates[1]["preferred_matched"],
    }
    expected = {
        "layout_strategy": "append",
        "layout_add_target": "proj-end",
        "layout_max_visible_projects": 2,
        "layout_candidate": "Personal Voice LLM — Gemma Fine-Tuning — May 2026",
        "trim_targets": ["exp-0-b1", "proj-0-b0", "exp-0-b0"],
        "first_trim_score": 0.0,
        "first_trim_required": [],
        "project_trim_preferred": ["AWS"],
    }
    assert actual == expected


def test_submit_keywords_recommends_project_replace_when_two_visible_projects(
    tmp_path, monkeypatch
):
    from pi_apply.server import load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "project_replace_layout_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [
            {
                "company": "ACME",
                "role": "Engineer",
                "bullets": ["Built Python services"],
            }
        ],
        "projects": [
            {
                "name": "Howe-2",
                "description": "Nonprofit website",
                "bullets": ["Built adoption site"],
            },
            {
                "name": "Search Lab",
                "description": "Python search project",
                "bullets": ["Built Python search API"],
            },
        ],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(
        resume_label,
        "\n".join(
            [
                "# Profile Index",
                "- [Personal Voice LLM](experience/story-013.md)",
            ]
        ),
    )
    store.write_page(
        resume_label,
        "experience/story-013.md",
        """# Personal Voice LLM — Gemma Fine-Tuning — May 2026

**Job Title:** Project

Skills: Python, RAG, ChatML, LLMs

**Behavior:** Built a Python RAG and ChatML pipeline for LLM fine-tuning.
""",
    )
    jd_json = json.dumps(
        {
            "title": "GenAI Engineer",
            "company": "Co",
            "required": ["Python", "RAG", "ChatML"],
            "preferred": [],
        }
    )

    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="GenAI engineer needed"))
        result = json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=jd_json))

    layout = result["data"]["project_layout_recommendation"]
    actual = {
        "strategy": layout["strategy"],
        "replace_target": layout["replace_target"],
        "candidate": layout["candidate"]["name"],
        "max_visible_projects": layout["max_visible_projects"],
    }
    expected = {
        "strategy": "replace",
        "replace_target": "proj-0",
        "candidate": "Personal Voice LLM — Gemma Fine-Tuning — May 2026",
        "max_visible_projects": 2,
    }
    assert actual == expected


def test_submit_keywords_orphaned_required_routes_to_create_story(tmp_path, monkeypatch):
    from pi_apply.server import load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "orphan_workflow_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(
        "Jane Dev\nExperience\nBuilt backend APIs\nEducation\nBS Computer Science\n",
        encoding="utf-8",
    )
    sections = {
        "summary": "Backend engineer",
        "skills": {"flat": ["Kafka"], "categorized": {}},
        "experience": [{"company": "ACME", "role": "Engineer", "bullets": ["Built APIs"]}],
        "projects": [],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(resume_label, "Python evidence only")

    jd_json = json.dumps({"title": "Backend Engineer", "company": "Co", "required": ["Kafka"]})
    with (
        patch("pi_apply.server.list_resumes", return_value=[resume_label]),
        patch("pi_apply.apply_nodes.get_resume", return_value=str(resume_path)),
    ):
        loaded = json.loads(load_jd(jd_raw_text="Kafka engineer needed"))
        result = json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=jd_json))

    actual = {
        "next_action": result["next_action"],
        "orphaned_required": result["data"]["orphaned_required"],
        "workflow_phase": result["workflow"]["phase"],
        "workflow_next_tool": result["workflow"]["next_tool"],
        "primary_skill": result["workflow"]["required_input"]["primary_skill"],
        "host_task_restarts_flow": "restart this job flow with load_jd"
        in result["workflow"]["host_task"],
    }
    expected = {
        "next_action": "add_story_first",
        "orphaned_required": ["Kafka"],
        "workflow_phase": "story_evidence",
        "workflow_next_tool": "create_story",
        "primary_skill": "Kafka",
        "host_task_restarts_flow": True,
    }
    assert actual == expected


def test_get_wiki_pages_returns_submit_tailor_workflow(tmp_path, monkeypatch):
    from pi_apply.server import get_wiki_pages, load_jd, submit_keywords
    from pi_apply.wiki import WikiStore

    resume_label = "wiki_pages_workflow_resume"
    monkeypatch.setattr("pi_apply.wiki.BASE_DIR", tmp_path / "wiki")
    sections = {
        "summary": "Python engineer",
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [{"company": "ACME", "role": "Engineer", "bullets": ["Built Python"]}],
        "projects": [],
        "education": [],
        "contact": {"name": "Jane Dev"},
        "certifications": [],
        "awards": [],
    }
    store = WikiStore()
    store.write_page(resume_label, "sections.json", json.dumps(sections))
    store.write_index(resume_label, "- experience/acme.md")
    store.write_page(resume_label, "experience/acme.md", "Built Python services.")

    with patch("pi_apply.server.list_resumes", return_value=[resume_label]):
        loaded = json.loads(load_jd(jd_raw_text="Python engineer needed"))
    json.loads(submit_keywords(session_id=loaded["session_id"], jd_json=PARTIAL_JD_JSON))

    result = json.loads(
        get_wiki_pages(session_id=loaded["session_id"], page_ids=["experience/acme.md"])
    )

    actual = {
        "status": result["status"],
        "pages": result["data"]["pages"],
        "workflow_phase": result["workflow"]["phase"],
        "workflow_next_tool": result["workflow"]["next_tool"],
        "required_session_id": result["workflow"]["required_input"]["session_id"],
        "required_no_coverage": result["workflow"]["required_input"]["no_coverage"],
    }
    expected = {
        "status": "ok",
        "pages": {"experience/acme.md": "Built Python services."},
        "workflow_phase": "tailor_editing",
        "workflow_next_tool": "submit_tailor",
        "required_session_id": loaded["session_id"],
        "required_no_coverage": False,
    }
    assert actual == expected


class TestOrphanDetection:
    """Tests for _detect_orphaned_required orphan classification logic."""

    def test_orphan_detected_when_skill_in_sections_not_in_wiki(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Python", "Docker"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Docker\n- Built containers\n"

        result = _detect_orphaned_required(["Python", "Docker"], sections, wiki_index)

        assert result == ["Python"]

    def test_genuine_gap_not_flagged_as_orphan(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Docker"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Docker\n- Built containers\n"

        result = _detect_orphaned_required(["Kubernetes"], sections, wiki_index)

        assert result == []

    def test_skill_covered_in_wiki_not_flagged(self):
        from pi_apply.server import _detect_orphaned_required

        sections = {
            "skills": {
                "flat": ["Python"],
                "categorized": {},
            }
        }
        wiki_index = "# Stories\n\n## Python\n- Built services in python\n"

        result = _detect_orphaned_required(["Python"], sections, wiki_index)

        assert result == []


_NO_COVERAGE_JD_JSON = json.dumps(
    {
        "title": "Backend Engineer",
        "company": "ExampleCo",
        "required": ["Python"],
    }
)


class TestSubmitTailorNoCoverage:
    """Tests for submit_tailor with no_coverage=True."""

    def test_submit_tailor_no_coverage_sets_outcome(self, tmp_path, monkeypatch):
        """no_coverage=True skips edits, runs graph to finalize, and returns no_coverage outcome."""
        from pi_apply.server import load_jd, submit_keywords, submit_tailor

        monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path / "applications"))

        with patch("pi_apply.server.list_resumes", return_value=["resume"]):
            session_id = json.loads(load_jd(jd_raw_text="Python engineer needed"))["session_id"]
        json.loads(submit_keywords(session_id=session_id, jd_json=_NO_COVERAGE_JD_JSON))

        result = json.loads(submit_tailor(session_id=session_id, edits=[], no_coverage=True))

        actual = {
            "status": result["status"],
            "session_id": result["session_id"],
            "no_next_action": "next_action" not in result,
            "edits_applied": result["data"]["edits_applied"],
            "edits_rejected": result["data"]["edits_rejected"],
            "uncovered_skills": result["data"]["uncovered_skills"],
            "pdf_path": result["data"]["pdf_path"],
            "archive_exists": Path(result["data"]["archive_path"]).exists(),
            "workflow_phase": result["workflow"]["phase"],
            "workflow_next_tool": result["workflow"]["next_tool"],
            "score_final_is_none_or_dict": result["data"]["score_final"] is None
            or isinstance(result["data"]["score_final"], dict),
            "report_no_coverage": (result["data"]["report"] or {}).get("no_coverage"),
            "outcome_no_coverage": result["data"]["outcome"]["no_coverage"],
        }
        assert actual == {
            "status": "ok",
            "session_id": session_id,
            "no_next_action": True,
            "edits_applied": [],
            "edits_rejected": [],
            "uncovered_skills": [],
            "pdf_path": None,
            "archive_exists": True,
            "workflow_phase": "complete",
            "workflow_next_tool": None,
            "score_final_is_none_or_dict": True,
            "report_no_coverage": True,
            "outcome_no_coverage": True,
        }
        assert result["workflow"]["required_input"] == {}

    def test_submit_tailor_no_coverage_report_notes_is_list(self, tmp_path, monkeypatch):
        """submit_tailor report.notes is present and is a list."""
        from pi_apply.server import load_jd, submit_keywords, submit_tailor

        monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path / "applications"))

        with patch("pi_apply.server.list_resumes", return_value=["resume"]):
            session_id = json.loads(load_jd(jd_raw_text="Python engineer needed"))["session_id"]
        json.loads(submit_keywords(session_id=session_id, jd_json=_NO_COVERAGE_JD_JSON))

        result = json.loads(submit_tailor(session_id=session_id, edits=[], no_coverage=True))

        report = result["data"]["report"]
        actual = {
            "status": result["status"],
            "notes_is_list": isinstance(report["notes"], list),
        }
        expected = {
            "status": "ok",
            "notes_is_list": True,
        }
        assert actual == expected


# ============================================================================
# check_update MCP tool — in-process transport tests
# ============================================================================


# ============================================================================
# load_jd resume resolution — tasks 4.1–4.4
# ============================================================================


def test_load_jd_auto_selects_single_registered_resume():
    """Single registered resume is auto-selected when resume_label is omitted."""
    from pi_apply.apply_graph import build_apply_graph, make_config
    from pi_apply.server import load_jd

    with patch("pi_apply.server.list_resumes", return_value=["default"]):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed"))

    session_id = result["session_id"]
    graph = build_apply_graph()
    snapshot = graph.get_state(make_config(session_id))
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {"jd_text": "Python engineer needed", "extraction_protocol": EXTRACTION_PROTOCOL},
        "workflow": _expected_load_jd_workflow(session_id),
    }
    assert result == expected
    assert snapshot.values.get("resume_label") == "default"


def test_load_jd_returns_ambiguous_resume_error_for_multiple_resumes():
    """Multiple resumes registered without label returns ambiguous_resume error."""
    from pi_apply.server import load_jd

    with patch("pi_apply.server.list_resumes", return_value=["default", "senior"]):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed"))

    expected = {
        "session_id": result["session_id"],
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "ambiguous_resume",
            "message": result["error"]["message"],
            "retriable": False,
        },
    }
    assert result == expected
    assert "default" in result["error"]["message"]
    assert "senior" in result["error"]["message"]


def test_load_jd_returns_no_resume_registered_error_when_empty():
    """No registered resumes returns no_resume_registered error."""
    from pi_apply.server import load_jd

    with patch("pi_apply.server.list_resumes", return_value=[]):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed"))

    expected = {
        "session_id": result["session_id"],
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "no_resume_registered",
            "message": result["error"]["message"],
            "retriable": False,
        },
    }
    assert result == expected
    assert "onboard_user" in result["error"]["message"]


def test_load_jd_passes_explicit_label_through_to_state():
    """Explicit resume_label is stored in session state."""
    from pi_apply.apply_graph import build_apply_graph, make_config
    from pi_apply.server import load_jd

    with patch("pi_apply.server.list_resumes", return_value=["default", "senior"]):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed", resume_label="senior"))

    session_id = result["session_id"]
    graph = build_apply_graph()
    snapshot = graph.get_state(make_config(session_id))
    expected = {
        "session_id": session_id,
        "status": "ok",
        "next_action": "extract_keywords",
        "data": {"jd_text": "Python engineer needed", "extraction_protocol": EXTRACTION_PROTOCOL},
        "workflow": _expected_load_jd_workflow(session_id),
    }
    assert result == expected
    assert snapshot.values.get("resume_label") == "senior"


def test_load_jd_returns_error_for_unknown_explicit_label():
    """Explicit resume_label not in registry returns resume_not_found error."""
    from pi_apply.server import load_jd

    with patch("pi_apply.server.list_resumes", return_value=["default"]):
        result = json.loads(load_jd(jd_raw_text="Python engineer needed", resume_label="missing"))

    expected = {
        "session_id": result["session_id"],
        "status": "error",
        "error": {
            "stage": "load_jd",
            "code": "resume_not_found",
            "message": result["error"]["message"],
            "retriable": False,
        },
    }
    assert result == expected
    assert "missing" in result["error"]["message"]


# ============================================================================
# parse_initial resume resolution — tasks 4.5–4.6
# ============================================================================


def test_parse_initial_wiki_miss_calls_get_resume_and_extracts_text(tmp_path):
    """Wiki miss: get_resume is called and text is extracted from the returned path."""
    from pi_apply.apply_nodes import parse_initial
    from pi_apply.state import ApplyState

    resume = tmp_path / "resume.txt"
    resume.write_text("Lead Engineer with Python and Kubernetes experience")
    state = ApplyState(session_id="s1", resume_label="lead")

    with patch("pi_apply.apply_nodes.get_resume", return_value=str(resume)) as mock_get:
        result = parse_initial(state)

    mock_get.assert_called_once_with("lead")
    assert result == {"parsed_initial": "Lead Engineer with Python and Kubernetes experience"}


def test_parse_initial_wiki_miss_resume_not_found_returns_noop_sentinel():
    """Wiki miss with ResumeNotFoundError returns noop sentinel."""
    from pi_apply.apply_nodes import parse_initial
    from pi_apply.repository.resumes import ResumeNotFoundError
    from pi_apply.state import ApplyState

    state = ApplyState(session_id="s1", resume_label="ghost")

    with patch("pi_apply.apply_nodes.get_resume", side_effect=ResumeNotFoundError("ghost")):
        result = parse_initial(state)

    assert result == {"parsed_initial": "<noop:parse:no-source>"}


MINIMAL_SECTIONS_JSON = json.dumps(
    {
        "summary": None,
        "skills": {"flat": ["Python"], "categorized": {}},
        "experience": [{"company": "ACME", "role": "Engineer", "bullets": ["built things"]}],
        "projects": [],
        "education": [],
        "contact": None,
        "certifications": [],
        "awards": [],
    }
)


def test_parse_initial_wiki_hit_uses_pdf_for_parsed_initial(tmp_path):
    """Wiki hit: parsed_initial comes from PDF, sections/wiki_index from wiki."""
    from pi_apply.apply_nodes import parse_initial
    from pi_apply.state import ApplyState

    resume = tmp_path / "resume.txt"
    resume.write_text("Experience\nBuilt Python services.\n\nSkills\nPython")
    state = ApplyState(session_id="s1", resume_label="eng")

    with (
        patch("pi_apply.apply_nodes._load_wiki_sections") as mock_wiki,
        patch("pi_apply.apply_nodes.get_resume", return_value=str(resume)),
    ):
        mock_wiki.return_value = (
            MINIMAL_SECTIONS_JSON,
            "index content",
            "Python ACME Engineer built things",
        )
        result = parse_initial(state)

    actual = {
        "parsed_initial": result["parsed_initial"],
        "has_sections": result["sections"] is not None,
        "wiki_index": result["wiki_index"],
    }
    expected = {
        "parsed_initial": "Experience\nBuilt Python services.\n\nSkills\nPython",
        "has_sections": True,
        "wiki_index": "index content",
    }
    assert actual == expected


def test_parse_initial_wiki_hit_pdf_missing_falls_back_to_sections_text():
    """Wiki hit + ResumeNotFoundError: falls back to _sections_to_text, emits warning."""
    from pi_apply.apply_nodes import parse_initial
    from pi_apply.repository.resumes import ResumeNotFoundError
    from pi_apply.state import ApplyState

    state = ApplyState(session_id="s1", resume_label="eng")
    sections_text = "Python ACME Engineer built things"

    with (
        patch("pi_apply.apply_nodes._load_wiki_sections") as mock_wiki,
        patch("pi_apply.apply_nodes.get_resume", side_effect=ResumeNotFoundError("eng")),
    ):
        mock_wiki.return_value = (MINIMAL_SECTIONS_JSON, "index", sections_text)
        result = parse_initial(state)

    actual = {
        "parsed_initial": result["parsed_initial"],
        "has_sections": result["sections"] is not None,
    }
    expected = {
        "parsed_initial": sections_text,
        "has_sections": True,
    }
    assert actual == expected


# ============================================================================
# check_update MCP tool — in-process transport tests
# ============================================================================
# tailor_diagnostics — _compute_tailor_diagnostics unit tests
# ============================================================================


class TestTailorDiagnostics:
    def test_matched_skill_present_in_rendered_text(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        result = _compute_tailor_diagnostics(
            ["machine learning"],
            "Experience with machine learning and Python.",
        )
        assert result == [
            {
                "value": "machine learning",
                "applied_to_map": True,
                "present_in_rendered_text": True,
                "suggested_alternatives": [],
            }
        ]

    def test_hyphen_dropped_by_pdf_extraction_not_present(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        result = _compute_tailor_diagnostics(
            ["agent-based workflows"],
            "Experience with agent based workflows.",  # hyphen dropped
        )
        assert result == [
            {
                "value": "agent-based workflows",
                "applied_to_map": True,
                "present_in_rendered_text": False,
                "suggested_alternatives": ["agent based workflows"],
            }
        ]

    def test_suggested_alternatives_uses_normalization(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        result = _compute_tailor_diagnostics(
            ["retrieval-augmented generation (RAG)"],
            "retrieval augmented generation (RAG)",
        )
        assert result == [
            {
                "value": "retrieval-augmented generation (RAG)",
                "applied_to_map": True,
                "present_in_rendered_text": False,
                "suggested_alternatives": ["retrieval augmented generation (RAG)"],
            }
        ]

    def test_no_applied_skill_values_returns_empty(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        assert _compute_tailor_diagnostics(None, "some text") == []
        assert _compute_tailor_diagnostics([], "some text") == []

    def test_case_insensitive_match(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        result = _compute_tailor_diagnostics(["Python"], "built with PYTHON and Django")
        actual = {
            "present_in_rendered_text": result[0]["present_in_rendered_text"],
            "suggested_alternatives": result[0]["suggested_alternatives"],
        }
        expected = {
            "present_in_rendered_text": True,
            "suggested_alternatives": [],
        }
        assert actual == expected

    def test_all_matched_returns_empty_alternatives(self):
        from pi_apply.apply_nodes import _compute_tailor_diagnostics

        result = _compute_tailor_diagnostics(["Python", "Go"], "Python and Go are used.")
        actual = {
            "all_present": all(r["present_in_rendered_text"] for r in result),
            "all_alternatives_empty": all(r["suggested_alternatives"] == [] for r in result),
        }
        expected = {
            "all_present": True,
            "all_alternatives_empty": True,
        }
        assert actual == expected


# ============================================================================


@pytest.mark.anyio
async def test_check_update_tool_returns_update_available():
    import pi_apply.server as server
    import pi_apply.version_check as vc

    vc._cached = None
    check_result = {
        "checked": True,
        "current": "0.2.0",
        "latest": "v9.9.9",
        "update_available": True,
    }

    with patch.object(vc, "check_update", return_value=check_result):
        async with Client(FastMCPTransport(server.mcp)) as client:
            result = await client.call_tool("check_update", {})

    envelope = json.loads(str(result.data))
    assert envelope == {"session_id": "", "status": "ok", "data": check_result}


@pytest.mark.anyio
async def test_check_update_tool_returns_already_current():
    import pi_apply.server as server
    import pi_apply.version_check as vc

    vc._cached = None
    check_result = {
        "checked": True,
        "current": "0.2.0",
        "latest": "v0.2.0",
        "update_available": False,
    }

    with patch.object(vc, "check_update", return_value=check_result):
        async with Client(FastMCPTransport(server.mcp)) as client:
            result = await client.call_tool("check_update", {})

    envelope = json.loads(str(result.data))
    assert envelope == {"session_id": "", "status": "ok", "data": check_result}
