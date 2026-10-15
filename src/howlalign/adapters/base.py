"""Base provider adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from howlalign.core.models import (
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
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
