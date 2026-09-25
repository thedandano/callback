import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_hermes_plugin_manifest_matches_expected():
    manifest = json.loads((REPO_ROOT / "plugin.json").read_text())
    claude = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert manifest == {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "callback",
        "version": claude["version"],
        "description": claude["description"],
        "author": claude["author"],
        "homepage": claude["homepage"],
        "repository": "https://github.com/thedandano/callback",
        "license": claude["license"],
        "keywords": claude["keywords"],
    }


def test_hermes_mcp_manifest_matches_dot_mcp_json():
    hermes_mcp = json.loads((REPO_ROOT / "mcp.json").read_text())
    dot_mcp = json.loads((REPO_ROOT / ".mcp.json").read_text())
    assert hermes_mcp == {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {
            "callback": {
                "type": "stdio",
                "command": dot_mcp["mcpServers"]["callback"]["command"],
                "args": dot_mcp["mcpServers"]["callback"]["args"],
            }
        },
    }


def test_hermes_plugin_version_tracked_by_release_please():
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text())
    extra_files = config["packages"]["."]["extra-files"]
    assert {"type": "json", "path": "plugin.json", "jsonpath": "$.version"} in extra_files
