"""Exhaustive regression tests for HowlAlign v0.1.2 audit remediation.

Covers:
- H-001: Restore drift validation, missing/null hashes, deleted targets, force semantics
- H-002: Backup file integrity, SHA-256 validation, symlink rejection
- H-003: Comprehensive secret redaction (quoted, unquoted, Bearer, multi-line keys)
- H-004: Truthful rollback reporting (SUCCEEDED, PARTIAL, FAILED, NONE)
- H-005: Managed file provenance and user modification protection
- H-006: Backup manifest preservation during failure and step 4 finalization
- SEC-007: Cross-mount restore authorization and untrusted manifest protection
- COMPAT-008: AGY configuration compatibility (no planningModel in settings.json)
- ARCH-009: Strict fail-closed policy validation
"""

import json
from pathlib import Path

import pytest

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.core.constants import MANIFEST_FILENAME
from howlalign.core.differ import Differ, redact_secrets_for_display
from howlalign.core.exceptions import PolicyValidationError
from howlalign.core.models import (
    ConfigChange,
    ProviderType,
    RecoveryState,
    RoleClass,
)
from howlalign.core.policy import get_default_policy, load_policy_from_dict
from howlalign.core.writer import ConfigWriter, compute_file_sha256

# ============================================================================
# H-001: RESTORE DRIFT VALIDATION
# ============================================================================


def test_h001_restore_drift_rejects_missing_or_null_post_apply_hash(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    target = workspace / "config.txt"
    target.write_text("initial content\n", encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content="initial content\n",
        proposed_content="updated content\n",
        description="Update",
        provider=ProviderType.CLAUDE,
    )

    # Apply change to create a backup
    res_apply = writer.apply([change], create_backup=True)
    assert res_apply.success is True
    backup_dir = Path(res_apply.backup_dir)

    # Manipulate manifest to simulate null post_apply_sha256
    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["post_apply_sha256"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Restore without force must be rejected
    res_restore = writer.restore_backup(backup_dir, force=False)
    assert res_restore.success is False
    assert any(
        "Target drift validation failure" in e or "missing or invalid post_apply_sha256" in e
        for e in res_restore.errors
    )
    assert target.read_text(encoding="utf-8") == "updated content\n"

    # Restore with force must succeed
    res_force = writer.restore_backup(backup_dir, force=True)
    assert res_force.success is True
    assert target.read_text(encoding="utf-8") == "initial content\n"


def test_h001_restore_detects_target_file_deleted_after_apply(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    target = workspace / "data.txt"
    target.write_text("version 1\n", encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content="version 1\n",
        proposed_content="version 2\n",
        description="Update data",
        provider=ProviderType.CODEX,
    )

    res_apply = writer.apply([change], create_backup=True)
    assert res_apply.success is True
    backup_dir = Path(res_apply.backup_dir)

    # Delete the target file on disk
    target.unlink()
    assert not target.exists()

    # Restore without force must detect deletion as drift
    res_restore = writer.restore_backup(backup_dir, force=False)
    assert res_restore.success is False
    assert any("deleted after apply" in e for e in res_restore.errors)

    # Restore with force authorizes recreating the original file
    res_force = writer.restore_backup(backup_dir, force=True)
    assert res_force.success is True
    assert target.read_text(encoding="utf-8") == "version 1\n"


# ============================================================================
# H-002: BACKUP FILE INTEGRITY
# ============================================================================


def test_h002_backup_integrity_rejects_corrupted_backup_artifact(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    target = workspace / "sensitive.json"
    target.write_text('{"important": true}\n', encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content='{"important": true}\n',
        proposed_content='{"important": false}\n',
        description="Modify sensitive file",
        provider=ProviderType.AGY,
    )

    res_apply = writer.apply([change], create_backup=True)
    assert res_apply.success is True
    backup_dir = Path(res_apply.backup_dir)

    # Locate and corrupt the backup file bytes
    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_rel = manifest["files"][0]["backup_path"]
    backup_file = backup_dir / backup_rel
    backup_file.write_text("CORRUPTED GARBAGE DATA\n", encoding="utf-8")

    # Restore without force must reject corrupted backup
    res1 = writer.restore_backup(backup_dir, force=False)
    assert res1.success is False
    assert any("Backup integrity failure" in e for e in res1.errors)

    # Force restore must ALSO reject corrupted backup (force overrides drift, not integrity!)
    res2 = writer.restore_backup(backup_dir, force=True)
    assert res2.success is False
    assert any("Backup integrity failure" in e for e in res2.errors)

    # Target must not be overwritten with corrupted data
    assert target.read_text(encoding="utf-8") == '{"important": false}\n'


def test_h002_backup_integrity_rejects_symlink_inside_backup_dir(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    target = workspace / "target.txt"
    target.write_text("original\n", encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content="original\n",
        proposed_content="proposed\n",
        description="Update",
        provider=ProviderType.CLAUDE,
    )

    res_apply = writer.apply([change], create_backup=True)
    backup_dir = Path(res_apply.backup_dir)

    manifest_path = backup_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_rel = manifest["files"][0]["backup_path"]
    backup_file = backup_dir / backup_rel

    # Replace backup file with a symlink
    backup_file.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    backup_file.symlink_to(outside)

    res = writer.restore_backup(backup_dir, force=True)
    assert res.success is False
    assert any("backup artifact is a symlink" in e for e in res.errors)


# ============================================================================
# H-004: TRUTHFUL ROLLBACK REPORTING
# ============================================================================


def test_h004_rollback_reports_truthful_failure(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    file1 = workspace / "file1.txt"
    file2 = workspace / "file2.txt"
    file1.write_text("orig1\n", encoding="utf-8")
    file2.write_text("orig2\n", encoding="utf-8")

    changes = [
        ConfigChange(
            file_path=file1,
            original_content="orig1\n",
            proposed_content="prop1\n",
            description="change 1",
            provider=ProviderType.CLAUDE,
        ),
        ConfigChange(
            file_path=file2,
            original_content="orig2\n",
            proposed_content="prop2\n",
            description="change 2",
            provider=ProviderType.CLAUDE,
        ),
    ]

    # Inject failure on write of file2, AND inject failure on rollback of file1
    real_atomic_write = writer.atomic_write
    write_count = 0

    def mock_atomic_write(target: Path, content: str):
        nonlocal write_count
        write_count += 1
        if target == file2:
            raise RuntimeError("Disk write error on file2!")
        # If this is during rollback (reverting file1)
        if write_count > 2 and target == file1:
            raise RuntimeError("Rollback revert failed on file1!")
        real_atomic_write(target, content)

    monkeypatch.setattr(writer, "atomic_write", mock_atomic_write)

    res = writer.apply(changes, create_backup=True)
    assert res.success is False
    # Finding H-004 fix: rolled_back must be FALSE when rollback fails!
    assert res.rolled_back is False
    assert res.recovery_state in (RecoveryState.FAILED, RecoveryState.PARTIAL)
    assert str(file1) in res.remaining_modified_files


def test_h004_rollback_reports_success_when_all_reverted(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    file1 = workspace / "file1.txt"
    file1.write_text("orig1\n", encoding="utf-8")

    # Invalid second change path targeting unauthorized root to trigger failure on step 3
    changes = [
        ConfigChange(
            file_path=file1,
            original_content="orig1\n",
            proposed_content="prop1\n",
            description="change 1",
            provider=ProviderType.CLAUDE,
        ),
        ConfigChange(
            file_path=Path("/invalid/unauthorized/path/file2.txt"),
            original_content=None,
            proposed_content="prop2\n",
            description="change 2",
            provider=ProviderType.CLAUDE,
            is_creation=True,
        ),
    ]

    res = writer.apply(changes, create_backup=True)
    assert res.success is False
    assert res.rolled_back is True
    assert res.recovery_state == RecoveryState.SUCCEEDED
    assert file1.read_text(encoding="utf-8") == "orig1\n"
    assert res.remaining_modified_files == []


# ============================================================================
# H-006: PRESERVE BACKUP MANIFESTS
# ============================================================================


def test_h006_manifest_not_overwritten_with_reduced_list_during_rollback(
    tmp_path: Path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    file1 = workspace / "file1.txt"
    file2 = workspace / "file2.txt"
    file1.write_text("orig1\n", encoding="utf-8")
    file2.write_text("orig2\n", encoding="utf-8")

    changes = [
        ConfigChange(
            file_path=file1,
            original_content="orig1\n",
            proposed_content="prop1\n",
            description="change 1",
            provider=ProviderType.CODEX,
        ),
        ConfigChange(
            file_path=file2,
            original_content="orig2\n",
            proposed_content="prop2\n",
            description="change 2",
            provider=ProviderType.CODEX,
        ),
    ]

    real_atomic_write = writer.atomic_write

    def mock_write(target: Path, content: str):
        if target == file2:
            raise RuntimeError("Simulated write failure on file 2!")
        real_atomic_write(target, content)

    monkeypatch.setattr(writer, "atomic_write", mock_write)

    res = writer.apply(changes, create_backup=True)
    assert res.success is False
    assert res.backup_dir is not None

    # Finding H-006: manifest.json on disk must NOT be overwritten with only [file1]!
    backup_dir = Path(res.backup_dir)
    manifest = json.loads((backup_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    # Both files must remain in manifest.json
    assert len(manifest["files"]) == 2
    assert manifest["status"] in ("rolled_back", "failed")


def test_h006_manifest_finalization_failure_reports_truthful_unfinalized_state(
    tmp_path: Path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    target = workspace / "test.txt"
    target.write_text("orig\n", encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content="orig\n",
        proposed_content="prop\n",
        description="update",
        provider=ProviderType.AGY,
    )

    # Fail during step 4 manifest write
    real_write_manifest = writer._write_manifest
    call_count = 0

    def mock_write_manifest(manifest_path: Path, manifest_data: dict):
        nonlocal call_count
        call_count += 1
        if call_count > 1:  # Fail on Step 4 finalization write
            raise OSError("Disk quota exceeded while finalizing manifest!")
        real_write_manifest(manifest_path, manifest_data)

    monkeypatch.setattr(writer, "_write_manifest", mock_write_manifest)

    res = writer.apply([change], create_backup=True)
    assert res.success is False
    assert any("failed to finalize manifest" in e for e in res.errors)
    assert str(target) in res.remaining_modified_files


# ============================================================================
# SEC-007: CROSS-MOUNT RESTORE WITHOUT TRUST BYPASS
# ============================================================================


def test_sec007_cross_mount_restore_with_authorized_workspace(tmp_path: Path):
    # Simulate a separate volume mount (e.g. /run/media/drive/project)
    mount_workspace = tmp_path / "media_mount" / "project"
    mount_workspace.mkdir(parents=True)
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    writer = ConfigWriter(workspace_dir=mount_workspace, home_dir=home_dir)

    target = mount_workspace / "config.toml"
    target.write_text("key = 'initial'\n", encoding="utf-8")

    change = ConfigChange(
        file_path=target,
        original_content="key = 'initial'\n",
        proposed_content="key = 'updated'\n",
        description="Mount change",
        provider=ProviderType.CODEX,
    )

    res_apply = writer.apply([change], create_backup=True)
    assert res_apply.success is True
    backup_dir = Path(res_apply.backup_dir)

    # Now create a new writer running from another directory (e.g. current directory is home_dir)
    other_cwd_writer = ConfigWriter(workspace_dir=home_dir, home_dir=home_dir)

    # Without trusted_workspace, target on /media_mount/ escapes [home_dir]
    res_rejected = other_cwd_writer.restore_backup(backup_dir, force=True)
    assert res_rejected.success is False
    assert any(
        "escapes authorized roots" in e or "provide --workspace" in e for e in res_rejected.errors
    )

    # With explicit trusted_workspace authorization, restore succeeds!
    res_authorized = other_cwd_writer.restore_backup(
        backup_dir,
        force=True,
        trusted_workspace=mount_workspace,
    )
    assert res_authorized.success is True
    assert target.read_text(encoding="utf-8") == "key = 'initial'\n"


def test_sec007_cross_mount_restore_rejects_untrusted_manifest_target(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    writer = ConfigWriter(workspace_dir=workspace, home_dir=home_dir)
    backup_dir = tmp_path / "malicious_backup"
    backup_dir.mkdir()

    # Create malicious manifest attempting to restore into /etc or arbitrary directory
    evil_target = tmp_path / "unrelated_dir" / "secret.txt"
    evil_target.parent.mkdir()
    evil_target.write_text("unrelated\n", encoding="utf-8")

    manifest = {
        "version": "0.1.2",
        "timestamp": "20261015_000000",
        "workspace": str(workspace),
        "status": "completed",
        "files": [
            {
                "target_path": str(evil_target),
                "existed": True,
                "backup_path": "file_0_secret.txt",
                "original_sha256": compute_file_sha256(evil_target),
                "post_apply_sha256": compute_file_sha256(evil_target),
            }
        ],
    }
    (backup_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    (backup_dir / "file_0_secret.txt").write_text("evil\n", encoding="utf-8")

    # Even with workspace provided, evil_target is outside authorized roots
    res = writer.restore_backup(backup_dir, force=True, trusted_workspace=workspace)
    assert res.success is False
    assert any("escapes authorized roots" in e for e in res.errors)


# ============================================================================
# H-003: SECRET REDACTION AND OUTPUT SAFETY
# ============================================================================


def test_h003_secret_redaction_comprehensive():
    raw_api_key = "sk-proj-super-secret-key-123456789"
    raw_github = "ghp_1234567890abcdef1234567890abcdef"
    raw_bearer = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    raw_rsa = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0Y3...\n-----END RSA PRIVATE KEY-----"
    )

    content_with_secrets = f"""
api_key = "{raw_api_key}"
GITHUB_TOKEN={raw_github}
Authorization: Bearer {raw_bearer}
PRIVATE_KEY:
{raw_rsa}
"""

    redacted_text, had_secrets = redact_secrets_for_display(content_with_secrets)
    assert had_secrets is True

    # No secret tokens, prefixes, or suffixes should appear
    assert raw_api_key not in redacted_text
    assert raw_github not in redacted_text
    assert raw_bearer not in redacted_text
    assert "MIIEowIBAAKCAQEA0Y3" not in redacted_text

    # Redacted markers should be present
    assert "****[REDACTED]****" in redacted_text
    assert "****[REDACTED PRIVATE KEY]****" in redacted_text


def test_h003_differ_masks_unquoted_and_env_secrets(tmp_path: Path):
    target = tmp_path / "env.txt"
    raw_secret = "ghp_securetoken999999999999999999"

    changes = [
        ConfigChange(
            file_path=target,
            original_content="token=old_token\n",
            proposed_content=f"token={raw_secret}\n",
            description="Add token",
            provider=ProviderType.CODEX,
        )
    ]

    res = Differ.compute_diff(changes, mask_secrets=True)
    assert raw_secret not in res.unified_diff
    assert res.has_redactions is True
    assert "SECURITY NOTICE" in res.unified_diff
    assert "****" in res.unified_diff


# ============================================================================
# COMPAT-008: AGY CONFIGURATION COMPATIBILITY
# ============================================================================


def test_compat008_agy_no_planning_model_in_settings(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = AgyAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()
    # Configure distinct planning model
    policy.roles[RoleClass.PLANNING].agy_model = "gemini-3.8-flash-high"
    policy.roles[RoleClass.IMPLEMENTATION].agy_model = "gemini-3.8-flash-medium"

    changes = adapter.generate_changes(policy, is_global=True)
    settings_change = next(c for c in changes if c.file_path.name == "settings.json")
    parsed = json.loads(settings_change.proposed_content)

    # Finding COMPAT-008: planningModel must NOT be written to settings.json
    assert "planningModel" not in parsed
    assert parsed["model"] == "gemini-3.8-flash-medium"

    # Diagnostics should inform user of native planning capabilities
    provider_info = adapter.check_health(policy, None, is_global=False)
    assert any("Policy specifies planning model" in d.message for d in provider_info)


# ============================================================================
# ARCH-009: STRICT FAIL-CLOSED POLICY VALIDATION
# ============================================================================


def test_arch009_strict_policy_validation_rejects_invalid_enums():
    # 1. Invalid effort level
    with pytest.raises(PolicyValidationError, match="Invalid effort 'ultra'"):
        load_policy_from_dict(
            {
                "schema_version": "0.1.0",
                "roles": {"planning": {"effort": "ultra"}},
            }
        )

    # 2. Invalid ask_approval policy
    with pytest.raises(PolicyValidationError, match="Invalid permissions.ask_approval 'whenever'"):
        load_policy_from_dict(
            {
                "schema_version": "0.1.0",
                "permissions": {"ask_approval": "whenever"},
            }
        )

    # 3. Invalid sandbox mode
    with pytest.raises(PolicyValidationError, match="Invalid permissions.sandbox 'unrestricted'"):
        load_policy_from_dict(
            {
                "schema_version": "0.1.0",
                "permissions": {"sandbox": "unrestricted"},
            }
        )

    # 4. Invalid agent model_role
    with pytest.raises(PolicyValidationError, match="Invalid model_role 'wizard'"):
        load_policy_from_dict(
            {
                "schema_version": "0.1.0",
                "agents": {"helper": {"model_role": "wizard"}},
            }
        )

    # 5. Unknown provider in enabled list
    with pytest.raises(PolicyValidationError, match="Unknown provider 'copilot'"):
        load_policy_from_dict(
            {
                "schema_version": "0.1.0",
                "providers": {"enabled": ["claude", "copilot"]},
            }
        )


# ============================================================================
# H-005: MANAGED FILE PROVENANCE & USER MODIFICATIONS
# ============================================================================


def test_h005_user_modified_managed_file_preserved(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    adapter = ClaudeAdapter(workspace_dir=workspace, home_dir=home)
    policy = get_default_policy()

    # Step 1: Generate initial agent file
    changes = adapter.generate_changes(policy, is_global=False)
    search_change = next(c for c in changes if c.file_path.name == "search.md")
    search_file = search_change.file_path
    search_file.parent.mkdir(parents=True, exist_ok=True)
    search_file.write_text(search_change.proposed_content, encoding="utf-8")

    # Step 2: Simulate human developer customizing the prompt
    customized_content = (
        search_file.read_text(encoding="utf-8") + "\n# Extra custom user instructions\n"
    )
    search_file.write_text(customized_content, encoding="utf-8")

    # Step 3: Run generate_changes again
    changes_after_edit = adapter.generate_changes(policy, is_global=False)
    search_change_2 = next(c for c in changes_after_edit if c.file_path == search_file)

    # Must be recognized as user-owned conflict and preserved untouched
    assert search_change_2.is_user_owned_conflict is True
    assert search_change_2.proposed_content == customized_content
    assert "User modifications detected" in search_change_2.description
