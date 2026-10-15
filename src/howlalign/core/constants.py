"""Centralized constants, defaults, and provenance markers for HowlAlign."""

from __future__ import annotations

import os
from pathlib import Path
from types import MappingProxyType

# Versioning & Schemas
DEFAULT_POLICY_VERSION = "0.1.0"
SUPPORTED_POLICY_VERSIONS = frozenset({"0.1.0"})
POLICY_FILENAME = "howlalign.toml"
HIDDEN_POLICY_FILENAME = ".howlalign.toml"
MANIFEST_FILENAME = "manifest.json"

# Provenance Management Markers
# These markers identify files generated and managed by HowlAlign.
# Files lacking these markers are considered user-owned and are NOT overwritten.
MANAGED_BY_MARKER_MD = "managed_by: howlalign"
MANAGED_BY_MARKER_TOML = 'managed_by = "howlalign"'
MANAGED_BLOCK_START = "<!-- BEGIN HOWLALIGN MANAGED BLOCK -->"
MANAGED_BLOCK_END = "<!-- END HOWLALIGN MANAGED BLOCK -->"

# Subprocess & File Limits
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 5
DEFAULT_BUFFER_SIZE_BYTES = 65_536
DEFAULT_CONFIG_FILE_MODE = 0o600  # Default restrictive owner-only mode for configs
DEFAULT_DOC_FILE_MODE = 0o644  # Standard mode for markdown guidelines
BACKUP_DIR_MODE = 0o700  # Owner-only access for backup directories
BACKUP_FILE_MODE = 0o600  # Owner-only access for backup files

# AGY Limits
AGY_MAX_RULE_BYTES = 24_000  # 24 KB per-file hard cap in AGY CLI
AGY_AGGREGATE_RULE_BUDGET_TOKENS = 20_000
AGY_ESTIMATED_BYTES_PER_TOKEN = 4
AGY_MAX_AGGREGATE_RULE_BYTES = AGY_AGGREGATE_RULE_BUDGET_TOKENS * AGY_ESTIMATED_BYTES_PER_TOKEN

# Default Model Specifications per Provider and Role
DEFAULT_MODELS = MappingProxyType(
    {
        "claude": MappingProxyType(
            {
                "planning": "claude-opus-5",
                "implementation": "claude-sonnet-5",
                "support": "claude-haiku-4",
            }
        ),
        "codex": MappingProxyType(
            {
                "planning": "gpt-6.1-sol",
                "implementation": "gpt-6.1-sol",
                "support": "gpt-5.6-luna",
            }
        ),
        "agy": MappingProxyType(
            {
                "planning": "gemini-3.8-flash-high",
                "implementation": "gemini-3.8-flash-high",
                "support": "gemini-3.8-flash-medium",
            }
        ),
    }
)


def get_default_backup_root(home_dir: Path | None = None) -> Path:
    """Resolve user-private XDG state directory for backups outside repositories."""
    env_override = os.environ.get("HOWLALIGN_BACKUP_DIR")
    if env_override:
        return Path(env_override).resolve()

    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).resolve() / "howlalign" / "backups"

    home = home_dir or Path.home()
    return home / ".local" / "state" / "howlalign" / "backups"
