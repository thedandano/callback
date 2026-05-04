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
from pi_apply.server import load_jd, submit_keywords

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

    try:
        # Call load_jd with minimal inputs
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
        assert loaded == expected_loaded

        submit_result = submit_keywords(session_id=session_id, jd_json=JD_JSON)
        submitted = json.loads(submit_result)
        expected_submitted = {
            "session_id": session_id,
            "status": "ok",
            "next_action": "parse_initial",
            "data": {
                "keywords": {
                    "title": "Python Engineer",
                    "company": "ExampleCo",
                    "required": ["Python", "Kubernetes", "Go"],
                    "preferred": None,
                    "location": None,
                    "seniority": "mid",
                    "required_years": None,
                    "team": None,
                    "key_responsibilities": None,
                    "pay_range_min": None,
                    "pay_range_max": None,
                },
            },
        }
        assert submitted == expected_submitted

        print(json.dumps({"load_jd": loaded, "submit_keywords": submitted}, indent=2))
        print("\nSMOKE OK: apply handoff tools executed")
        return 0
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        # Cleanup
        Path(resume_path).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
