"""Tests for safe atomic writing, backups, revalidation, and security boundaries."""

from pathlib import Path

import pytest

from howlalign.core.models import ConfigChange, ProviderType
from howlalign.core.writer import (
    ConfigWriter,
    validate_path_safety,
)


def test_atomic_write_and_permissions(tmp_path: Path):
    writer = ConfigWriter(workspace_dir=tmp_path)
    target = tmp_path / "sub" / "config.json"

    writer.atomic_write(target, '{"test": 1}\n')
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == '{"test": 1}\n'

    # Check file permissions (not world-writable)
    mode = target.stat().st_mode
    assert (mode & 0o002) == 0


def test_backup_and_restore(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    # File 1: Existing file to be modified
    f1 = workspace / "existing.txt"
    f1.write_text("original content\n", encoding="utf-8")

    # File 2: New file to be created
    f2 = workspace / "new.txt"

    changes = [
        ConfigChange(
            file_path=f1,
            original_content="original content\n",
            proposed_content="updated content\n",
            description="Modify f1",
            provider=ProviderType.CLAUDE,
        ),
        ConfigChange(
            file_path=f2,
            original_content=None,
            proposed_content="created content\n",
            description="Create f2",
            provider=ProviderType.CODEX,
            is_creation=True,
        ),
    ]

    # Apply changes
    res = writer.apply(changes, create_backup=True)
    assert res.success is True
    assert res.backup_dir is not None
    assert f1.read_text(encoding="utf-8") == "updated content\n"
    assert f2.read_text(encoding="utf-8") == "created content\n"

    # Restore from backup
    restore_res = writer.restore_backup(Path(res.backup_dir))
    assert restore_res.success is True
    assert f1.read_text(encoding="utf-8") == "original content\n"
    assert not f2.exists()  # Newly created file should be removed on rollback/restore


def test_concurrent_modification_detection(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = ConfigWriter(workspace_dir=workspace)

    f1 = workspace / "file.txt"
    f1.write_text("initial state\n", encoding="utf-8")

    # Change plan assumes original is "initial state\n"
    change = ConfigChange(
        file_path=f1,
        original_content="initial state\n",
        proposed_content="aligned state\n",
        description="Align file",
        provider=ProviderType.AGY,
    )

    # Simulate concurrent edit to f1 on disk
    f1.write_text("tampered by another process\n", encoding="utf-8")

    # Attempt to apply should fail revalidation
    res = writer.apply([change], create_backup=True)
    assert res.success is False
    assert any("Concurrent modification detected" in e for e in res.errors)
    # File content should remain untouched
    assert f1.read_text(encoding="utf-8") == "tampered by another process\n"


def test_path_traversal_safety(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    # Attempting to validate path outside workspace and home
    target_outside = outside / "bad.txt"
    with pytest.raises(PermissionError, match="outside allowed roots"):
        validate_path_safety(target_outside, allowed_roots=[workspace])


def test_unsafe_symlink_safety(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.env"
    secret.write_text("SECRET=123\n", encoding="utf-8")

    symlink_in_workspace = workspace / "link_to_secret.env"
    symlink_in_workspace.symlink_to(secret)

    with pytest.raises(PermissionError, match="Unsafe symlink detected"):
        validate_path_safety(symlink_in_workspace, allowed_roots=[workspace])
