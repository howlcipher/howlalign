"""Base provider adapter interface and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from howlalign.core.constants import (
    MANAGED_BY_MARKER_MD,
    MANAGED_BY_MARKER_TOML,
)
from howlalign.core.models import (
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
)


def safe_read_text(path: Path) -> str | None:
    """Read text file if present, returning None if missing."""
    return path.read_text(encoding="utf-8") if path.is_file() else None


def is_file_managed_by_howlalign(content: str | None, format_type: str = "md") -> bool:
    """Determine if an existing configuration/agent file is managed by HowlAlign.

    If the file does not exist, it is considered eligible for creation (managed=True).
    If it exists and contains the provenance marker, it is managed.
    If it exists and lacks the marker, it is user-authored and must NOT be overwritten.
    """
    if content is None:
        return True
    if format_type.lower() == "toml":
        return MANAGED_BY_MARKER_TOML in content
    return MANAGED_BY_MARKER_MD in content


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
