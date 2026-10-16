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
    provider_effort: dict[ProviderType, EffortLevel] = field(default_factory=dict)

    def get_model_for_provider(self, provider: ProviderType) -> str:
        """Retrieve model identifier for a given provider."""
        if provider == ProviderType.CLAUDE:
            return self.claude_model
        elif provider == ProviderType.CODEX:
            return self.codex_model
        elif provider == ProviderType.AGY:
            return self.agy_model
        raise ValueError(f"Unknown provider: {provider}")

    def get_effort_for_provider(self, provider: ProviderType) -> EffortLevel:
        """Retrieve effort level for a given provider with fallback to shared effort."""
        return self.provider_effort.get(provider, self.effort)

    @property
    def claude_effort(self) -> EffortLevel:
        return self.get_effort_for_provider(ProviderType.CLAUDE)

    @property
    def codex_effort(self) -> EffortLevel:
        return self.get_effort_for_provider(ProviderType.CODEX)

    @property
    def agy_effort(self) -> EffortLevel:
        return self.get_effort_for_provider(ProviderType.AGY)


@dataclass
class AgentConfig:
    name: str
    description: str
    model_role: RoleClass
    read_only: bool = False
    enabled: bool = True
    system_prompt: str = ""


@dataclass
class ProviderPermissionsConfig:
    allow_dangerous_bypass: bool | None = None
    ask_approval: ApprovalPolicy | None = None
    sandbox: SandboxMode | None = None


@dataclass(frozen=True)
class EffectivePermissions:
    allow_dangerous_bypass: bool
    ask_approval: ApprovalPolicy
    sandbox: SandboxMode


@dataclass(frozen=True)
class EffectiveRoleSettings:
    role: RoleClass
    model: str
    effort: EffortLevel
    effort_source: str  # "provider_effort", "provider_override", "shared_effort", "default"


@dataclass(frozen=True)
class EffectiveProviderPolicy:
    provider: ProviderType
    enabled: bool
    roles: dict[RoleClass, EffectiveRoleSettings]
    permissions: EffectivePermissions
    permission_sources: dict[str, str]


@dataclass
class PermissionsConfig:
    allow_dangerous_bypass: bool = False
    ask_approval: ApprovalPolicy = ApprovalPolicy.ON_REQUEST
    sandbox: SandboxMode = SandboxMode.WORKSPACE_WRITE
    providers: dict[ProviderType, ProviderPermissionsConfig] = field(default_factory=dict)

    def get_effective_permissions(self, provider: ProviderType) -> EffectivePermissions:
        prov_cfg = self.providers.get(provider)
        bypass = (
            prov_cfg.allow_dangerous_bypass
            if prov_cfg and prov_cfg.allow_dangerous_bypass is not None
            else self.allow_dangerous_bypass
        )
        approval = (
            prov_cfg.ask_approval
            if prov_cfg and prov_cfg.ask_approval is not None
            else self.ask_approval
        )
        sbox = prov_cfg.sandbox if prov_cfg and prov_cfg.sandbox is not None else self.sandbox
        return EffectivePermissions(
            allow_dangerous_bypass=bypass,
            ask_approval=approval,
            sandbox=sbox,
        )


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

    def get_effective_model(self, provider: ProviderType | str, role: RoleClass | str) -> str:
        """Resolve effective model for a provider and role with safe fallbacks."""
        if isinstance(provider, str):
            provider = ProviderType(provider)
        if isinstance(role, str):
            role = RoleClass(role)

        role_cfg = self.roles.get(role)
        if role_cfg:
            try:
                return role_cfg.get_model_for_provider(provider)
            except ValueError:
                pass

        # Fallback to defaults
        from howlalign.core.constants import DEFAULT_MODELS

        prov_models = DEFAULT_MODELS.get(provider.value, {})
        return prov_models.get(role.value, "default")

    def get_effective_effort_with_source(
        self, provider: ProviderType | str, role: RoleClass | str
    ) -> tuple[EffortLevel, str]:
        """Resolve effective effort for provider and role according to strict precedence rules.

        Precedence:
        1. Explicit provider-specific role effort (roles.<role>.provider_effort.<provider>)
        2. Existing supported provider-specific effort override (overrides.<provider>.*)
        3. Shared role effort (roles.<role>.effort)
        4. Established default
        """
        if isinstance(provider, str):
            provider = ProviderType(provider)
        if isinstance(role, str):
            role = RoleClass(role)

        role_cfg = self.roles.get(role)

        # 1. Explicit provider-specific role effort
        if role_cfg and provider in role_cfg.provider_effort:
            return role_cfg.provider_effort[provider], "provider_effort"

        # 2. Existing supported provider-specific override
        prov_overrides = self.overrides.get(provider.value, {})
        if provider == ProviderType.CODEX:
            if role == RoleClass.IMPLEMENTATION and "model_reasoning_effort" in prov_overrides:
                raw = str(prov_overrides["model_reasoning_effort"]).lower()
                try:
                    return EffortLevel(raw), "provider_override"
                except ValueError:
                    pass
            elif role == RoleClass.PLANNING and "plan_mode_reasoning_effort" in prov_overrides:
                raw = str(prov_overrides["plan_mode_reasoning_effort"]).lower()
                try:
                    return EffortLevel(raw), "provider_override"
                except ValueError:
                    pass
        elif provider == ProviderType.AGY:
            if role == RoleClass.IMPLEMENTATION and "effort" in prov_overrides:
                raw = str(prov_overrides["effort"]).lower()
                try:
                    return EffortLevel(raw), "provider_override"
                except ValueError:
                    pass
        elif provider == ProviderType.CLAUDE:
            if "effort" in prov_overrides:
                raw = str(prov_overrides["effort"]).lower()
                try:
                    return EffortLevel(raw), "provider_override"
                except ValueError:
                    pass

        # 3. Shared role effort
        if role_cfg:
            return role_cfg.effort, "shared_effort"

        # 4. Established default
        if role == RoleClass.PLANNING:
            return EffortLevel.HIGH, "default"
        elif role == RoleClass.SUPPORT:
            return EffortLevel.LOW, "default"
        return EffortLevel.MEDIUM, "default"

    def get_effective_effort(
        self, provider: ProviderType | str, role: RoleClass | str
    ) -> EffortLevel:
        """Resolve effective effort level for a provider and role."""
        effort, _ = self.get_effective_effort_with_source(provider, role)
        return effort

    def get_effective_permissions_with_sources(
        self, provider: ProviderType | str
    ) -> tuple[EffectivePermissions, dict[str, str]]:
        """Resolve effective permissions for a provider according to documented precedence.

        Precedence:
        1. Explicit provider-specific permissions (permissions.providers.<provider>)
        2. Legacy provider overrides (e.g. overrides.agy.toolPermission)
        3. Shared permissions (permissions.*)
        4. Safe defaults
        """
        if isinstance(provider, str):
            provider = ProviderType(provider)

        sources: dict[str, str] = {}
        prov_cfg = self.permissions.providers.get(provider)
        prov_overrides = self.overrides.get(provider.value, {})

        # 1. Ask approval
        if prov_cfg and prov_cfg.ask_approval is not None:
            approval = prov_cfg.ask_approval
            sources["ask_approval"] = "provider_specific"
        elif provider == ProviderType.AGY and "toolPermission" in prov_overrides:
            tp = str(prov_overrides["toolPermission"]).lower()
            if tp == "always-proceed":
                approval = ApprovalPolicy.NEVER
            elif tp == "request-review":
                approval = ApprovalPolicy.ALWAYS
            else:
                approval = ApprovalPolicy.ON_REQUEST
            sources["ask_approval"] = "provider_override"
        elif self.permissions.ask_approval is not None:
            approval = self.permissions.ask_approval
            sources["ask_approval"] = "shared"
        else:
            approval = ApprovalPolicy.ON_REQUEST
            sources["ask_approval"] = "default"

        # 2. Sandbox
        if prov_cfg and prov_cfg.sandbox is not None:
            sandbox = prov_cfg.sandbox
            sources["sandbox"] = "provider_specific"
        elif self.permissions.sandbox is not None:
            sandbox = self.permissions.sandbox
            sources["sandbox"] = "shared"
        else:
            sandbox = SandboxMode.WORKSPACE_WRITE
            sources["sandbox"] = "default"

        # 3. Allow dangerous bypass
        if prov_cfg and prov_cfg.allow_dangerous_bypass is not None:
            bypass = prov_cfg.allow_dangerous_bypass
            sources["allow_dangerous_bypass"] = "provider_specific"
        elif self.permissions.allow_dangerous_bypass is not None:
            bypass = self.permissions.allow_dangerous_bypass
            sources["allow_dangerous_bypass"] = "shared"
        else:
            bypass = False
            sources["allow_dangerous_bypass"] = "default"

        return (
            EffectivePermissions(
                allow_dangerous_bypass=bypass,
                ask_approval=approval,
                sandbox=sandbox,
            ),
            sources,
        )

    def get_effective_permissions(self, provider: ProviderType | str) -> EffectivePermissions:
        """Resolve effective permissions for a provider."""
        perms, _ = self.get_effective_permissions_with_sources(provider)
        return perms

    def get_effective_provider_policy(
        self, provider: ProviderType | str
    ) -> EffectiveProviderPolicy:
        """Construct full effective policy representation for a provider."""
        if isinstance(provider, str):
            provider = ProviderType(provider)

        roles_map: dict[RoleClass, EffectiveRoleSettings] = {}
        for role in (RoleClass.PLANNING, RoleClass.IMPLEMENTATION, RoleClass.SUPPORT):
            model = self.get_effective_model(provider, role)
            effort, effort_src = self.get_effective_effort_with_source(provider, role)
            roles_map[role] = EffectiveRoleSettings(
                role=role,
                model=model,
                effort=effort,
                effort_source=effort_src,
            )

        perms, perm_sources = self.get_effective_permissions_with_sources(provider)
        return EffectiveProviderPolicy(
            provider=provider,
            enabled=provider in self.enabled_providers,
            roles=roles_map,
            permissions=perms,
            permission_sources=perm_sources,
        )

    def get_conflicting_settings(self, provider: ProviderType | str) -> list[str]:
        """Detect and return human-readable notices when older and newer settings conflict."""
        if isinstance(provider, str):
            provider = ProviderType(provider)

        conflicts: list[str] = []
        prov_overrides = self.overrides.get(provider.value, {})
        prov_perm_cfg = self.permissions.providers.get(provider)

        # Check effort conflicts
        if provider == ProviderType.CODEX:
            impl_cfg = self.roles.get(RoleClass.IMPLEMENTATION)
            if (
                impl_cfg
                and ProviderType.CODEX in impl_cfg.provider_effort
                and "model_reasoning_effort" in prov_overrides
            ):
                pe = impl_cfg.provider_effort[ProviderType.CODEX].value
                ov = str(prov_overrides["model_reasoning_effort"]).lower()
                if pe != ov:
                    conflicts.append(
                        f"Codex implementation effort conflict: roles.implementation.provider_effort.codex='{pe}' takes precedence over overrides.codex.model_reasoning_effort='{ov}'."
                    )
            plan_cfg = self.roles.get(RoleClass.PLANNING)
            if (
                plan_cfg
                and ProviderType.CODEX in plan_cfg.provider_effort
                and "plan_mode_reasoning_effort" in prov_overrides
            ):
                pe = plan_cfg.provider_effort[ProviderType.CODEX].value
                ov = str(prov_overrides["plan_mode_reasoning_effort"]).lower()
                if pe != ov:
                    conflicts.append(
                        f"Codex planning effort conflict: roles.planning.provider_effort.codex='{pe}' takes precedence over overrides.codex.plan_mode_reasoning_effort='{ov}'."
                    )
        elif provider == ProviderType.AGY:
            impl_cfg = self.roles.get(RoleClass.IMPLEMENTATION)
            if (
                impl_cfg
                and ProviderType.AGY in impl_cfg.provider_effort
                and "effort" in prov_overrides
            ):
                pe = impl_cfg.provider_effort[ProviderType.AGY].value
                ov = str(prov_overrides["effort"]).lower()
                if pe != ov:
                    conflicts.append(
                        f"AGY implementation effort conflict: roles.implementation.provider_effort.agy='{pe}' takes precedence over overrides.agy.effort='{ov}'."
                    )

        # Check permissions conflicts
        if (
            provider == ProviderType.AGY
            and prov_perm_cfg
            and prov_perm_cfg.ask_approval is not None
            and "toolPermission" in prov_overrides
        ):
            pa = prov_perm_cfg.ask_approval.value
            tp = str(prov_overrides["toolPermission"]).lower()
            conflicts.append(
                f"AGY permissions conflict: permissions.providers.agy.ask_approval='{pa}' takes precedence over overrides.agy.toolPermission='{tp}'."
            )

        return conflicts

    def detect_permission_escalation(
        self,
        provider: ProviderType | str,
        baseline: EffectivePermissions | None = None,
    ) -> list[str]:
        """Detect and return warnings if effective permissions represent privilege widening."""
        if isinstance(provider, str):
            provider = ProviderType(provider)

        warnings: list[str] = []
        effective = self.get_effective_permissions(provider)
        safe_base = baseline or EffectivePermissions(
            allow_dangerous_bypass=False,
            ask_approval=ApprovalPolicy.ON_REQUEST,
            sandbox=SandboxMode.WORKSPACE_WRITE,
        )

        if effective.allow_dangerous_bypass and not safe_base.allow_dangerous_bypass:
            warnings.append(
                f"Permission widening: {provider.value} dangerous security bypass enabled ('allow_dangerous_bypass = true')."
            )

        if (
            effective.ask_approval == ApprovalPolicy.NEVER
            and safe_base.ask_approval != ApprovalPolicy.NEVER
        ):
            warnings.append(
                f"Permission widening: {provider.value} approval policy set to 'never' (autonomous execution without confirmation)."
            )

        if (
            effective.sandbox == SandboxMode.DANGER_FULL_ACCESS
            and safe_base.sandbox != SandboxMode.DANGER_FULL_ACCESS
        ):
            warnings.append(
                f"Permission widening: {provider.value} sandbox mode set to 'danger-full-access' (file writes unrestricted to workspace)."
            )

        return warnings


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


class RecoveryState(str, Enum):
    NONE = "none"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class ApplyResult:
    success: bool
    applied_files: list[str] = field(default_factory=list)
    backup_dir: str | None = None
    errors: list[str] = field(default_factory=list)
    rolled_back: bool = False
    recovery_state: RecoveryState = RecoveryState.NONE
    remaining_modified_files: list[str] = field(default_factory=list)


@dataclass
class DiagnosticItem:
    severity: str  # "INFO", "WARNING", "ERROR"
    category: str  # "VERSION", "SECURITY", "CONFIGURATION", "COMPATIBILITY", "DRIFT"
    message: str
    provider: str | None = None
    action: str | None = None
