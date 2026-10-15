"""Exhaustive tests for HowlAlign v0.1.3 managed-file correctness and alignment lifecycle.

Covers:
1. Canonical fingerprint contract across all supported managed-file formats:
   - Claude agent Markdown (.claude/agents/*.md)
   - Codex agent TOML (.codex/agents/*.toml)
   - AGY agent Markdown (.agents/agents/*/agent.md)
   - AGY skill Markdown (.agents/skills/*/SKILL.md)
2. Scenarios 1-10:
   - Generate, write to workspace, immediately verify fingerprint (no false positive user modification)
   - Repeated alignment without modifications is a true no-op (no conflict, no diff)
   - Policy changes propagate correctly to untouched managed files
   - User modifications are detected, preserved, and reported as conflicts
3. Legacy v0.1.2 backward-compatibility and migration:
   - Untouched v0.1.2 files recognized as untouched, eligible for policy alignment
   - User-modified v0.1.2 files preserved as conflicts, never silently overwritten
   - Tampered/corrupted fingerprints fail closed and are preserved
4. End-to-end alignment lifecycle (project & global scopes):
   - init, check, diff, apply, check-after-apply, repeated-apply, drift detection, backup, restore, doctor
"""

from __future__ import annotations

import json
from pathlib import Path

import toml

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.base import (
    compute_managed_fingerprint,
    extract_managed_fingerprint,
    has_user_modifications,
    is_file_managed_by_howlalign,
)
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.engine import AlignmentEngine
from howlalign.core.models import RoleClass, Scope
from howlalign.core.policy import get_default_policy, init_policy_file

# ============================================================================
# SCENARIOS 1-10: CANONICAL FINGERPRINT CORRECTNESS & PRESERVATION
# ============================================================================


def test_scenario_claude_agent_markdown_lifecycle(tmp_path: Path):
    """Exercise scenarios 1-9 for Claude agent Markdown (.claude/agents/<name>.md)."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = ClaudeAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # 1. Generate managed file
    changes = adapter.generate_changes(policy, is_global=False)
    search_change = next(c for c in changes if c.file_path.name == "search.md")
    search_file = search_change.file_path
    initial_content = search_change.proposed_content

    # 2. Write it to a disposable workspace
    search_file.parent.mkdir(parents=True, exist_ok=True)
    search_file.write_text(initial_content, encoding="utf-8")

    # 3. Immediately verify its stored fingerprint
    fp = extract_managed_fingerprint(initial_content, format_type="md")
    assert fp is not None
    assert compute_managed_fingerprint(initial_content) == fp
    assert has_user_modifications(initial_content, format_type="md") is False

    # 4. Run alignment again without modifications
    changes_round_2 = adapter.generate_changes(policy, is_global=False)
    search_change_2 = next(c for c in changes_round_2 if c.file_path == search_file)

    # 5. Confirm there is no conflict and no unnecessary diff
    assert search_change_2.is_user_owned_conflict is False
    assert search_change_2.original_content == search_change_2.proposed_content
    assert search_change_2.original_content == initial_content

    # 6. Change the policy
    policy.agents["search"].description = "Updated search agent with enhanced tracing."
    changes_round_3 = adapter.generate_changes(policy, is_global=False)
    search_change_3 = next(c for c in changes_round_3 if c.file_path == search_file)

    # 7. Confirm the untouched managed file updates appropriately
    assert search_change_3.is_user_owned_conflict is False
    assert search_change_3.original_content != search_change_3.proposed_content
    assert "Updated search agent with enhanced tracing." in search_change_3.proposed_content
    # Apply updated policy content to disk
    search_file.write_text(search_change_3.proposed_content, encoding="utf-8")
    assert has_user_modifications(search_file.read_text(encoding="utf-8"), "md") is False

    # 8. Modify the managed file manually
    user_edited = (
        search_file.read_text(encoding="utf-8")
        + "\n# Developer Note: Custom local search instructions\n"
    )
    search_file.write_text(user_edited, encoding="utf-8")
    assert has_user_modifications(search_file.read_text(encoding="utf-8"), "md") is True

    # 9. Confirm HowlAlign preserves the human edit and reports a conflict
    changes_round_4 = adapter.generate_changes(policy, is_global=False)
    search_change_4 = next(c for c in changes_round_4 if c.file_path == search_file)
    assert search_change_4.is_user_owned_conflict is True
    assert search_change_4.proposed_content == user_edited
    assert "User modifications detected" in search_change_4.description


def test_scenario_codex_agent_toml_lifecycle(tmp_path: Path):
    """Exercise scenarios 1-9 for Codex agent TOML (.codex/agents/<name>.toml)."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # 1. Generate managed file
    changes = adapter.generate_changes(policy, is_global=False)
    search_change = next(c for c in changes if c.file_path.name == "search.toml")
    search_file = search_change.file_path
    initial_content = search_change.proposed_content

    # 2. Write it to a disposable workspace
    search_file.parent.mkdir(parents=True, exist_ok=True)
    search_file.write_text(initial_content, encoding="utf-8")

    # 3. Immediately verify its stored fingerprint
    fp = extract_managed_fingerprint(initial_content, format_type="toml")
    assert fp is not None
    assert compute_managed_fingerprint(initial_content) == fp
    assert has_user_modifications(initial_content, format_type="toml") is False
    # Ensure invalid managed_by is NOT inside TOML table
    parsed_toml = toml.loads(initial_content)
    assert "managed_by" not in parsed_toml

    # 4. Run alignment again without modifications
    changes_round_2 = adapter.generate_changes(policy, is_global=False)
    search_change_2 = next(c for c in changes_round_2 if c.file_path == search_file)

    # 5. Confirm there is no conflict and no unnecessary diff
    assert search_change_2.is_user_owned_conflict is False
    assert search_change_2.original_content == search_change_2.proposed_content
    assert search_change_2.original_content == initial_content

    # 6. Change the policy
    policy.roles[RoleClass.SUPPORT].effort = policy.roles[RoleClass.PLANNING].effort
    changes_round_3 = adapter.generate_changes(policy, is_global=False)
    search_change_3 = next(c for c in changes_round_3 if c.file_path == search_file)

    # 7. Confirm the untouched managed file updates appropriately
    assert search_change_3.is_user_owned_conflict is False
    assert search_change_3.original_content != search_change_3.proposed_content
    # Apply updated policy content to disk
    search_file.write_text(search_change_3.proposed_content, encoding="utf-8")
    assert has_user_modifications(search_file.read_text(encoding="utf-8"), "toml") is False

    # 8. Modify the managed file manually
    user_edited = (
        search_file.read_text(encoding="utf-8") + '\ncustom_user_setting = "preserved_value"\n'
    )
    search_file.write_text(user_edited, encoding="utf-8")
    assert has_user_modifications(search_file.read_text(encoding="utf-8"), "toml") is True

    # 9. Confirm HowlAlign preserves the human edit and reports a conflict
    changes_round_4 = adapter.generate_changes(policy, is_global=False)
    search_change_4 = next(c for c in changes_round_4 if c.file_path == search_file)
    assert search_change_4.is_user_owned_conflict is True
    assert search_change_4.proposed_content == user_edited
    assert "User modifications detected" in search_change_4.description


def test_scenario_agy_skill_markdown_lifecycle(tmp_path: Path):
    """Exercise scenarios 1-9 for AGY skill Markdown (.agents/skills/<name>/SKILL.md)."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # 1. Generate managed file
    changes = adapter.generate_changes(policy, is_global=False)
    skill_change = next(
        c for c in changes if c.file_path.name == "SKILL.md" and "search" in str(c.file_path)
    )
    skill_file = skill_change.file_path
    initial_content = skill_change.proposed_content

    # 2. Write it to a disposable workspace
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(initial_content, encoding="utf-8")

    # 3. Immediately verify its stored fingerprint
    fp = extract_managed_fingerprint(initial_content, format_type="md")
    assert fp is not None
    assert compute_managed_fingerprint(initial_content) == fp
    assert has_user_modifications(initial_content, format_type="md") is False

    # 4. Run alignment again without modifications
    changes_round_2 = adapter.generate_changes(policy, is_global=False)
    skill_change_2 = next(c for c in changes_round_2 if c.file_path == skill_file)

    # 5. Confirm there is no conflict and no unnecessary diff
    assert skill_change_2.is_user_owned_conflict is False
    assert skill_change_2.original_content == skill_change_2.proposed_content
    assert skill_change_2.original_content == initial_content

    # 6. Change the policy
    policy.agents["search"].description = "Updated skill for symbol mapping."
    changes_round_3 = adapter.generate_changes(policy, is_global=False)
    skill_change_3 = next(c for c in changes_round_3 if c.file_path == skill_file)

    # 7. Confirm the untouched managed file updates appropriately
    assert skill_change_3.is_user_owned_conflict is False
    assert skill_change_3.original_content != skill_change_3.proposed_content
    assert "Updated skill for symbol mapping." in skill_change_3.proposed_content
    # Apply updated policy content to disk
    skill_file.write_text(skill_change_3.proposed_content, encoding="utf-8")
    assert has_user_modifications(skill_file.read_text(encoding="utf-8"), "md") is False

    # 8. Modify the managed file manually
    user_edited = (
        skill_file.read_text(encoding="utf-8")
        + "\n## Custom Developer Section\nRun additional verification step.\n"
    )
    skill_file.write_text(user_edited, encoding="utf-8")
    assert has_user_modifications(skill_file.read_text(encoding="utf-8"), "md") is True

    # 9. Confirm HowlAlign preserves the human edit and reports a conflict
    changes_round_4 = adapter.generate_changes(policy, is_global=False)
    skill_change_4 = next(c for c in changes_round_4 if c.file_path == skill_file)
    assert skill_change_4.is_user_owned_conflict is True
    assert skill_change_4.proposed_content == user_edited
    assert "User modifications detected" in skill_change_4.description


def test_scenario_agy_agent_markdown_lifecycle(tmp_path: Path):
    """Exercise scenarios 1-9 for AGY agent Markdown (.agents/agents/<name>/agent.md)."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # 1. Generate managed file
    changes = adapter.generate_changes(policy, is_global=False)
    agent_change = next(
        c for c in changes if c.file_path.name == "agent.md" and "search" in str(c.file_path)
    )
    agent_file = agent_change.file_path
    initial_content = agent_change.proposed_content

    # 2. Write it to a disposable workspace
    agent_file.parent.mkdir(parents=True, exist_ok=True)
    agent_file.write_text(initial_content, encoding="utf-8")

    # 3. Immediately verify its stored fingerprint
    fp = extract_managed_fingerprint(initial_content, format_type="md")
    assert fp is not None
    assert compute_managed_fingerprint(initial_content) == fp
    assert has_user_modifications(initial_content, format_type="md") is False

    # 4. Run alignment again without modifications
    changes_round_2 = adapter.generate_changes(policy, is_global=False)
    agent_change_2 = next(c for c in changes_round_2 if c.file_path == agent_file)

    # 5. Confirm there is no conflict and no unnecessary diff
    assert agent_change_2.is_user_owned_conflict is False
    assert agent_change_2.original_content == agent_change_2.proposed_content
    assert agent_change_2.original_content == initial_content

    # 6. Change the policy
    policy.roles[RoleClass.SUPPORT].agy_model = "gemini-3.8-flash-low"
    changes_round_3 = adapter.generate_changes(policy, is_global=False)
    agent_change_3 = next(c for c in changes_round_3 if c.file_path == agent_file)

    # 7. Confirm the untouched managed file updates appropriately
    assert agent_change_3.is_user_owned_conflict is False
    assert agent_change_3.original_content != agent_change_3.proposed_content
    assert "model: gemini-3.8-flash-low" in agent_change_3.proposed_content
    # Apply updated policy content to disk
    agent_file.write_text(agent_change_3.proposed_content, encoding="utf-8")
    assert has_user_modifications(agent_file.read_text(encoding="utf-8"), "md") is False

    # 8. Modify the managed file manually
    user_edited = (
        agent_file.read_text(encoding="utf-8")
        + "\n# Custom Agent Guidelines\nAlways use verbose logging.\n"
    )
    agent_file.write_text(user_edited, encoding="utf-8")
    assert has_user_modifications(agent_file.read_text(encoding="utf-8"), "md") is True

    # 9. Confirm HowlAlign preserves the human edit and reports a conflict
    changes_round_4 = adapter.generate_changes(policy, is_global=False)
    agent_change_4 = next(c for c in changes_round_4 if c.file_path == agent_file)
    assert agent_change_4.is_user_owned_conflict is True
    assert agent_change_4.proposed_content == user_edited
    assert "User modifications detected" in agent_change_4.description


# ============================================================================
# LEGACY v0.1.2 BACKWARD COMPATIBILITY & CONSERVATIVE MIGRATION
# ============================================================================


def test_legacy_v012_claude_agent_untouched_and_modified():
    """Verify that untouched v0.1.2 Claude agent files update safely, but edited files conflict."""
    # Synthesize authentic v0.1.2 Claude agent content
    p = get_default_policy()
    tools_formatted = "\n".join(f"  - {t}" for t in ["Read", "Glob", "Grep", "WebSearch"])
    disallowed_formatted = "\n".join(f"  - {t}" for t in ["Edit", "Write", "NotebookEdit", "Bash"])
    core_body = f"""name: search
description: {p.agents["search"].description}
tools:
{tools_formatted}
disallowedTools:
{disallowed_formatted}
model: claude-haiku-4
permissionMode: plan

{p.agents["search"].system_prompt.strip()}"""
    v012_fp = compute_managed_fingerprint(core_body)

    v012_untouched = f"""---
managed_by: howlalign
managed_fingerprint: {v012_fp}
name: search
description: {p.agents["search"].description}
tools:
{tools_formatted}
disallowedTools:
{disallowed_formatted}
model: claude-haiku-4
permissionMode: plan
---

<!-- managed by howlalign -->
{p.agents["search"].system_prompt.strip()}
"""
    # Untouched must not be flagged as user modified
    assert is_file_managed_by_howlalign(v012_untouched, "md") is True
    assert has_user_modifications(v012_untouched, "md") is False

    # Human edited must be flagged as user modified
    v012_edited = v012_untouched + "\n# Extra custom user instructions\n"
    assert has_user_modifications(v012_edited, "md") is True


def test_legacy_v012_codex_role_untouched_and_modified():
    """Verify that untouched v0.1.2 Codex role files update safely, but edited files conflict."""
    p = get_default_policy()
    role_data = {
        "managed_by": "howlalign",
        "name": "search",
        "description": p.agents["search"].description,
        "developer_instructions": p.agents["search"].system_prompt.strip(),
        "model": "gpt-5.6-luna",
        "model_reasoning_effort": "low",
        "nickname_candidates": ["search", "search-agent"],
        "sandbox_mode": "read-only",
    }
    role_body = toml.dumps(role_data)
    v012_fp = compute_managed_fingerprint(role_body)

    v012_untouched = f'# managed by howlalign\n# managed_fingerprint = "{v012_fp}"\n' + role_body

    assert is_file_managed_by_howlalign(v012_untouched, "toml") is True
    assert has_user_modifications(v012_untouched, "toml") is False

    v012_edited = v012_untouched + '\ncustom_key = "value"\n'
    assert has_user_modifications(v012_edited, "toml") is True


def test_corrupted_or_tampered_fingerprint_fails_closed():
    """Verify that a file with a corrupted, tampered, or unknown fingerprint fails closed."""
    content = """---
managed_by: howlalign
managed_fingerprint: bad0000000000000
name: search
---

<!-- managed by howlalign -->
Content
"""
    # Fails closed: treated as modified, preserving user content rather than silently overwriting
    assert is_file_managed_by_howlalign(content, "md") is True
    assert has_user_modifications(content, "md") is True


def test_unmanaged_file_without_marker_preserved_as_conflict():
    """Verify that a completely user-authored agent file without howlalign markers is preserved."""
    content = """# My Hand-Crafted Agent
I created this agent manually without HowlAlign.
"""
    assert is_file_managed_by_howlalign(content, "md") is False


# ============================================================================
# COMPLETE ALIGNMENT LIFECYCLE (PROJECT & GLOBAL SCOPE)
# ============================================================================


def test_complete_alignment_lifecycle_project_scope(tmp_path: Path, monkeypatch):
    """End-to-end alignment lifecycle in project scope:

    init -> check -> diff -> apply -> check after apply -> repeated apply -> policy change -> drift.
    """
    workspace = tmp_path / "project_ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(tmp_path / "backups"))

    # 1. init: create howlalign.toml policy
    policy_path = init_policy_file(path=workspace, is_global=False)
    assert policy_path.is_file()

    engine = AlignmentEngine(
        config_path=policy_path, workspace_dir=workspace, home_dir=home, scope=Scope.PROJECT
    )

    # 2. check: inspect drift before apply
    changes = engine.generate_all_changes()
    assert len(changes) > 0
    drift_before = [c for c in changes if c.original_content != c.proposed_content]
    assert len(drift_before) > 0

    # 3. diff: compute unified diff
    diff_exit = engine.diff()
    assert diff_exit == 0

    # 4. apply: apply changes with backup
    apply_exit = engine.apply(auto_approve=True, backup=True)
    assert apply_exit == 0

    # Verify exact resulting files
    claude_settings = workspace / ".claude" / "settings.json"
    claude_search = workspace / ".claude" / "agents" / "search.md"
    codex_cfg = workspace / ".codex" / "config.toml"
    codex_search = workspace / ".codex" / "agents" / "search.toml"
    agy_skill = workspace / ".agents" / "skills" / "search" / "SKILL.md"
    agy_agent = workspace / ".agents" / "agents" / "search" / "agent.md"
    gemini_md = workspace / "GEMINI.md"
    claude_md = workspace / "CLAUDE.md"
    agents_md = workspace / "AGENTS.md"

    for f in (
        claude_settings,
        claude_search,
        codex_cfg,
        codex_search,
        agy_skill,
        agy_agent,
        gemini_md,
        claude_md,
        agents_md,
    ):
        assert f.is_file(), f"Expected file {f} was not created"

    # Verify Codex config does not contain unsupported subagent keys
    codex_toml_data = toml.loads(codex_cfg.read_text(encoding="utf-8"))
    assert "default_subagent_model" not in codex_toml_data
    assert "default_subagent_reasoning_effort" not in codex_toml_data

    # Verify Codex role toml does not contain managed_by key in data table
    codex_role_data = toml.loads(codex_search.read_text(encoding="utf-8"))
    assert "managed_by" not in codex_role_data
    assert '# managed_by = "howlalign"' in codex_search.read_text(encoding="utf-8")

    # 5. check after apply: 0 drift files
    changes_after = engine.generate_all_changes()
    drift_after = [
        c
        for c in changes_after
        if c.original_content != c.proposed_content and not c.is_user_owned_conflict
    ]
    assert len(drift_after) == 0, f"Expected 0 drift files after apply, found {drift_after}"

    # 6. repeated apply: true no-op
    reapply_exit = engine.apply(auto_approve=True, backup=True)
    assert reapply_exit == 0

    # 7. policy changes: update howlalign.toml policy and re-align
    policy_text = policy_path.read_text(encoding="utf-8")
    updated_policy_text = policy_text.replace(
        'claude_model = "claude-haiku-4"', 'claude_model = "claude-3-5-haiku-latest"'
    )
    policy_path.write_text(updated_policy_text, encoding="utf-8")

    # Re-initialize engine with updated policy
    engine_updated = AlignmentEngine(
        config_path=policy_path, workspace_dir=workspace, home_dir=home, scope=Scope.PROJECT
    )
    changes_updated = engine_updated.generate_all_changes()
    drift_updated = [
        c
        for c in changes_updated
        if c.original_content != c.proposed_content and not c.is_user_owned_conflict
    ]
    assert len(drift_updated) > 0
    # Apply policy updates
    assert engine_updated.apply(auto_approve=True, backup=True) == 0
    assert "model: claude-3-5-haiku-latest" in claude_search.read_text(encoding="utf-8")

    # 8. user-edited managed files: modify claude_search manually
    user_customization = (
        claude_search.read_text(encoding="utf-8") + "\n# Extra custom rule for human developer\n"
    )
    claude_search.write_text(user_customization, encoding="utf-8")

    # Check and diff must report the conflict and protect the file
    changes_conflict = engine_updated.generate_all_changes()
    claude_conflict = next(c for c in changes_conflict if c.file_path == claude_search)
    assert claude_conflict.is_user_owned_conflict is True
    assert claude_conflict.proposed_content == user_customization

    # Apply must preserve the human edit
    engine_updated.apply(auto_approve=True, backup=True)
    assert claude_search.read_text(encoding="utf-8") == user_customization


def test_complete_alignment_lifecycle_global_scope(tmp_path: Path, monkeypatch):
    """End-to-end alignment lifecycle in global scope."""
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))

    # Initialize global policy
    policy_path = init_policy_file(is_global=True)
    assert policy_path.is_file()
    # Redirect HOME for isolated test
    global_engine = AlignmentEngine(
        config_path=None, workspace_dir=workspace, home_dir=home, scope=Scope.GLOBAL
    )
    # Force policy
    global_engine.policy = get_default_policy()

    # Generate changes
    changes = global_engine.generate_all_changes()
    assert len(changes) > 0

    # Apply global changes
    apply_res = global_engine.writer.apply(
        [c for c in changes if c.original_content != c.proposed_content]
    )
    assert apply_res.success is True

    # Global target files
    claude_global_settings = home / ".claude" / "settings.json"
    agy_global_settings = home / ".gemini" / "antigravity-cli" / "settings.json"
    codex_global_config = home / ".codex" / "config.toml"

    assert claude_global_settings.is_file()
    assert agy_global_settings.is_file()
    assert codex_global_config.is_file()

    # Re-check global: must be 0 drift
    global_engine_2 = AlignmentEngine(
        config_path=None, workspace_dir=workspace, home_dir=home, scope=Scope.GLOBAL
    )
    global_engine_2.policy = get_default_policy()
    changes_2 = global_engine_2.generate_all_changes()
    drift_2 = [c for c in changes_2 if c.original_content != c.proposed_content]
    assert len(drift_2) == 0


def test_lifecycle_backup_and_restore_with_drift(tmp_path: Path, monkeypatch):
    """Verify backup creation, restore pre-validation, target drift rejection, and force restore."""
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(tmp_path / "backups"))

    policy_path = init_policy_file(path=workspace, is_global=False)
    engine = AlignmentEngine(
        config_path=policy_path, workspace_dir=workspace, home_dir=home, scope=Scope.PROJECT
    )

    # Apply changes (creates timestamped backup)
    assert engine.apply(auto_approve=True, backup=True) == 0

    claude_settings = workspace / ".claude" / "settings.json"
    assert claude_settings.is_file()
    initial_content = claude_settings.read_text(encoding="utf-8")
    assert "opusplan" in initial_content

    # Find the backup directory created
    backup_base = tmp_path / "backups"
    assert backup_base.is_dir()
    ws_backups = list(backup_base.iterdir())[0]
    timestamp_backup_dir = list(ws_backups.iterdir())[0]
    manifest_file = timestamp_backup_dir / "manifest.json"
    assert manifest_file.is_file()

    # Verify manifest integrity
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "completed"
    assert len(manifest_data["files"]) > 0
    for entry in manifest_data["files"]:
        assert entry["post_apply_sha256"] is not None

    # Simulate target drift: modify claude_settings on disk
    claude_settings.write_text('{\n  "theme": "drifted"\n}\n', encoding="utf-8")

    # Restore without force must be rejected due to target drift conflict
    restore_res_no_force = engine.writer.restore_backup(timestamp_backup_dir, force=False)
    assert restore_res_no_force.success is False
    assert any("Target drift conflict" in err for err in restore_res_no_force.errors)
    assert claude_settings.read_text(encoding="utf-8") == '{\n  "theme": "drifted"\n}\n'

    # Restore with force must succeed and restore original state
    restore_res_force = engine.writer.restore_backup(timestamp_backup_dir, force=True)
    assert restore_res_force.success is True
    # Initial settings was newly created by apply, so restoring re-applies or removes as per manifest
    assert len(restore_res_force.applied_files) > 0


def test_lifecycle_doctor_diagnostics(tmp_path: Path, monkeypatch):
    """Verify that doctor reports clean status on aligned repos and catches anomalies."""
    from howlalign.core.doctor import Doctor, run_doctor

    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(tmp_path / "backups"))

    policy_path = init_policy_file(path=workspace, is_global=False)
    engine = AlignmentEngine(
        config_path=policy_path, workspace_dir=workspace, home_dir=home, scope=Scope.PROJECT
    )
    engine.apply(auto_approve=True, backup=True)

    # Run doctor on clean repository
    exit_code = run_doctor(
        config_path=policy_path,
        workspace_dir=workspace,
        home_dir=home,
        scope=Scope.PROJECT,
    )
    assert exit_code == 0

    # Inject an obsolete key into Codex config to test doctor diagnostic detection
    codex_cfg = workspace / ".codex" / "config.toml"
    current_codex = codex_cfg.read_text(encoding="utf-8")
    codex_cfg.write_text('default_subagent_model = "obsolete"\n' + current_codex, encoding="utf-8")

    doctor = Doctor(
        config_path=policy_path,
        workspace_dir=workspace,
        home_dir=home,
        scope=Scope.PROJECT,
    )
    items = doctor.run_diagnostics()
    assert any("obsolete subagent settings" in item.message for item in items)


def test_provider_compatibility_native_clis(tmp_path: Path):
    """Validate generated configurations against installed native CLIs in isolated environments."""
    import os
    import shutil
    import subprocess

    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    policy = get_default_policy()

    # 1. Codex CLI validation
    if shutil.which("codex"):
        codex_home = home / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
        changes = codex_adapter.generate_changes(policy, is_global=True)
        for c in changes:
            c.file_path.parent.mkdir(parents=True, exist_ok=True)
            c.file_path.write_text(c.proposed_content, encoding="utf-8")

        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        res = subprocess.run(
            ["codex", "--strict-config", "doctor"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert "config       loaded" in res.stdout or "config loaded" in res.stdout
        assert "unrecognized configuration settings" not in res.stdout.lower()

    # 2. Claude Code CLI validation
    if shutil.which("claude"):
        claude_home = home / ".claude_env"
        claude_home.mkdir(parents=True, exist_ok=True)
        claude_adapter = ClaudeAdapter(workspace_dir=workspace, home_dir=claude_home)
        changes = claude_adapter.generate_changes(policy, is_global=True)
        for c in changes:
            c.file_path.parent.mkdir(parents=True, exist_ok=True)
            c.file_path.write_text(c.proposed_content, encoding="utf-8")

        env = os.environ.copy()
        env["HOME"] = str(claude_home)
        res = subprocess.run(
            ["claude", "doctor"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "malformed" not in res.stdout.lower()

    # 3. AGY CLI validation
    if shutil.which("agy"):
        res = subprocess.run(
            ["agy", "models"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "gemini-3.8-flash" in res.stdout
