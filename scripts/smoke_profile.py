#!/usr/bin/env python3
"""Smoke test for the profile MCP tools: onboard_user, compile_profile, create_story."""

import json
import os
import sys
import tempfile
import traceback

# Add current directory to path for running via uv
sys.path.insert(0, os.getcwd())

from pi_apply.server import compile_profile, create_story, onboard_user

RESUME_TEXT = """\
Jane Doe
jane@example.com

Experience
Acme Corp | DevOps Engineer | 2021 - 2024
- Automated AWS provisioning using Terraform, reducing deploy time by 50%.
- Migrated CI/CD pipelines to GitHub Actions across 12 services.

Skills
Terraform, AWS, GitHub Actions, Python
"""


def main():
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(RESUME_TEXT)
            resume_path = f.name

        # Step 1: onboard_user with a real resume file
        r1_str = onboard_user(resume_path=resume_path)
        r1 = json.loads(r1_str)
        print("onboard_user response:", json.dumps(r1, indent=2))
        assert r1["status"] == "ok", f"Expected status='ok', got {r1['status']}"
        assert r1.get("next_action") == "compile_profile"
        assert "session_id" in r1

        # Step 2: compile_profile (generates its own session)
        r2_str = compile_profile()
        r2 = json.loads(r2_str)
        print("compile_profile response:", json.dumps(r2, indent=2))
        assert r2["status"] == "ok", f"Expected status='ok', got {r2['status']}"
        assert "compiled_profile" in r2.get("data", {})

        # Step 3: create_story with the current API
        r3_str = create_story(
            primary_skill="Terraform",
            skills=["Terraform", "AWS"],
            story_type="STAR",
            job_title="DevOps Engineer",
            situation="Team needed to migrate infrastructure to AWS.",
            behavior="I automated provisioning using Terraform modules.",
            impact="Reduced deployment time by 50%.",
        )
        r3 = json.loads(r3_str)
        print("create_story response:", json.dumps(r3, indent=2))
        assert r3["status"] == "ok", f"Expected status='ok', got {r3['status']}"
        assert r3.get("next_action") == "compile_profile"
        assert r3["data"]["needs_compile"] is True

        print("\nSMOKE OK: profile tools executed end-to-end")
        return 0
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
