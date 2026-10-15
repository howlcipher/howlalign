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

from howlalign.core.constants import (
    BACKUP_DIR_MODE,
    BACKUP_FILE_MODE,
    DEFAULT_BUFFER_SIZE_BYTES,
    DEFAULT_CONFIG_FILE_MODE,
    DEFAULT_DOC_FILE_MODE,
    MANIFEST_FILENAME,
    get_default_backup_root,
)
from howlalign.core.exceptions import (
    AtomicWriteError,
    PathTraversalError,
    UnsafeSymlinkError,
)
from howlalign.core.models import ApplyResult, ConfigChange


def compute_file_sha256(path: Path) -> str | None:
    """Compute SHA-256 hash of a file if it exists, else None."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(DEFAULT_BUFFER_SIZE_BYTES):
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
    resolved_roots = [r.resolve() for r in allowed_roots]

    # Verify that the target itself or any parent directory symlink does not escape allowed roots
    current = target_path
    while current != current.parent:
        if current.is_symlink():
            sym_target = current.resolve()
            is_safe = any(sym_target.is_relative_to(root) for root in resolved_roots)
            if not is_safe:
                raise UnsafeSymlinkError(
                    f"Unsafe symlink detected escaping allowed roots: '{current}' -> '{sym_target}'"
                )
        current = current.parent

    # Check that final resolved path is within at least one allowed root
    is_contained = any(resolved.is_relative_to(root) for root in resolved_roots)
    if not is_contained:
        raise PathTraversalError(
            f"Target path '{resolved}' escapes authorized roots: {[str(r) for r in resolved_roots]}"
        )


class ConfigWriter:
    """Applies configuration changes with atomic writes, pre-write revalidation, and backups."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
        backup_root: Path | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()
        self.allowed_roots = [self.workspace, self.home]
        self.backup_root = backup_root or get_default_backup_root(self.home)

    def _get_workspace_backup_dir(self) -> Path:
        """Derive an isolated, user-private backup directory for this workspace."""
        # Hash workspace path to avoid collision across repositories
        workspace_key = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:16]
        ws_name = "".join(c if c.isalnum() else "_" for c in self.workspace.name) or "root"
        return self.backup_root / f"{ws_name}_{workspace_key}"

    def create_backup(
        self,
        changes: list[ConfigChange],
        backup_base_dir: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        """Create timestamped backups of all files about to be modified with strict permissions."""
        base = backup_base_dir or self._get_workspace_backup_dir()
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        backup_dir = base / ts

        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(backup_dir, BACKUP_DIR_MODE)
        except OSError:
            pass

        manifest: dict[str, Any] = {
            "version": "0.1.1",
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
                "post_apply_sha256": None,
            }

            if target.is_file():
                backup_file = backup_dir / f"file_{idx}_{target.name}"
                shutil.copy2(target, backup_file)
                try:
                    os.chmod(backup_file, BACKUP_FILE_MODE)
                except OSError:
                    pass
                entry["backup_path"] = str(backup_file)

            manifest["files"].append(entry)

        manifest_path = backup_dir / MANIFEST_FILENAME
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        try:
            os.chmod(manifest_path, BACKUP_FILE_MODE)
        except OSError:
            pass

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
        """Atomically write content to a file via a temporary file in the same directory, preserving mode."""
        validate_path_safety(target_path, self.allowed_roots)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        parent = target_path.parent

        # Preserve permissions if file exists, else use restrictive default
        if target_path.exists():
            target_mode = target_path.stat().st_mode & 0o777
        else:
            # Markdown documents standard 0o644, configs restrictive 0o600
            target_mode = (
                DEFAULT_DOC_FILE_MODE
                if target_path.suffix.lower() == ".md"
                else DEFAULT_CONFIG_FILE_MODE
            )

        fd, temp_path_str = tempfile.mkstemp(dir=parent, prefix=f".{target_path.name}.tmp_")
        temp_path = Path(temp_path_str)

        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.chmod(temp_path, target_mode)
            os.replace(temp_path, target_path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise AtomicWriteError(f"Failed atomic replacement of '{target_path}': {e}") from e

    def restore_backup(self, backup_dir: Path, force: bool = False) -> ApplyResult:
        """Restore files from a backup directory with strict manifest validation and drift checks."""
        manifest_path = backup_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            return ApplyResult(
                success=False,
                errors=[f"Invalid backup directory (missing manifest.json): {backup_dir}"],
            )

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as err:
            return ApplyResult(
                success=False,
                errors=[f"Failed to parse backup manifest: {err}"],
            )

        if (
            not isinstance(manifest, dict)
            or "files" not in manifest
            or not isinstance(manifest["files"], list)
        ):
            return ApplyResult(
                success=False,
                errors=["Malformed backup manifest: missing valid 'files' list"],
            )

        restored_files: list[str] = []
        errors: list[str] = []
        backup_dir_resolved = backup_dir.resolve()

        # Step 1: Pre-validation of all manifest entries
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or "target_path" not in entry:
                return ApplyResult(
                    success=False,
                    errors=["Malformed manifest entry: missing 'target_path'"],
                )

            target = Path(entry["target_path"])
            try:
                validate_path_safety(target, self.allowed_roots)
            except Exception as e:
                return ApplyResult(
                    success=False,
                    errors=[f"Security violation in restore manifest target '{target}': {e}"],
                )

            backup_file_str = entry.get("backup_path")
            if backup_file_str:
                backup_file = Path(backup_file_str).resolve()
                if not backup_file.is_relative_to(backup_dir_resolved):
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Security violation: backup file '{backup_file}' is outside backup directory '{backup_dir}'"
                        ],
                    )
                if not backup_file.is_file():
                    return ApplyResult(
                        success=False,
                        errors=[f"Corrupt backup: missing backup artifact '{backup_file}'"],
                    )

            # Target Drift Detection: Has file changed on disk since apply?
            post_apply_sha = entry.get("post_apply_sha256")
            if not force and post_apply_sha:
                current_sha = compute_file_sha256(target)
                if current_sha != post_apply_sha:
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Target drift conflict: '{target}' was modified after apply (expected hash {post_apply_sha}, found {current_sha}). Use --force to overwrite."
                        ],
                    )

        # Step 2: Perform atomic restores and safe unlinks
        for entry in manifest["files"]:
            target = Path(entry["target_path"])
            existed = entry.get("existed", False)
            backup_file_str = entry.get("backup_path")

            try:
                if existed and backup_file_str:
                    backup_file = Path(backup_file_str)
                    self.atomic_write(target, backup_file.read_text(encoding="utf-8"))
                    restored_files.append(str(target))
                elif not existed and target.is_file():
                    # Validate path safety again before unlinking
                    validate_path_safety(target, self.allowed_roots)
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
        """Apply all configuration changes atomically with revalidation and rollback."""
        # Step 1: Revalidate file state before writing
        reval_errors = self.revalidate_changes(changes)
        if reval_errors:
            return ApplyResult(
                success=False,
                applied_files=[],
                errors=reval_errors,
            )

        # Step 2: Create backup
        backup_dir: Path | None = None
        manifest: dict[str, Any] | None = None
        if create_backup:
            try:
                backup_dir, manifest = self.create_backup(changes, backup_base_dir=backup_base_dir)
            except Exception as e:
                return ApplyResult(
                    success=False,
                    applied_files=[],
                    errors=[f"Failed to create backup prior to applying changes: {e}"],
                )

        # Step 3: Apply changes with scoped rollback on failure
        applied: list[ConfigChange] = []
        try:
            for change in changes:
                if change.original_content == change.proposed_content:
                    continue  # No changes needed
                self.atomic_write(change.file_path, change.proposed_content)
                applied.append(change)
        except Exception as err:
            rollback_errors: list[str] = [f"Write failed on step ({err}). Initiating rollback."]
            # Scoped rollback of modified files only
            if backup_dir and manifest:
                # Filter manifest files to only those that were touched
                applied_paths = {str(c.file_path.resolve()) for c in applied}
                scoped_manifest = {
                    **manifest,
                    "files": [
                        f for f in manifest.get("files", []) if f["target_path"] in applied_paths
                    ],
                }
                # Overwrite manifest temporarily for scoped rollback
                manifest_path = backup_dir / MANIFEST_FILENAME
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(scoped_manifest, f, indent=2)

                res = self.restore_backup(backup_dir, force=True)
                if not res.success:
                    rollback_errors.extend(res.errors)
            else:
                # In-memory rollback when disk backups are disabled
                for c in reversed(applied):
                    try:
                        if c.is_creation or c.original_content is None:
                            if c.file_path.is_file():
                                c.file_path.unlink()
                        else:
                            self.atomic_write(c.file_path, c.original_content)
                    except Exception as rb_err:
                        rollback_errors.append(
                            f"In-memory rollback failed on {c.file_path}: {rb_err}"
                        )

            return ApplyResult(
                success=False,
                applied_files=[str(c.file_path) for c in applied],
                backup_dir=str(backup_dir) if backup_dir else None,
                errors=rollback_errors,
                rolled_back=True,
            )

        # Step 4: Record post-apply hashes in manifest for future restore drift protection
        if backup_dir and manifest:
            for entry in manifest.get("files", []):
                t_path = Path(entry["target_path"])
                entry["post_apply_sha256"] = compute_file_sha256(t_path)
            manifest_path = backup_dir / MANIFEST_FILENAME
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

        return ApplyResult(
            success=True,
            applied_files=[str(c.file_path) for c in applied],
            backup_dir=str(backup_dir) if backup_dir else None,
            errors=[],
        )
