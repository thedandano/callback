#!/usr/bin/env python3
"""Smoke test for the apply MCP handoff tools.

Pass a job URL as the first argument to exercise the fetcher.
"""

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Add current directory to path for running via uv
sys.path.insert(0, os.getcwd())

from callback.jd_data import EXTRACTION_PROTOCOL
from callback.jd_fetcher import MIN_MARKDOWN_CHARS
from callback.repository.resumes import save_resume
from callback.section_map import ContactInfo, ExperienceEntry, SectionMap, SkillsSection
from callback.server import load_jd, submit_keywords, submit_tailor
from callback.wiki import WikiStore

JD_JSON = json.dumps(
    {
        "title": "Python Engineer",
        "company": "ExampleCo",
        "required": ["Python", "Kubernetes", "Go"],
    },
    separators=(",", ":"),
)


def _load_phase(jd_url: str | None, jd_text: str, resume_label: str) -> dict:
    """Run the load_jd phase against a live URL or pasted raw text."""
    if jd_url:
        load_result = load_jd(jd_url=jd_url, resume_label=resume_label)
    else:
        load_result = load_jd(jd_raw_text=jd_text, resume_label=resume_label)
    loaded = json.loads(load_result)
    assert loaded["status"] == "ok", f"load_jd failed: {loaded}"
    assert loaded["next_action"] == "extract_keywords", f"unexpected: {loaded}"
    assert loaded["data"]["extraction_protocol"] == EXTRACTION_PROTOCOL
    loaded_text = loaded["data"]["jd_text"]
    if jd_url:
        assert len(loaded_text) > MIN_MARKDOWN_CHARS, f"fetched JD too short: {loaded_text!r}"
        print(f"fetched {len(loaded_text)} chars from {jd_url}")
    else:
        assert loaded_text == jd_text, f"jd_text mismatch: {loaded_text!r}"
    return loaded


def main():
    jd_url = sys.argv[1] if len(sys.argv) > 1 else None

    # Create a temp resume file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("Sample resume text: Python engineer with 5 years experience.")
        resume_path = f.name
    jd_text = "Sample JD: Looking for a Python engineer with Kubernetes and Go experience."
    resume_label = Path(resume_path).stem

    # Write minimal sections.json to WikiStore so parse_initial can load structured data
    section_map = SectionMap(
        contact=ContactInfo(name="Jane Doe", email="jane@example.com"),
        summary="Python engineer with 5 years experience in backend systems.",
        skills=SkillsSection(flat=["Python", "Go"]),
        experience=[
            ExperienceEntry(
                company="ExampleCo",
                role="Software Engineer",
                bullets=[
                    "Built Go microservices handling 200K RPS",
                    "Deployed Python data pipelines",
                ],
            ),
        ],
    )
    WikiStore().write_page(resume_label, "sections.json", section_map.model_dump_json())
    registered_resume_path = save_resume(resume_label, resume_path)

    try:
        # Phase 1: load_jd
        loaded = _load_phase(jd_url, jd_text, resume_label)
        session_id = loaded["session_id"]

        # Phase 2: submit_keywords
        submit_result = submit_keywords(session_id=session_id, jd_json=JD_JSON)
        submitted = json.loads(submit_result)
        assert submitted["status"] == "ok", f"submit_keywords failed: {submitted}"
        assert submitted["next_action"] == "parse_initial", (
            f"unexpected next_action: {submitted['next_action']}"
        )
        assert submitted["data"]["keywords"]["required"] == ["Python", "Kubernetes", "Go"]
        assert "score_gap" in submitted["data"], "score_gap missing from submit_keywords response"

        # Phase 3: submit_tailor
        edits = [
            {
                "section": "summary",
                "op": "replace",
                "value": "Python and Kubernetes engineer, 5 years experience building Go services.",
            },
        ]
        tailor_result = submit_tailor(session_id=session_id, edits=edits)
        tailored = json.loads(tailor_result)
        assert tailored["status"] == "ok", f"submit_tailor failed: {tailored}"
        assert "next_action" not in tailored, (
            f"unexpected next_action: {tailored.get('next_action')}"
        )
        assert len(tailored["data"]["edits_applied"]) > 0, "no edits applied"
        assert tailored["data"]["score_final"] is not None, "score_final missing"
        assert "total" in tailored["data"]["score_final"], "score_final missing total"

        # Phase 4: read archive JSON for score delta
        apps_dir = Path.home() / ".local" / "share" / "callback" / "applications"
        archive_path = apps_dir / f"{session_id}.json"
        assert archive_path.exists(), f"archive not written: {archive_path}"
        archive = json.loads(archive_path.read_text())
        delta = archive["scores"]["delta"]
        assert delta is not None, "scores.delta missing from archive"
        assert delta["keyword_match"] > 0, (
            f"delta.keyword_match <= 0: {delta['keyword_match']}"
            " — tailor did not improve keyword coverage"
        )

        phases = {"load_jd": loaded, "submit_keywords": submitted, "submit_tailor": tailored}
        print(json.dumps(phases, indent=2))
        print(f"\nScore delta: {json.dumps(delta, indent=2)}")
        print(
            "\nSMOKE OK: apply handoff tools executed (load_jd + submit_keywords + submit_tailor)"
        )  # noqa: E501
        return 0
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        # Cleanup temp resume
        Path(resume_path).unlink(missing_ok=True)
        # Cleanup registered resume from registry (best-effort)
        with contextlib.suppress(Exception):
            Path(registered_resume_path).unlink(missing_ok=True)
        # Cleanup sections.json from WikiStore (best-effort)
        try:
            wiki_page = WikiStore().wiki_root(resume_label) / "sections.json"
            wiki_page.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
