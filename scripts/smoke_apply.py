#!/usr/bin/env python3
"""Smoke test for the apply MCP handoff tools."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add current directory to path for running via uv
sys.path.insert(0, os.getcwd())

from pi_apply.jd_data import EXTRACTION_PROTOCOL
from pi_apply.section_map import ExperienceEntry, SectionMap, SkillsSection
from pi_apply.server import load_jd, submit_keywords, submit_tailor
from pi_apply.wiki import WikiStore

JD_JSON = json.dumps(
    {
        "title": "Python Engineer",
        "company": "ExampleCo",
        "required": ["Python", "Kubernetes", "Go"],
    },
    separators=(",", ":"),
)


def main():
    # Create a temp resume file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("Sample resume text: Python engineer with 5 years experience.")
        resume_path = f.name
    jd_text = "Sample JD: Looking for a Python engineer with Kubernetes and Go experience."
    resume_label = Path(resume_path).stem

    # Write minimal sections.json to WikiStore so parse_initial can load structured data
    section_map = SectionMap(
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

    try:
        # Phase 1: load_jd
        load_result = load_jd(
            jd_raw_text=jd_text,
            resume_path=resume_path,
        )
        loaded = json.loads(load_result)
        session_id = loaded["session_id"]
        expected_loaded = {
            "session_id": session_id,
            "status": "ok",
            "next_action": "extract_keywords",
            "data": {
                "jd_text": jd_text,
                "extraction_protocol": EXTRACTION_PROTOCOL,
            },
        }
        assert loaded == expected_loaded, f"load_jd mismatch: {loaded}"

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
        assert tailored["next_action"] == "render", (
            f"unexpected next_action: {tailored['next_action']}"
        )
        assert len(tailored["data"]["edits_applied"]) > 0, "no edits applied"
        assert "total" in tailored["data"]["score_final"], "score_final missing total"

        # Phase 4: read archive JSON for score delta
        apps_dir = Path.home() / ".local" / "share" / "pi-apply" / "applications"
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
        # Cleanup sections.json from WikiStore (best-effort)
        try:
            wiki_page = WikiStore().wiki_root(resume_label) / "sections.json"
            wiki_page.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
