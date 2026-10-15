"""Tests for Claude, Codex, and AGY native provider adapters."""

import json
from pathlib import Path

import toml

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.policy import get_default_policy


def test_claude_adapter_generation_and_preservation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    # Pre-create an existing .claude/settings.json with unrelated settings
    claude_dir = workspace / ".claude"
    claude_dir.mkdir()
    existing_settings_file = claude_dir / "settings.json"
    existing_settings = {
        "theme": "dark",
        "customEnv": {"FOO": "BAR"},
        "mcpServers": {"local-db": {"command": "sqlite"}},
    }
    existing_settings_file.write_text(json.dumps(existing_settings, indent=2), encoding="utf-8")

    adapter = ClaudeAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    changes = adapter.generate_changes(policy, is_global=False)
    assert len(changes) >= 4  # settings.json, search.md, tests.md, docs.md, CLAUDE.md

    # Verify settings preservation
    settings_change = next(c for c in changes if c.file_path == existing_settings_file)
    parsed = json.loads(settings_change.proposed_content)
    assert parsed["theme"] == "dark"
    assert parsed["customEnv"] == {"FOO": "BAR"}
    assert parsed["mcpServers"] == {"local-db": {"command": "sqlite"}}
    assert parsed["model"] == "opusplan"
    assert "permissions" in parsed
    assert "modelSettings" in parsed

    # Verify agent markdown definitions
    search_change = next(c for c in changes if c.file_path.name == "search.md")
    assert "name: search" in search_change.proposed_content
    assert "permissionMode: plan" in search_change.proposed_content
    assert "disallowedTools:" in search_change.proposed_content
    assert "Edit" in search_change.proposed_content

    tests_change = next(c for c in changes if c.file_path.name == "tests.md")
    assert "name: tests" in tests_change.proposed_content
    assert "Bash" in tests_change.proposed_content

    # Verify CLAUDE.md
    claude_md_change = next(c for c in changes if c.file_path.name == "CLAUDE.md")
    assert "HowlAlign" in claude_md_change.proposed_content


def test_codex_adapter_generation_and_preservation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    # Pre-create existing .codex/config.toml with unrelated tables
    codex_dir = workspace / ".codex"
    codex_dir.mkdir()
    existing_cfg_file = codex_dir / "config.toml"
    existing_toml = """
    project_doc_max_bytes = 40960

    [features]
    fast_apply = true
    """
    existing_cfg_file.write_text(existing_toml, encoding="utf-8")

    adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    changes = adapter.generate_changes(policy, is_global=False)
    assert len(changes) >= 4  # config.toml, search.toml, tests.toml, docs.toml, AGENTS.md

    # Check TOML config update and preservation
    cfg_change = next(c for c in changes if c.file_path == existing_cfg_file)
    parsed = toml.loads(cfg_change.proposed_content)
    assert parsed.get("project_doc_max_bytes") == 40960
    assert parsed.get("features", {}).get("fast_apply") is True
    assert parsed.get("model") == "gpt-6.1-sol"
    assert parsed.get("sandbox_mode") == "workspace-write"
    assert "agents" in parsed
    assert "search" in parsed["agents"]

    # Check dedicated role TOML
    search_role_change = next(c for c in changes if c.file_path.name == "search.toml")
    parsed_role = toml.loads(search_role_change.proposed_content)
    assert parsed_role["name"] == "search"
    assert "developer_instructions" in parsed_role
    assert parsed_role["model_reasoning_effort"] == "low"

    # Check AGENTS.md
    agents_md_change = next(c for c in changes if c.file_path.name == "AGENTS.md")
    assert "AGENTS.md" in agents_md_change.proposed_content


def test_agy_adapter_generation(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # Project workspace changes
    changes = adapter.generate_changes(policy, is_global=False)

    # Check skill generation
    skill_change = next(
        c for c in changes if c.file_path.name == "SKILL.md" and "search" in str(c.file_path)
    )
    assert "name: search" in skill_change.proposed_content

    # Check subagent generation
    agent_change = next(
        c for c in changes if c.file_path.name == "agent.md" and "tests" in str(c.file_path)
    )
    assert "name: tests" in agent_change.proposed_content
    assert "subagent: true" in agent_change.proposed_content

    # Check GEMINI.md
    gemini_change = next(c for c in changes if c.file_path.name == "GEMINI.md")
    assert "GEMINI.md" in gemini_change.file_path.name
    assert "HowlAlign" in gemini_change.proposed_content

    # Global settings generation
    global_changes = adapter.generate_changes(policy, is_global=True)
    global_settings_change = next(c for c in global_changes if c.file_path.name == "settings.json")
    parsed_global = json.loads(global_settings_change.proposed_content)
    assert parsed_global["model"] == "gemini-3.8-flash-high"
    assert parsed_global["toolPermission"] == "proceed-in-sandbox"
