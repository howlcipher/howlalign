"""Safe atomic configuration writer, revalidation, and backup/restore engine."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from howlalign.core.models import ApplyResult, ConfigChange


def compute_file_sha256(path: Path) -> str | None:
    """Compute SHA-256 hash of a file if it exists, else None."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_string_sha256(content: str | None) -> str | None:
    """Compute SHA-256 hash of a string if not None."""
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_path_safety(target_path: Path, allowed_roots: list[Path]) -> None:
    """Ensure path does not perform unsafe traversal or break outside allowed roots."""
    resolved = target_path.resolve()

    # Check for symlink traversal
    if target_path.is_symlink():
        symlink_target = target_path.resolve()
        is_safe = any(symlink_target.is_relative_to(root.resolve()) for root in allowed_roots)
        if not is_safe:
            raise PermissionError(
                f"Unsafe symlink detected pointing outside allowed roots: {target_path} -> {symlink_target}"
            )

    # Check that path is within at least one allowed root
    is_contained = any(resolved.is_relative_to(root.resolve()) for root in allowed_roots)
    if not is_contained:
        raise PermissionError(
            f"Target path {resolved} is outside allowed roots: {[str(r) for r in allowed_roots]}"
        )


class ConfigWriter:
    """Applies configuration changes with atomic writes, pre-write revalidation, and backups."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()
        self.allowed_roots = [self.workspace, self.home]

    def create_backup(
        self,
        changes: list[ConfigChange],
        backup_base_dir: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        """Create timestamped backups of all files about to be modified."""
        base = backup_base_dir or (self.workspace / ".howlalign" / "backups")
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        backup_dir = base / ts
        backup_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any] = {
            "timestamp": ts,
            "workspace": str(self.workspace),
            "files": [],
        }

        for idx, change in enumerate(changes):
            target = change.file_path.resolve()
            entry: dict[str, Any] = {
                "target_path": str(target),
                "existed": target.is_file(),
                "backup_path": None,
                "original_sha256": compute_file_sha256(target),
            }

            if target.is_file():
                backup_file = backup_dir / f"file_{idx}_{target.name}"
                shutil.copy2(target, backup_file)
                entry["backup_path"] = str(backup_file)

            manifest["files"].append(entry)

        manifest_path = backup_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return backup_dir, manifest

    def revalidate_changes(self, changes: list[ConfigChange]) -> list[str]:
        """Verify that files on disk match the state when diff was calculated (detect TOCTOU)."""
        errors: list[str] = []
        for change in changes:
            target = change.file_path.resolve()
            current_sha = compute_file_sha256(target)
            expected_sha = compute_string_sha256(change.original_content)

            if current_sha != expected_sha:
                errors.append(
                    f"Concurrent modification detected on {target}: expected hash {expected_sha}, found {current_sha}"
                )
        return errors

    def atomic_write(self, target_path: Path, content: str) -> None:
        """Atomically write content to a file via a temporary file in the same directory."""
        validate_path_safety(target_path, self.allowed_roots)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        parent = target_path.parent
        # Create temp file in same directory to guarantee atomic rename across filesystems
        fd, temp_path_str = tempfile.mkstemp(dir=parent, prefix=f".{target_path.name}.tmp_")
        temp_path = Path(temp_path_str)

        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            # Enforce safe permissions (0o644 for configs)
            os.chmod(temp_path, 0o644)
            # Atomic replace
            os.replace(temp_path, target_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def restore_backup(self, backup_dir: Path) -> ApplyResult:
        """Restore files from a backup directory using its manifest."""
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.is_file():
            return ApplyResult(
                success=False,
                errors=[f"Invalid backup directory (missing manifest.json): {backup_dir}"],
            )

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        restored_files: list[str] = []
        errors: list[str] = []

        for entry in manifest.get("files", []):
            target = Path(entry["target_path"])
            existed = entry.get("existed", False)
            backup_file_str = entry.get("backup_path")

            try:
                if existed and backup_file_str:
                    backup_file = Path(backup_file_str)
                    if backup_file.is_file():
                        self.atomic_write(target, backup_file.read_text(encoding="utf-8"))
                        restored_files.append(str(target))
                    else:
                        errors.append(f"Missing backup file: {backup_file}")
                elif not existed and target.is_file():
                    # File was newly created by apply, so delete it on restore
                    target.unlink()
                    restored_files.append(f"DELETED (reverted creation): {target}")
            except Exception as e:
                errors.append(f"Failed to restore {target}: {e}")

        return ApplyResult(
            success=len(errors) == 0,
            applied_files=restored_files,
            backup_dir=str(backup_dir),
            errors=errors,
        )

    def apply(
        self,
        changes: list[ConfigChange],
        create_backup: bool = True,
        backup_base_dir: Path | None = None,
    ) -> ApplyResult:
        """Apply all configuration changes atomically with revalidation and backups."""
        # Step 1: Revalidate file state
        reval_errors = self.revalidate_changes(changes)
        if reval_errors:
            return ApplyResult(
                success=False,
                applied_files=[],
                errors=reval_errors,
            )

        # Step 2: Create backup
        backup_dir: Path | None = None
        if create_backup:
            try:
                backup_dir, _ = self.create_backup(changes, backup_base_dir=backup_base_dir)
            except Exception as e:
                return ApplyResult(
                    success=False,
                    applied_files=[],
                    errors=[f"Failed to create backup prior to applying changes: {e}"],
                )

        # Step 3: Apply changes with rollback on failure
        applied: list[str] = []
        try:
            for change in changes:
                if change.original_content == change.proposed_content:
                    continue  # No changes needed
                self.atomic_write(change.file_path, change.proposed_content)
                applied.append(str(change.file_path))
        except Exception as err:
            rollback_errors: list[str] = [f"Write failed on step ({err}). Initiating rollback."]
            if backup_dir:
                res = self.restore_backup(backup_dir)
                if not res.success:
                    rollback_errors.extend(res.errors)
            return ApplyResult(
                success=False,
                applied_files=applied,
                backup_dir=str(backup_dir) if backup_dir else None,
                errors=rollback_errors,
            )

        return ApplyResult(
            success=True,
            applied_files=applied,
            backup_dir=str(backup_dir) if backup_dir else None,
            errors=[],
        )
