#!/usr/bin/env python3
"""Smoke test for the apply MCP tool."""
import json
import sys
import tempfile
import os
from pathlib import Path

# Add current directory to path for running via uv
sys.path.insert(0, os.getcwd())

from pi_apply.server import apply


def main():
    # Create a temp resume file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("Sample resume text: Python engineer with 5 years experience.")
        resume_path = f.name

    try:
        # Call apply with minimal inputs
        result = apply(
            jd_raw_text="Sample JD: Looking for a Python engineer with Kubernetes and Go experience.",
            resume_path=resume_path
        )
        data = json.loads(result)
        print(json.dumps(data, indent=2))

        # Verify structure
        assert data["status"] == "ok", f"Expected status='ok', got {data['status']}"
        assert "data" in data, "Missing 'data' key in response"
        assert data["data"]["pdf_path"], "Missing or empty pdf_path"
        assert data["data"]["report"], "Missing or empty report"
        assert "score_initial" in data["data"], "Missing score_initial in data"
        assert "score_final" in data["data"], "Missing score_final in data"
        assert "uncovered_skills" in data["data"], "Missing uncovered_skills in data"
        assert isinstance(data["data"]["uncovered_skills"], list), "uncovered_skills should be a list"

        print("\nSMOKE OK: apply tool executed end-to-end")
        return 0
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        # Cleanup
        Path(resume_path).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
