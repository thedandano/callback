#!/usr/bin/env python3
"""Smoke test for the profile MCP tools: onboard_user, compile_profile, create_story."""
import json
import sys
import os

# Add current directory to path for running via uv
sys.path.insert(0, os.getcwd())

from pi_apply.server import onboard_user, compile_profile, create_story


def main():
    try:
        # Step 1: onboard_user (creates a new profile session)
        r1_str = onboard_user()
        r1 = json.loads(r1_str)
        print("onboard_user response:", json.dumps(r1, indent=2))
        assert r1["status"] == "ok", f"Expected status='ok', got {r1['status']}"
        assert "session_id" in r1, "Missing session_id in onboard_user response"

        # Step 2: compile_profile (generates its own session)
        r2_str = compile_profile()
        r2 = json.loads(r2_str)
        print("compile_profile response:", json.dumps(r2, indent=2))
        assert r2["status"] == "ok", f"Expected status='ok', got {r2['status']}"

        # Step 3: create_story (generates its own session)
        r3_str = create_story(
            skill="terraform",
            story_type="project",
            job_title="DevOps Engineer",
            situation="Team needed to migrate infrastructure",
            behavior="I automated AWS provisioning using Terraform",
            impact="Reduced deployment time by 50%"
        )
        r3 = json.loads(r3_str)
        print("create_story response:", json.dumps(r3, indent=2))
        assert r3["status"] == "ok", f"Expected status='ok', got {r3['status']}"

        print("\nSMOKE OK: profile tools executed end-to-end")
        return 0
    except Exception as e:
        print(f"SMOKE FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
