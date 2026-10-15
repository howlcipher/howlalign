"""Safe atomic configuration writer, revalidation, and backup/restore engine."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
from howlalign.core.models import ApplyResult, ConfigChange, RecoveryState

HEX_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


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
        authorized_roots: list[Path] | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()
        self.allowed_roots = (
            [r.resolve() for r in authorized_roots]
            if authorized_roots is not None
            else [self.workspace, self.home]
        )
        self.backup_root = backup_root or get_default_backup_root(self.home)

    def _get_workspace_backup_dir(self) -> Path:
        """Derive an isolated, user-private backup directory for this workspace."""
        workspace_key = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:16]
        ws_name = "".join(c if c.isalnum() else "_" for c in self.workspace.name) or "root"
        return self.backup_root / f"{ws_name}_{workspace_key}"

    def _write_manifest(self, manifest_path: Path, manifest_data: dict[str, Any]) -> None:
        """Atomically write manifest.json with user-only permissions."""
        parent = manifest_path.parent
        fd, temp_path_str = tempfile.mkstemp(dir=parent, prefix=".manifest.tmp_")
        temp_path = Path(temp_path_str)
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(temp_path, BACKUP_FILE_MODE)
            os.replace(temp_path, manifest_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

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
            "version": "0.1.2",
            "timestamp": ts,
            "workspace": str(self.workspace),
            "status": "in_progress",
            "files": [],
        }

        for idx, change in enumerate(changes):
            target = change.file_path.resolve()
            existed = target.is_file()
            orig_sha = compute_file_sha256(target) if existed else None
            backup_filename: str | None = None

            if existed:
                backup_filename = f"file_{idx}_{target.name}"
                backup_file = backup_dir / backup_filename
                shutil.copy2(target, backup_file)
                try:
                    os.chmod(backup_file, BACKUP_FILE_MODE)
                except OSError:
                    pass

            entry: dict[str, Any] = {
                "target_path": str(target),
                "existed": existed,
                "backup_path": backup_filename,
                "original_sha256": orig_sha,
                "post_apply_sha256": None,
            }
            manifest["files"].append(entry)

        manifest_path = backup_dir / MANIFEST_FILENAME
        self._write_manifest(manifest_path, manifest)

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

    def restore_backup(
        self,
        backup_dir: Path,
        force: bool = False,
        trusted_workspace: Path | None = None,
    ) -> ApplyResult:
        """Restore files from a backup directory with strict manifest validation, integrity verification, and drift checks."""
        manifest_path = backup_dir / MANIFEST_FILENAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
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

        # Determine effective authorized roots
        effective_roots = list(self.allowed_roots)
        if trusted_workspace is not None:
            trusted_ws_resolved = trusted_workspace.resolve()
            if not trusted_ws_resolved.is_dir():
                return ApplyResult(
                    success=False,
                    errors=[
                        f"Specified --workspace directory does not exist: '{trusted_workspace}'"
                    ],
                )
            manifest_ws_str = manifest.get("workspace")
            if manifest_ws_str:
                manifest_ws = Path(manifest_ws_str).resolve()
                if manifest_ws != trusted_ws_resolved:
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Workspace authorization mismatch: manifest was created for '{manifest_ws}', "
                            f"but --workspace was specified as '{trusted_ws_resolved}'."
                        ],
                    )
            effective_roots.append(trusted_ws_resolved)

        # Distinguish completed transaction from incomplete/interrupted transaction
        manifest_status = manifest.get("status", "completed")
        if manifest_status != "completed" and not force:
            return ApplyResult(
                success=False,
                errors=[
                    f"Cannot restore incomplete or interrupted transaction (status: '{manifest_status}'). "
                    "Target drift hashes may be missing or unverified. Use --force to explicitly authorize recovery."
                ],
            )

        backup_dir_resolved = backup_dir.resolve()

        # Step 1: Strict Pre-validation of ALL manifest entries before modifying any disk files
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or "target_path" not in entry:
                return ApplyResult(
                    success=False,
                    errors=["Malformed manifest entry: missing 'target_path'"],
                )

            target = Path(entry["target_path"])
            try:
                validate_path_safety(target, effective_roots)
            except Exception as e:
                manifest_ws = manifest.get("workspace", "unknown")
                return ApplyResult(
                    success=False,
                    errors=[
                        f"Security violation in restore manifest target '{target}': {e}. "
                        f"Manifest workspace is '{manifest_ws}'. If this is an authorized cross-mount workspace, "
                        "provide --workspace <path> to authorize it."
                    ],
                )

            existed = bool(entry.get("existed", False))
            backup_file_rel = entry.get("backup_path")

            if existed:
                if not backup_file_rel:
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Corrupt manifest: missing backup_path for existing file '{target}'"
                        ],
                    )

                backup_file = (
                    (backup_dir_resolved / backup_file_rel)
                    if not Path(backup_file_rel).is_absolute()
                    else Path(backup_file_rel).resolve()
                )

                if backup_file.is_symlink():
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Security violation: backup artifact is a symlink: '{backup_file}'"
                        ],
                    )

                if not backup_file.resolve().is_relative_to(backup_dir_resolved):
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

                # Validate original_sha256 format and content integrity
                orig_sha = entry.get("original_sha256")
                if (
                    not orig_sha
                    or not isinstance(orig_sha, str)
                    or not HEX_SHA256_PATTERN.match(orig_sha)
                ):
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Corrupt manifest: missing or invalid original_sha256 for '{target}' (found {orig_sha!r})"
                        ],
                    )

                actual_backup_sha = compute_file_sha256(backup_file)
                if actual_backup_sha != orig_sha:
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Backup integrity failure: backup file '{backup_file.name}' for target '{target}' "
                            f"does not match expected SHA-256 (expected {orig_sha}, found {actual_backup_sha}). "
                            "Restore aborted to prevent restoring corrupted data."
                        ],
                    )

            # Target Drift Validation
            post_apply_sha = entry.get("post_apply_sha256")
            if not force:
                if (
                    not post_apply_sha
                    or not isinstance(post_apply_sha, str)
                    or not HEX_SHA256_PATTERN.match(post_apply_sha)
                ):
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Target drift validation failure: missing or invalid post_apply_sha256 for '{target}' "
                            f"(found {post_apply_sha!r}). Transaction may be incomplete. Use --force to authorize overwrite."
                        ],
                    )

                if target.exists():
                    current_sha = compute_file_sha256(target)
                    if current_sha != post_apply_sha:
                        return ApplyResult(
                            success=False,
                            errors=[
                                f"Target drift conflict: '{target}' was modified after apply "
                                f"(expected hash {post_apply_sha}, found {current_sha}). Use --force to overwrite."
                            ],
                        )
                else:
                    # Target was deleted after apply
                    return ApplyResult(
                        success=False,
                        errors=[
                            f"Target drift conflict: '{target}' was deleted after apply "
                            f"(expected hash {post_apply_sha}). Use --force to restore."
                        ],
                    )

        # Step 2: Perform atomic restores and safe unlinks (all entries pre-validated)
        restored_files: list[str] = []
        errors: list[str] = []

        for entry in manifest["files"]:
            target = Path(entry["target_path"])
            existed = bool(entry.get("existed", False))
            backup_file_rel = entry.get("backup_path")

            try:
                if existed and backup_file_rel:
                    backup_file = (
                        (backup_dir_resolved / backup_file_rel)
                        if not Path(backup_file_rel).is_absolute()
                        else Path(backup_file_rel).resolve()
                    )
                    content = backup_file.read_text(encoding="utf-8")
                    # Use effective_roots for atomic write
                    validate_path_safety(target, effective_roots)
                    self._atomic_write_with_roots(target, content, effective_roots)
                    restored_files.append(str(target))
                elif not existed and target.is_file():
                    validate_path_safety(target, effective_roots)
                    target.unlink()
                    restored_files.append(f"DELETED (reverted creation): {target}")
            except Exception as e:
                errors.append(f"Failed to restore {target}: {e}")

        return ApplyResult(
            success=len(errors) == 0,
            applied_files=restored_files,
            backup_dir=str(backup_dir),
            errors=errors,
            rolled_back=False,
            recovery_state=RecoveryState.NONE,
        )

    def _atomic_write_with_roots(
        self,
        target_path: Path,
        content: str,
        roots: list[Path],
    ) -> None:
        """Atomically write content to target path respecting specific authorized roots."""
        validate_path_safety(target_path, roots)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        parent = target_path.parent

        if target_path.exists():
            target_mode = target_path.stat().st_mode & 0o777
        else:
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

    def apply(
        self,
        changes: list[ConfigChange],
        create_backup: bool = True,
        backup_base_dir: Path | None = None,
    ) -> ApplyResult:
        """Apply all configuration changes atomically with revalidation and truthful rollback."""
        # Step 1: Revalidate file state before writing (detect TOCTOU)
        reval_errors = self.revalidate_changes(changes)
        if reval_errors:
            return ApplyResult(
                success=False,
                applied_files=[],
                errors=reval_errors,
                rolled_back=False,
                recovery_state=RecoveryState.NONE,
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
                    rolled_back=False,
                    recovery_state=RecoveryState.NONE,
                )

        # Step 3: Apply changes with in-memory scoped rollback on failure
        applied: list[ConfigChange] = []
        try:
            for change in changes:
                if change.original_content == change.proposed_content:
                    continue  # No changes needed
                self.atomic_write(change.file_path, change.proposed_content)
                applied.append(change)
        except Exception as err:
            rollback_errors: list[str] = [f"Write failed on step ({err}). Initiating rollback."]
            reverted_files: list[str] = []
            failed_revert_files: list[str] = []

            # Rollback without mutating or destroying manifest.json on disk
            if backup_dir and manifest:
                manifest_files = manifest.get("files", [])
                for c in reversed(applied):
                    target_resolved = c.file_path.resolve()
                    matching = next(
                        (
                            entry
                            for entry in manifest_files
                            if Path(entry["target_path"]).resolve() == target_resolved
                        ),
                        None,
                    )
                    if matching:
                        try:
                            if matching.get("existed") and matching.get("backup_path"):
                                b_path = Path(matching["backup_path"])
                                if not b_path.is_absolute():
                                    b_path = backup_dir / b_path
                                self.atomic_write(c.file_path, b_path.read_text(encoding="utf-8"))
                                reverted_files.append(str(c.file_path))
                            elif not matching.get("existed"):
                                if c.file_path.is_file():
                                    c.file_path.unlink()
                                reverted_files.append(str(c.file_path))
                        except Exception as rb_err:
                            failed_revert_files.append(str(c.file_path))
                            rollback_errors.append(f"Rollback failed on {c.file_path}: {rb_err}")
                    else:
                        failed_revert_files.append(str(c.file_path))
                        rollback_errors.append(
                            f"Rollback failed on {c.file_path}: missing backup entry in manifest"
                        )

                # Persist rollback state into manifest without destroying file records
                try:
                    manifest["status"] = "rolled_back" if not failed_revert_files else "failed"
                    manifest_path = backup_dir / MANIFEST_FILENAME
                    self._write_manifest(manifest_path, manifest)
                except Exception:
                    pass
            else:
                # In-memory rollback when disk backups are disabled
                for c in reversed(applied):
                    try:
                        if c.is_creation or c.original_content is None:
                            if c.file_path.is_file():
                                c.file_path.unlink()
                        else:
                            self.atomic_write(c.file_path, c.original_content)
                        reverted_files.append(str(c.file_path))
                    except Exception as rb_err:
                        failed_revert_files.append(str(c.file_path))
                        rollback_errors.append(
                            f"In-memory rollback failed on {c.file_path}: {rb_err}"
                        )

            # Determine accurate recovery state
            if not applied:
                rec_state = RecoveryState.NONE
                rolled_back = False
            elif not failed_revert_files:
                rec_state = RecoveryState.SUCCEEDED
                rolled_back = True
            elif reverted_files:
                rec_state = RecoveryState.PARTIAL
                rolled_back = False
            else:
                rec_state = RecoveryState.FAILED
                rolled_back = False

            return ApplyResult(
                success=False,
                applied_files=[str(c.file_path) for c in applied],
                backup_dir=str(backup_dir) if backup_dir else None,
                errors=rollback_errors,
                rolled_back=rolled_back,
                recovery_state=rec_state,
                remaining_modified_files=failed_revert_files,
            )

        # Step 4: Record post-apply hashes in manifest for future restore drift protection
        if backup_dir and manifest:
            try:
                for entry in manifest.get("files", []):
                    t_path = Path(entry["target_path"])
                    entry["post_apply_sha256"] = compute_file_sha256(t_path)
                manifest["status"] = "completed"
                manifest_path = backup_dir / MANIFEST_FILENAME
                self._write_manifest(manifest_path, manifest)
            except Exception as final_err:
                return ApplyResult(
                    success=False,
                    applied_files=[str(c.file_path) for c in applied],
                    backup_dir=str(backup_dir) if backup_dir else None,
                    errors=[
                        f"Files written successfully, but failed to finalize manifest ({final_err}). "
                        "Target files are modified, but post-apply validation hashes were not saved."
                    ],
                    rolled_back=False,
                    recovery_state=RecoveryState.NONE,
                    remaining_modified_files=[str(c.file_path) for c in applied],
                )

        return ApplyResult(
            success=True,
            applied_files=[str(c.file_path) for c in applied],
            backup_dir=str(backup_dir) if backup_dir else None,
            errors=[],
            rolled_back=False,
            recovery_state=RecoveryState.NONE,
        )
