import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
MCP = PLUGIN / ".mcp.json"
SKILL = PLUGIN / "skills" / "witness" / "SKILL.md"
COMMAND = PLUGIN / "commands" / "witness.md"

PLUGIN_FILES = [MANIFEST, MCP, SKILL, COMMAND]


def test_manifest_json_valid():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["name"] == "witness"


def test_mcp_json_command():
    data = json.loads(MCP.read_text(encoding="utf-8"))
    server = data["mcpServers"]["witness"]
    assert server["command"] == "witness"
    assert server["args"] == ["mcp"]


def test_commands_present():
    text = COMMAND.read_text(encoding="utf-8")
    assert "/witness <pr>" in text
    assert "explain <hunk>" in text
    assert "paths <hunk>" in text


def test_skill_frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert re.search(r"^name: witness$", frontmatter, re.MULTILINE)
    assert re.search(r"^description: .+", frontmatter, re.MULTILINE)


def test_no_credentials_in_plugin_files():
    secret = re.compile(r"sk-ant-|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY")
    for path in PLUGIN_FILES:
        assert not secret.search(path.read_text(encoding="utf-8")), path
