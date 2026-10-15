"""Base provider adapter interface and shared helpers."""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path

from howlalign.core.models import (
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
)

FINGERPRINT_PATTERN_MD = re.compile(r"^\s*managed_fingerprint:\s*([0-9a-fA-F]+)", re.MULTILINE)
FINGERPRINT_PATTERN_TOML = re.compile(
    r'^\s*#?\s*managed_fingerprint\s*=\s*["\']([0-9a-fA-F]+)["\']', re.MULTILINE
)


def safe_read_text(path: Path) -> str | None:
    """Read text file if present, returning None if missing."""
    return path.read_text(encoding="utf-8") if path.is_file() else None


def compute_managed_fingerprint(text: str) -> str:
    """Compute stable SHA-256 fingerprint of the core content ignoring variable metadata lines."""
    lines = [
        line.strip()
        for line in text.splitlines()
        if not line.strip().startswith("managed_fingerprint")
        and not line.strip().startswith("# managed_fingerprint")
        and not line.strip().startswith("<!-- managed_fingerprint")
    ]
    core_content = "\n".join(lines)
    return hashlib.sha256(core_content.encode("utf-8")).hexdigest()[:16]


def extract_managed_fingerprint(content: str | None, format_type: str = "md") -> str | None:
    """Extract recorded managed_fingerprint from file header if present."""
    if not content:
        return None
    header = "\n".join(content.splitlines()[:25])
    pattern = FINGERPRINT_PATTERN_TOML if format_type.lower() == "toml" else FINGERPRINT_PATTERN_MD
    m = pattern.search(header)
    return m.group(1) if m else None


def has_user_modifications(content: str | None, format_type: str = "md") -> bool:
    """Check if a managed file has user modifications by comparing content with recorded fingerprint."""
    if not content:
        return False
    fp = extract_managed_fingerprint(content, format_type=format_type)
    if not fp:
        return False
    current_fp = compute_managed_fingerprint(content)
    return current_fp != fp


def is_file_managed_by_howlalign(content: str | None, format_type: str = "md") -> bool:
    """Determine if an existing configuration/agent file is managed by HowlAlign.

    Inspects the file header (first 20 lines) to avoid false matches on incidental text.
    If the file does not exist, it is considered eligible for creation (managed=True).
    If it exists and contains the provenance marker in the header, it is managed.
    If it exists and lacks the marker in the header, it is user-authored and must NOT be overwritten.
    """
    if content is None:
        return True
    header_text = "\n".join(content.splitlines()[:20]).lower()
    if format_type.lower() == "toml":
        return (
            'managed_by = "howlalign"' in header_text
            or "managed_by: howlalign" in header_text
            or "# managed by howlalign" in header_text
        )
    return (
        "managed_by: howlalign" in header_text
        or 'managed_by = "howlalign"' in header_text
        or "<!-- managed_by: howlalign -->" in header_text
    )


class BaseAdapter(ABC):
    """Abstract base class for assistant provider configuration adapters."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the target provider type."""
        ...

    @abstractmethod
    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        """Generate the proposed native configuration changes for this provider."""
        ...

    @abstractmethod
    def check_health(
        self,
        policy: Policy,
        info: ProviderInfo,
        is_global: bool = False,
    ) -> list[DiagnosticItem]:
        """Run provider-specific health and compatibility diagnostics."""
        ...
