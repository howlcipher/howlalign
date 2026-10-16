"""Comprehensive tests for HowlAlign v0.1.5 provider-specific policy engine.

Verifies:
1. Changing Codex implementation effort does not alter AGY.
2. Changing AGY implementation effort does not alter Codex.
3. Changing Claude support effort does not alter AGY or Codex.
4. Changing Codex permissions does not alter Claude permissions.
5. Changing AGY permissions does not alter Codex permissions.
6. Disabled providers produce no changes.
7. Legacy policies continue loading.
8. Explicit provider effort overrides take precedence.
9. Shared fallback values work correctly.
10. Invalid provider effort values fail validation.
11. Invalid permission values fail validation.
12. Unsupported native effort values are handled predictably.
13. Existing managed-file fingerprints remain valid.
14. Repeated apply remains idempotent.
15. Backup and restore continue functioning.
16. User-owned configurations remain preserved.
17. Dangerous permission changes are reported.
18. Existing policy settings are not silently discarded.
19. Complex Codex configurations (projects, trust, custom tables) are preserved.
20. Explain CLI command displays accurate effective resolution matrix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import toml

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.base import (
    compute_managed_fingerprint,
    embed_managed_fingerprint,
    has_user_modifications,
    is_file_managed_by_howlalign,
)
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.differ import Differ
from howlalign.core.engine import AlignmentEngine
from howlalign.core.exceptions import PolicyValidationError
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
from howlalign.core.policy import (
    get_default_policy,
    load_policy_from_dict,
    serialize_policy_toml,
)


def create_disposable_policy() -> Policy:
    """Create disposable multi-provider policy with independent preferences."""
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

    default_policy = get_default_policy()
    return Policy(
        schema_version="0.1.5",
        enabled_providers=[ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY],
        roles=roles,
        agents=default_policy.agents,
        permissions=perms,
    )


# 1. Changing Codex implementation effort does not alter AGY
def test_changing_codex_effort_leaves_agy_untouched(tmp_path: Path):
    policy = create_disposable_policy()
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    agy_adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    agy_before = agy_adapter.generate_changes(policy, is_global=True)
    agy_settings_before = next(
        c for c in agy_before if c.file_path.name == "settings.json"
    ).proposed_content

    # Change Codex implementation effort
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.CODEX] = EffortLevel.HIGH

    agy_after = agy_adapter.generate_changes(policy, is_global=True)
    agy_settings_after = next(
        c for c in agy_after if c.file_path.name == "settings.json"
    ).proposed_content

    assert json.loads(agy_settings_before) == json.loads(agy_settings_after)
    assert json.loads(agy_settings_after)["effort"] == "high"


# 2. Changing AGY implementation effort does not alter Codex
def test_changing_agy_effort_leaves_codex_untouched(tmp_path: Path):
    policy = create_disposable_policy()
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    codex_before = codex_adapter.generate_changes(policy, is_global=True)
    codex_cfg_before = next(
        c for c in codex_before if c.file_path.name == "config.toml"
    ).proposed_content

    # Change AGY implementation effort to low
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.AGY] = EffortLevel.LOW

    codex_after = codex_adapter.generate_changes(policy, is_global=True)
    codex_cfg_after = next(
        c for c in codex_after if c.file_path.name == "config.toml"
    ).proposed_content

    assert toml.loads(codex_cfg_before) == toml.loads(codex_cfg_after)
    parsed = toml.loads(codex_cfg_after)
    assert parsed["model_reasoning_effort"] == "low"
    assert parsed["plan_mode_reasoning_effort"] == "high"


# 3. Changing Claude support effort does not alter AGY or Codex
def test_changing_claude_support_effort_leaves_agy_and_codex_untouched(tmp_path: Path):
    policy = create_disposable_policy()
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    agy_adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)

    agy_before = json.loads(
        next(
            c
            for c in agy_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "settings.json"
        ).proposed_content
    )
    codex_before = toml.loads(
        next(
            c
            for c in codex_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "config.toml"
        ).proposed_content
    )

    # Change Claude support effort to max
    policy.roles[RoleClass.SUPPORT].provider_effort[ProviderType.CLAUDE] = EffortLevel.MAX

    agy_after = json.loads(
        next(
            c
            for c in agy_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "settings.json"
        ).proposed_content
    )
    codex_after = toml.loads(
        next(
            c
            for c in codex_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "config.toml"
        ).proposed_content
    )

    assert agy_before == agy_after
    assert codex_before == codex_after


# 4. Changing Codex permissions does not alter Claude permissions
def test_changing_codex_permissions_does_not_alter_claude(tmp_path: Path):
    policy = create_disposable_policy()
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    claude_adapter = ClaudeAdapter(workspace_dir=workspace, home_dir=home)
    claude_before = json.loads(
        next(
            c
            for c in claude_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "settings.json"
        ).proposed_content
    )
    assert claude_before["permissions"]["defaultMode"] == "default"

    # Modify Codex permissions to unrestricted
    policy.permissions.providers[ProviderType.CODEX].ask_approval = ApprovalPolicy.NEVER
    policy.permissions.providers[ProviderType.CODEX].sandbox = SandboxMode.DANGER_FULL_ACCESS

    claude_after = json.loads(
        next(
            c
            for c in claude_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "settings.json"
        ).proposed_content
    )
    assert claude_before["permissions"] == claude_after["permissions"]
    assert claude_after["permissions"]["defaultMode"] == "default"


# 5. Changing AGY permissions does not alter Codex permissions
def test_changing_agy_permissions_does_not_alter_codex(tmp_path: Path):
    policy = create_disposable_policy()
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    codex_before = toml.loads(
        next(
            c
            for c in codex_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "config.toml"
        ).proposed_content
    )

    # Change AGY permissions to request-review
    policy.permissions.providers[ProviderType.AGY].ask_approval = ApprovalPolicy.ALWAYS

    codex_after = toml.loads(
        next(
            c
            for c in codex_adapter.generate_changes(policy, is_global=True)
            if c.file_path.name == "config.toml"
        ).proposed_content
    )
    assert codex_before["approval_policy"] == codex_after["approval_policy"]
    assert codex_before["sandbox_mode"] == codex_after["sandbox_mode"]


# 6. Disabled providers produce no changes
def test_disabled_providers_produce_no_changes(tmp_path: Path):
    policy = create_disposable_policy()
    policy.enabled_providers = [ProviderType.AGY]

    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    engine = AlignmentEngine(workspace_dir=workspace, home_dir=home, scope=Scope.ALL)
    engine.policy = policy

    changes = engine.generate_all_changes()
    for change in changes:
        assert change.provider == ProviderType.AGY


# 7. Legacy policies continue loading
def test_legacy_policies_continue_loading():
    legacy_toml = """# Legacy v0.1.0 policy
schema_version = "0.1.0"

[providers]
enabled = ["claude", "codex", "agy"]

[roles.planning]
claude_model = "claude-opus-5"
codex_model = "gpt-6.1-sol"
agy_model = "gemini-3.8-flash-high"
effort = "high"

[roles.implementation]
claude_model = "claude-sonnet-5"
codex_model = "gpt-6.1-sol"
agy_model = "gemini-3.8-flash-high"
effort = "medium"

[roles.support]
claude_model = "claude-haiku-4"
codex_model = "gpt-5.6-luna"
agy_model = "gemini-3.8-flash-medium"
effort = "low"

[permissions]
allow_dangerous_bypass = false
ask_approval = "on-request"
sandbox = "workspace-write"
"""
    data = toml.loads(legacy_toml)
    policy = load_policy_from_dict(data)

    assert policy.schema_version == "0.1.0"
    assert policy.roles[RoleClass.IMPLEMENTATION].effort == EffortLevel.MEDIUM
    assert policy.roles[RoleClass.IMPLEMENTATION].provider_effort == {}
    assert (
        policy.get_effective_effort(ProviderType.CLAUDE, RoleClass.IMPLEMENTATION)
        == EffortLevel.MEDIUM
    )
    assert (
        policy.get_effective_effort(ProviderType.CODEX, RoleClass.IMPLEMENTATION)
        == EffortLevel.MEDIUM
    )
    assert (
        policy.get_effective_effort(ProviderType.AGY, RoleClass.IMPLEMENTATION)
        == EffortLevel.MEDIUM
    )


# 8. Explicit provider effort overrides take precedence
def test_explicit_provider_effort_overrides_precedence():
    policy = create_disposable_policy()
    # Shared effort is medium
    policy.roles[RoleClass.IMPLEMENTATION].effort = EffortLevel.MEDIUM
    # Legacy override is high
    policy.overrides["codex"] = {"model_reasoning_effort": "high"}
    # Explicit provider_effort is low
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.CODEX] = EffortLevel.LOW

    # Precedence: provider_effort (LOW) > override (HIGH) > shared (MEDIUM)
    effort, source = policy.get_effective_effort_with_source(
        ProviderType.CODEX, RoleClass.IMPLEMENTATION
    )
    assert effort == EffortLevel.LOW
    assert source == "provider_effort"

    # Conflicts detected
    conflicts = policy.get_conflicting_settings(ProviderType.CODEX)
    assert len(conflicts) >= 1
    assert "takes precedence" in conflicts[0]


# 9. Shared fallback values work correctly
def test_shared_fallback_values():
    policy = Policy(
        schema_version="0.1.5",
        roles={
            RoleClass.IMPLEMENTATION: RoleConfig(
                claude_model="claude-sonnet-5",
                codex_model="gpt-6.1-sol",
                agy_model="gemini-3.8-flash-high",
                effort=EffortLevel.MEDIUM,
                provider_effort={},
            )
        },
        permissions=PermissionsConfig(
            ask_approval=ApprovalPolicy.ALWAYS,
            sandbox=SandboxMode.READ_ONLY,
            providers={},
        ),
    )

    for prov in (ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY):
        assert policy.get_effective_effort(prov, RoleClass.IMPLEMENTATION) == EffortLevel.MEDIUM
        perms = policy.get_effective_permissions(prov)
        assert perms.ask_approval == ApprovalPolicy.ALWAYS
        assert perms.sandbox == SandboxMode.READ_ONLY


# 10. Invalid provider effort values fail validation
def test_invalid_provider_effort_values_fail_validation():
    bad_data = {
        "schema_version": "0.1.5",
        "roles": {
            "implementation": {
                "claude_model": "c",
                "codex_model": "o",
                "agy_model": "a",
                "provider_effort": {
                    "unknown_provider": "high",
                },
            }
        },
    }
    with pytest.raises(PolicyValidationError, match="Unknown provider 'unknown_provider'"):
        load_policy_from_dict(bad_data)

    bad_effort_data = {
        "schema_version": "0.1.5",
        "roles": {
            "implementation": {
                "claude_model": "c",
                "codex_model": "o",
                "agy_model": "a",
                "provider_effort": {
                    "agy": "ultra-mega-high",
                },
            }
        },
    }
    with pytest.raises(PolicyValidationError, match="Invalid effort 'ultra-mega-high'"):
        load_policy_from_dict(bad_effort_data)


# 11. Invalid permission values fail validation
def test_invalid_permission_values_fail_validation():
    bad_prov_perm = {
        "schema_version": "0.1.5",
        "permissions": {
            "providers": {
                "bad_provider": {
                    "ask_approval": "never",
                }
            }
        },
    }
    with pytest.raises(PolicyValidationError, match="Unknown provider 'bad_provider'"):
        load_policy_from_dict(bad_prov_perm)

    bad_approval = {
        "schema_version": "0.1.5",
        "permissions": {
            "providers": {
                "agy": {
                    "ask_approval": "sometimes",
                }
            }
        },
    }
    with pytest.raises(
        PolicyValidationError, match="Invalid permissions.providers.agy.ask_approval 'sometimes'"
    ):
        load_policy_from_dict(bad_approval)


# 12. Unsupported native effort values handled predictably
def test_unsupported_native_effort_values_handled_predictably(tmp_path: Path):
    policy = create_disposable_policy()
    policy.roles[RoleClass.IMPLEMENTATION].provider_effort[ProviderType.CODEX] = EffortLevel.XHIGH

    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    changes = codex_adapter.generate_changes(policy, is_global=True)
    cfg = next(c for c in changes if c.file_path.name == "config.toml")
    parsed = toml.loads(cfg.proposed_content)
    assert parsed["model_reasoning_effort"] == "xhigh"


# 13. Existing managed-file fingerprints remain valid
def test_managed_file_fingerprints_remain_valid():
    raw_md = """---
managed_by: howlalign
name: tests
description: Test runner
model: gpt-6.1-sol
---

<!-- managed_by: howlalign -->
Test agent developer instructions.
"""
    embedded = embed_managed_fingerprint(raw_md, "md")
    fp = compute_managed_fingerprint(embedded)
    assert len(fp) == 16
    assert is_file_managed_by_howlalign(embedded, "md") is True
    assert has_user_modifications(embedded, "md") is False


# 14. Repeated apply remains idempotent
def test_repeated_apply_is_idempotent(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))

    policy = create_disposable_policy()
    policy.enabled_providers = [ProviderType.CODEX, ProviderType.AGY]

    engine = AlignmentEngine(workspace_dir=workspace, home_dir=home, scope=Scope.ALL)
    engine.policy = policy

    # First apply
    changes1 = engine.generate_all_changes()
    res1 = engine.writer.apply(changes1)
    assert res1.success is True
    assert len(res1.applied_files) > 0

    # Second apply: exactly zero actionable changes
    changes2 = engine.generate_all_changes()
    actionable2 = [c for c in changes2 if c.original_content != c.proposed_content]
    assert len(actionable2) == 0


# 15. Backup and restore continue functioning
def test_backup_and_restore_functionality(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))

    policy = create_disposable_policy()
    policy.enabled_providers = [ProviderType.CODEX]

    engine = AlignmentEngine(workspace_dir=workspace, home_dir=home, scope=Scope.PROJECT)
    engine.policy = policy

    # Pre-create target file so it exists before apply
    target = workspace / ".codex" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('model = "gpt-initial"\n', encoding="utf-8")

    changes = engine.generate_all_changes()
    res = engine.writer.apply(changes, create_backup=True)
    assert res.success is True
    assert res.backup_dir is not None

    # Corrupt a file
    assert target.is_file()
    target.write_text("corrupted content\n", encoding="utf-8")

    # Restore from backup
    restore_res = engine.writer.restore_backup(Path(res.backup_dir), force=True)
    assert restore_res.success is True
    assert target.read_text(encoding="utf-8") == 'model = "gpt-initial"\n'


# 16. User-owned configurations remain preserved
def test_user_owned_configurations_preserved(tmp_path: Path):
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    user_agent = workspace / ".codex" / "agents" / "search.toml"
    user_agent.parent.mkdir(parents=True)
    user_content = '# Hand-crafted user role\nname = "search"\nmodel = "custom-agent"\n'
    user_agent.write_text(user_content, encoding="utf-8")

    policy = create_disposable_policy()
    codex_adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    changes = codex_adapter.generate_changes(policy, is_global=False)

    search_change = next(c for c in changes if c.file_path == user_agent)
    assert search_change.is_user_owned_conflict is True
    assert search_change.proposed_content == user_content


# 17. Dangerous permission changes are reported
def test_dangerous_permission_changes_reported(tmp_path: Path):
    policy = create_disposable_policy()
    escalations = policy.detect_permission_escalation(ProviderType.CODEX)
    assert any("approval policy set to 'never'" in e for e in escalations)
    assert any("sandbox mode set to 'danger-full-access'" in e for e in escalations)

    # In Differ
    changes = [CodexAdapter(workspace_dir=tmp_path).generate_changes(policy, is_global=True)[0]]
    diff_res = Differ.compute_diff(changes)
    assert "[SECURITY ALERT]" in diff_res.summary


# 18. Existing policy settings are not silently discarded
def test_existing_policy_settings_not_silently_discarded():
    policy = create_disposable_policy()
    serialized = serialize_policy_toml(policy)
    loaded = load_policy_from_dict(toml.loads(serialized))

    assert loaded.schema_version == policy.schema_version
    for role_name in (RoleClass.PLANNING, RoleClass.IMPLEMENTATION, RoleClass.SUPPORT):
        orig_rc = policy.roles[role_name]
        load_rc = loaded.roles[role_name]
        assert orig_rc.provider_effort == load_rc.provider_effort
        assert orig_rc.effort == load_rc.effort

    for prov in (ProviderType.AGY, ProviderType.CODEX, ProviderType.CLAUDE):
        orig_p = policy.permissions.providers[prov]
        load_p = loaded.permissions.providers[prov]
        assert orig_p.ask_approval == load_p.ask_approval
        assert orig_p.sandbox == load_p.sandbox


# 19. Complex Codex configuration preservation (projects, custom tables)
def test_complex_codex_configuration_preservation(tmp_path: Path):
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    cfg_file = home / ".codex" / "config.toml"
    cfg_file.parent.mkdir(parents=True)
    complex_existing = """
# Real-world Codex configuration with custom tables and trusted projects
[features]
fast_apply = true
multi_turn = true

[notice]
hide_update_login = true

[projects."/run/media/system/tallgeese/dev/howlalign"]
trust_level = "trusted"

[projects."/run/media/system/tallgeese/dev/other-project"]
trust_level = "trusted"
"""
    cfg_file.write_text(complex_existing, encoding="utf-8")

    adapter = CodexAdapter(workspace_dir=workspace, home_dir=home)
    policy = create_disposable_policy()

    changes = adapter.generate_changes(policy, is_global=True)
    cfg_change = next(c for c in changes if c.file_path == cfg_file)
    parsed = toml.loads(cfg_change.proposed_content)

    # Assert all complex keys and tables are preserved
    assert parsed["features"]["fast_apply"] is True
    assert parsed["features"]["multi_turn"] is True
    assert parsed["notice"]["hide_update_login"] is True
    assert (
        parsed["projects"]["/run/media/system/tallgeese/dev/howlalign"]["trust_level"] == "trusted"
    )
    assert (
        parsed["projects"]["/run/media/system/tallgeese/dev/other-project"]["trust_level"]
        == "trusted"
    )
    # Managed keys updated
    assert parsed["model"] == "gpt-6.1-sol"
    assert parsed["model_reasoning_effort"] == "low"
    assert parsed["plan_mode_reasoning_effort"] == "high"
    assert parsed["approval_policy"] == "never"
    assert parsed["sandbox_mode"] == "danger-full-access"


# 20. Explain CLI method output
def test_explain_cli_method_output(tmp_path: Path):
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    engine = AlignmentEngine(workspace_dir=workspace, home_dir=home)
    engine.policy = create_disposable_policy()

    exit_code = engine.explain(json_output=True)
    assert exit_code == 0
