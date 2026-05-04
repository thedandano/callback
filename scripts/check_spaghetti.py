#!/usr/bin/env python3
"""Wrapper for spaghetti-score CLI that enforces a quality gate."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def resolve_repo_root(repo_arg=None):
    """Resolve repo root: use argument if provided, else discover from script location."""
    if repo_arg:
        return Path(repo_arg).resolve()
    # Auto-discover: parent of scripts/ directory
    script_dir = Path(__file__).parent
    return script_dir.parent


def main():
    parser = argparse.ArgumentParser(description="Check spaghetti-score and enforce quality gate")
    parser.add_argument(
        "--threshold",
        type=int,
        default=20,
        help="Score threshold; exit 0 if score < threshold (default: 20)",
    )
    parser.add_argument(
        "repo",
        nargs="?",
        help="Repository root to scan (optional; auto-discovered if not provided)",
    )
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo)
    threshold = args.threshold

    # Invoke ai-slop-score CLI
    spaghetti_script = Path(
        "/Users/dandano/.claude/skills/ai-slop-score/scripts/spaghetti_score.py"
    )
    try:
        result = subprocess.run(
            ["python3", str(spaghetti_script), str(repo_root)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        print(f"error: failed to invoke spaghetti-score: {e}", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print(f"error: spaghetti-score exited with code {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"error: failed to parse JSON output: {e}", file=sys.stderr)
        print(f"stdout: {result.stdout}", file=sys.stderr)
        sys.exit(1)

    score = output.get("score")
    band = output.get("band")

    if score is None or band is None:
        print("error: missing 'score' or 'band' in output", file=sys.stderr)
        sys.exit(1)

    # Print result
    print(f"score={score} band={band}")

    # Exit based on threshold
    if score < threshold:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
