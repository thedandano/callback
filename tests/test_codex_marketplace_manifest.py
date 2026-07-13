import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_codex_marketplace_manifest_matches_expected():
    manifest = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert manifest == {
        "name": "callback",
        "plugins": [
            {
                "name": "callback",
                "description": (
                    "Job application MCP workflows: profile onboarding, "
                    "resume tailoring, lead scanning, application review."
                ),
                "source": {"source": "local", "path": "./"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def test_codex_marketplace_description_matches_claude_marketplace():
    codex = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    claude = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert codex["plugins"][0]["description"] == claude["plugins"][0]["description"]
