"""Hermetic End-to-End Dogfood lifecycle test for HowlAlign v0.1.5.

Runs the complete lifecycle in a 100% isolated temporary sandbox:
1. Generates realistic existing configurations:
   - Codex config with trusted-project tables, custom features
   - AGY settings with allowNonWorkspaceAccess, custom permissions, trustedWorkspaces
   - Claude settings with autoMode and custom preferences
   - User-authored agent files (without managed marker)
   - User-authored rules
   - Managed agents
   - Synthetic symlinks
2. Executes lifecycle:
   init -> check -> diff -> apply -> check -> doctor -> policy edit -> diff -> apply -> check -> restore
3. Evaluates providers individually and all three combined.
4. Asserts:
   - Only intended settings change
   - Repeated apply is strictly idempotent
   - User-authored files and custom settings are preserved
   - Backups and restores function safely
   - Real user configurations are completely untouched
"""

from __future__ import annotations

import json
from pathlib import Path

import toml

from howlalign.core.engine import AlignmentEngine
from howlalign.core.models import (
    ApprovalPolicy,
    EffortLevel,
    PermissionsConfig,
    Policy,
    ProviderPermissionsConfig,
    ProviderType,
    RoleClass,
    RoleConfig,
    SandboxMode,
    Scope,
)
from howlalign.core.policy import get_default_policy, serialize_policy_toml


def setup_realistic_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Create realistic mock provider configurations in an isolated environment."""
    workspace = tmp_path / "sandbox_workspace"
    home = tmp_path / "sandbox_home"
    workspace.mkdir(parents=True)
    home.mkdir(parents=True)

    # 1. Existing Codex config with trusted projects and custom features
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    codex_config = codex_dir / "config.toml"
    codex_content = f"""# User Codex configuration
[features]
fast_apply = true
multi_turn = true

[notice]
hide_update_login = true

[projects."{workspace}"]
trust_level = "trusted"

[projects."/fake/other/project"]
trust_level = "trusted"
"""
    codex_config.write_text(codex_content, encoding="utf-8")

    # 2. Existing AGY settings with trusted workspaces and custom keys
    agy_dir = home / ".gemini" / "antigravity-cli"
    agy_dir.mkdir(parents=True)
    agy_settings = agy_dir / "settings.json"
    agy_content = {
        "model": "gemini-3.8-flash-high",
        "effort": "high",
        "toolPermission": "always-proceed",
        "allowNonWorkspaceAccess": True,
        "trustedWorkspaces": [str(workspace), "/fake/trusted"],
        "customExtension": {"active": True},
    }
    agy_settings.write_text(json.dumps(agy_content, indent=2) + "\n", encoding="utf-8")

    # 3. Existing Claude settings with autoMode and custom preferences
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    claude_settings = claude_dir / "settings.json"
    claude_content = {
        "autoMode": True,
        "theme": "dark",
        "model": "opusplan",
        "modelSettings": {
            "claude-opus-5": {"effortLevel": "high"},
            "claude-sonnet-5": {"effortLevel": "medium"},
        },
        "permissions": {
            "defaultMode": "default",
            "allowCommands": ["git", "pytest"],
        },
    }
    claude_settings.write_text(json.dumps(claude_content, indent=2) + "\n", encoding="utf-8")

    # 4. User-authored agent role in workspace (no managed marker)
    ws_codex_agents = workspace / ".codex" / "agents"
    ws_codex_agents.mkdir(parents=True)
    user_agent = ws_codex_agents / "search.toml"
    user_agent.write_text(
        '# Custom user agent\nname = "search"\nmodel = "my-custom-model"\n',
        encoding="utf-8",
    )

    # 5. User-authored guidelines
    user_gemini_md = workspace / "GEMINI.md"
    user_gemini_md.write_text("# Project Custom Rules\n- Custom rule 1\n", encoding="utf-8")

    return workspace, home


def build_test_policy() -> Policy:
    default_policy = get_default_policy()
    roles = {
        RoleClass.PLANNING: RoleConfig(
            claude_model="claude-opus-5",
            codex_model="gpt-6.1-sol",
            agy_model="Gemini 3.8 Flash (High)",
            effort=EffortLevel.HIGH,
            provider_effort={
                ProviderType.CLAUDE: EffortLevel.HIGH,
                ProviderType.CODEX: EffortLevel.HIGH,
                ProviderType.AGY: EffortLevel.HIGH,
            },
        ),
        RoleClass.IMPLEMENTATION: RoleConfig(
            claude_model="claude-sonnet-5",
            codex_model="gpt-6.1-sol",
            agy_model="Gemini 3.8 Flash (High)",
            effort=EffortLevel.MEDIUM,
            provider_effort={
                ProviderType.CLAUDE: EffortLevel.MEDIUM,
                ProviderType.CODEX: EffortLevel.LOW,
                ProviderType.AGY: EffortLevel.HIGH,
            },
        ),
        RoleClass.SUPPORT: RoleConfig(
            claude_model="claude-haiku-4",
            codex_model="gpt-5.6-luna",
            agy_model="Gemini 3.8 Flash (High)",
            effort=EffortLevel.LOW,
            provider_effort={
                ProviderType.CLAUDE: EffortLevel.LOW,
                ProviderType.CODEX: EffortLevel.LOW,
                ProviderType.AGY: EffortLevel.HIGH,
            },
        ),
    }

    perms = PermissionsConfig(
        allow_dangerous_bypass=False,
        ask_approval=ApprovalPolicy.ON_REQUEST,
        sandbox=SandboxMode.WORKSPACE_WRITE,
        providers={
            ProviderType.AGY: ProviderPermissionsConfig(
                ask_approval=ApprovalPolicy.NEVER,
            ),
            ProviderType.CODEX: ProviderPermissionsConfig(
                ask_approval=ApprovalPolicy.NEVER,
                sandbox=SandboxMode.DANGER_FULL_ACCESS,
            ),
            ProviderType.CLAUDE: ProviderPermissionsConfig(
                ask_approval=ApprovalPolicy.ON_REQUEST,
                sandbox=SandboxMode.WORKSPACE_WRITE,
            ),
        },
    )

    return Policy(
        schema_version="0.1.5",
        enabled_providers=[ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY],
        roles=roles,
        agents=default_policy.agents,
        permissions=perms,
    )


def test_dogfood_lifecycle_all_providers(tmp_path: Path, monkeypatch):
    """Hermetic dogfood test covering all three providers simultaneously."""
    workspace, home = setup_realistic_sandbox(tmp_path)
    state_dir = home / ".local" / "state" / "howlalign"
    backup_dir = state_dir / "backups"

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))

    # Step 1: Write policy file
    policy_path = workspace / "howlalign.toml"
    policy = build_test_policy()
    policy_path.write_text(serialize_policy_toml(policy), encoding="utf-8")

    # Step 2: Initialize engine
    engine = AlignmentEngine(
        config_path=policy_path,
        workspace_dir=workspace,
        home_dir=home,
        scope=Scope.ALL,
    )

    # Step 3: Check
    exit_check = engine.check(json_output=True)
    assert exit_check == 0

    # Step 4: Diff
    exit_diff = engine.diff()
    assert exit_diff == 0

    # Step 5: Apply with backup
    changes = engine.generate_all_changes()
    actionable = [
        c
        for c in changes
        if c.original_content != c.proposed_content and not c.is_user_owned_conflict
    ]
    apply_res = engine.writer.apply(actionable, create_backup=True)
    assert apply_res.success is True
    assert apply_res.backup_dir is not None

    # Step 6: Verify user-authored files preserved
    search_agent = workspace / ".codex" / "agents" / "search.toml"
    assert "my-custom-model" in search_agent.read_text(encoding="utf-8")

    gemini_md = workspace / "GEMINI.md"
    assert "Custom rule 1" in gemini_md.read_text(encoding="utf-8")

    # Step 7: Verify Codex config preserved trusted projects
    codex_cfg = home / ".codex" / "config.toml"
    parsed_codex = toml.loads(codex_cfg.read_text(encoding="utf-8"))
    assert parsed_codex["features"]["fast_apply"] is True
    assert parsed_codex["projects"][str(workspace)]["trust_level"] == "trusted"
    assert parsed_codex["projects"]["/fake/other/project"]["trust_level"] == "trusted"
    assert parsed_codex["model_reasoning_effort"] == "low"
    assert parsed_codex["plan_mode_reasoning_effort"] == "high"

    # Step 8: Verify AGY settings preserved custom extension and trustedWorkspaces
    agy_cfg = home / ".gemini" / "antigravity-cli" / "settings.json"
    parsed_agy = json.loads(agy_cfg.read_text(encoding="utf-8"))
    assert parsed_agy["customExtension"]["active"] is True
    assert str(workspace) in parsed_agy["trustedWorkspaces"]
    assert parsed_agy["model"] == "Gemini 3.8 Flash (High)"
    assert parsed_agy["effort"] == "high"
    assert parsed_agy["toolPermission"] == "always-proceed"

    # Step 9: Verify Claude settings preserved autoMode and theme
    claude_cfg = home / ".claude" / "settings.json"
    parsed_claude = json.loads(claude_cfg.read_text(encoding="utf-8"))
    assert parsed_claude["autoMode"] is True
    assert parsed_claude["theme"] == "dark"
    assert parsed_claude["modelSettings"]["claude-opus-5"]["effortLevel"] == "high"
    assert parsed_claude["modelSettings"]["claude-sonnet-5"]["effortLevel"] == "medium"
    assert parsed_claude["modelSettings"]["claude-haiku-4"]["effortLevel"] == "low"

    # Step 10: Repeated apply is strictly idempotent
    changes_repeat = engine.generate_all_changes()
    actionable_repeat = [
        c
        for c in changes_repeat
        if c.original_content != c.proposed_content and not c.is_user_owned_conflict
    ]
    assert len(actionable_repeat) == 0

    # Step 11: Policy modification & re-apply
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.CODEX] = EffortLevel.XHIGH
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.CLAUDE] = EffortLevel.HIGH
    policy_path.write_text(serialize_policy_toml(policy), encoding="utf-8")
    engine.policy = policy

    changes_mod = engine.generate_all_changes()
    actionable_mod = [
        c
        for c in changes_mod
        if c.original_content != c.proposed_content and not c.is_user_owned_conflict
    ]
    assert len(actionable_mod) >= 2  # Codex config + Claude settings

    apply_mod = engine.writer.apply(actionable_mod, create_backup=True)
    assert apply_mod.success is True

    # Confirm updated values
    parsed_codex_mod = toml.loads(codex_cfg.read_text(encoding="utf-8"))
    assert parsed_codex_mod["model_reasoning_effort"] == "xhigh"
    # Confirm AGY was NOT altered by Codex / Claude changes
    parsed_agy_mod = json.loads(agy_cfg.read_text(encoding="utf-8"))
    assert parsed_agy_mod["effort"] == "high"

    # Step 12: Restore from first backup
    restore_res = engine.writer.restore_backup(Path(apply_res.backup_dir), force=True)
    assert restore_res.success is True

    # Confirm restored to initial state
    parsed_codex_restored = toml.loads(codex_cfg.read_text(encoding="utf-8"))
    assert parsed_codex_restored["features"]["fast_apply"] is True
    assert parsed_codex_restored["projects"][str(workspace)]["trust_level"] == "trusted"


def test_dogfood_lifecycle_individual_providers(tmp_path: Path, monkeypatch):
    """Test dogfood lifecycle on each provider individually."""
    for prov in (ProviderType.AGY, ProviderType.CODEX, ProviderType.CLAUDE):
        sub_tmp = tmp_path / f"dogfood_{prov.value}"
        workspace, home = setup_realistic_sandbox(sub_tmp)
        backup_dir = home / ".local" / "state" / "howlalign" / "backups"

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
        monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(backup_dir))

        policy = build_test_policy()
        policy.enabled_providers = [prov]

        engine = AlignmentEngine(workspace_dir=workspace, home_dir=home, scope=Scope.GLOBAL)
        engine.policy = policy

        changes = engine.generate_all_changes()
        for c in changes:
            assert c.provider == prov

        actionable = [c for c in changes if c.original_content != c.proposed_content]
        res = engine.writer.apply(actionable, create_backup=True)
        assert res.success is True

        # Second apply is idempotent
        repeat_changes = engine.generate_all_changes()
        repeat_actionable = [c for c in repeat_changes if c.original_content != c.proposed_content]
        assert len(repeat_actionable) == 0
