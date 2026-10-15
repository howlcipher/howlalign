"""Domain-specific exception hierarchy for HowlAlign."""

from __future__ import annotations

from pathlib import Path


class HowlAlignError(Exception):
    """Base exception for all HowlAlign errors."""

    pass


# Configuration & Policy Errors
class ConfigurationError(HowlAlignError):
    """Base exception for configuration and policy errors."""

    pass


class PolicyNotFoundError(ConfigurationError, FileNotFoundError):
    """Raised when an expected policy file does not exist."""

    pass


class PolicyValidationError(ConfigurationError, ValueError):
    """Raised when a policy fails schema or semantic validation."""

    pass


class PolicySyntaxError(ConfigurationError, ValueError):
    """Raised when a policy file contains invalid syntax."""

    pass


class ConfigurationParseError(ConfigurationError, ValueError):
    """Raised when an existing assistant configuration file cannot be parsed safely."""

    def __init__(self, file_path: Path | str, format_name: str, cause: Exception) -> None:
        self.file_path = Path(file_path)
        self.format_name = format_name
        self.cause = cause
        super().__init__(
            f"Failed to parse existing {format_name} configuration at '{self.file_path}': {cause}. "
            "Aborting alignment to prevent data loss."
        )


# Safety & Security Errors
class SafetyViolationError(HowlAlignError, PermissionError):
    """Base exception for safety and security violations."""

    pass


class PathTraversalError(SafetyViolationError):
    """Raised when a path escapes allowed directory boundaries."""

    pass


class UnsafeSymlinkError(SafetyViolationError):
    """Raised when an unsafe symlink targets unauthorized locations."""

    pass


class SecretExposureError(SafetyViolationError):
    """Raised when raw credentials or secrets are detected."""

    pass


class BackupCorruptedError(SafetyViolationError):
    """Raised when backup artifact integrity check fails or file is corrupted."""

    pass


class ManifestValidationError(SafetyViolationError):
    """Raised when backup manifest schema or paths fail validation."""

    pass


# Execution & Transaction Errors
class ExecutionError(HowlAlignError):
    """Base exception for file operation and execution failures."""

    pass


class ConcurrentModificationError(ExecutionError):
    """Raised when a file changes on disk between planning and writing (TOCTOU)."""

    pass


class AtomicWriteError(ExecutionError, OSError):
    """Raised when atomic write or tempfile operation fails."""

    pass


class RestoreConflictError(ExecutionError):
    """Raised when a restore target has drifted since the original apply."""

    pass


class RollbackFailureError(ExecutionError):
    """Raised when transactional rollback encounters errors."""

    pass
