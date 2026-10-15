"""Core domain models for HowlAlign."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProviderType(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    AGY = "agy"


class Scope(str, Enum):
    PROJECT = "project"
    GLOBAL = "global"
    ALL = "all"


class RoleClass(str, Enum):
    PLANNING = "planning"
    IMPLEMENTATION = "implementation"
    SUPPORT = "support"


class EffortLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class SandboxMode(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"


class ApprovalPolicy(str, Enum):
    ON_REQUEST = "on-request"
    NEVER = "never"
    ALWAYS = "always"


@dataclass
class RoleConfig:
    claude_model: str
    codex_model: str
    agy_model: str
    effort: EffortLevel = EffortLevel.MEDIUM
    description: str = ""

    def get_model_for_provider(self, provider: ProviderType) -> str:
        """Retrieve model identifier for a given provider."""
        if provider == ProviderType.CLAUDE:
            return self.claude_model
        elif provider == ProviderType.CODEX:
            return self.codex_model
        elif provider == ProviderType.AGY:
            return self.agy_model
        raise ValueError(f"Unknown provider: {provider}")


@dataclass
class AgentConfig:
    name: str
    description: str
    model_role: RoleClass
    read_only: bool = False
    enabled: bool = True
    system_prompt: str = ""


@dataclass
class PermissionsConfig:
    allow_dangerous_bypass: bool = False
    ask_approval: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    sandbox: SandboxMode = SandboxMode.WORKSPACE_WRITE


@dataclass
class Policy:
    schema_version: str = "0.1.0"
    enabled_providers: list[ProviderType] = field(
        default_factory=lambda: [ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY]
    )
    roles: dict[RoleClass, RoleConfig] = field(default_factory=dict)
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ProviderInfo:
    provider: ProviderType
    installed: bool
    version: str | None = None
    executable_path: str | None = None
    global_config_path: str | None = None
    project_config_path: str | None = None
    capabilities: list[str] = field(default_factory=list)
    unsupported_features: list[str] = field(default_factory=list)


@dataclass
class ConfigChange:
    file_path: Path
    original_content: str | None
    proposed_content: str
    description: str
    provider: ProviderType
    is_creation: bool = False
    is_deletion: bool = False
    is_user_owned_conflict: bool = (
        False  # True if existing file was authored by user without managed_by marker
    )


@dataclass
class DiffResult:
    changes: list[ConfigChange] = field(default_factory=list)
    unified_diff: str = ""
    summary: str = ""
    has_conflicts: bool = False
    has_redactions: bool = False


@dataclass
class ApplyResult:
    success: bool
    applied_files: list[str] = field(default_factory=list)
    backup_dir: str | None = None
    errors: list[str] = field(default_factory=list)
    rolled_back: bool = False


@dataclass
class DiagnosticItem:
    severity: str  # "INFO", "WARNING", "ERROR"
    category: str  # "VERSION", "SECURITY", "CONFIGURATION", "COMPATIBILITY", "DRIFT"
    message: str
    provider: str | None = None
    action: str | None = None
