"""Declarative policy schema, loading, validation, and serialization."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from howlalign.core.constants import (
    DEFAULT_POLICY_VERSION,
    HIDDEN_POLICY_FILENAME,
    POLICY_FILENAME,
    SUPPORTED_POLICY_VERSIONS,
)
from howlalign.core.exceptions import (
    PolicyNotFoundError,
    PolicySyntaxError,
    PolicyValidationError,
)
from howlalign.core.models import (
    AgentConfig,
    ApprovalPolicy,
    EffortLevel,
    PermissionsConfig,
    Policy,
    ProviderPermissionsConfig,
    ProviderType,
    RoleClass,
    RoleConfig,
    SandboxMode,
)

DEFAULT_SEARCH_PROMPT = """You are a specialized Search and Exploration subagent.
Responsibilities:
- Explore the repository structure and map architectural relationships.
- Locate symbols, function definitions, types, and usages.
- Trace dependencies and execution paths.
- Return concise file paths and line ranges (e.g. file:///path/to/file#L10-L20).
Restrictions:
- Strictly READ-ONLY exploration.
- Do not modify, create, or delete any source, configuration, or test files.
"""

DEFAULT_TESTS_PROMPT = """You are a specialized Test Runner and Failure Diagnostic subagent.
Responsibilities:
- Execute authorized project test commands (e.g. pytest, npm test, cargo test, go test).
- Collect terminal output, exit codes, and stack traces.
- Diagnose test failures and pinpoint likely regressions.
- Return structured diagnostic evidence and suggested remediation steps.
Restrictions:
- Run only non-destructive, isolated test commands.
- Do not modify existing test suites, application code, or environment settings.
"""

DEFAULT_DOCS_PROMPT = """You are a specialized Technical Documentation Research subagent.
Responsibilities:
- Research relevant language, framework, API, and library documentation.
- Verify version-specific behavior, breaking changes, and migration paths.
- Summarize API contracts, types, and function signatures.
- Provide direct documentation links and citations.
Restrictions:
- Strictly READ-ONLY research.
- Do not modify or create source or configuration files.
"""


def get_default_policy() -> Policy:
    """Construct standard default policy for HowlAlign."""
    roles = {
        RoleClass.PLANNING: RoleConfig(
            claude_model="claude-opus-5",
            codex_model="gpt-6.1-sol",
            agy_model="gemini-3.8-flash-high",
            effort=EffortLevel.HIGH,
            description="System architecture, complex refactoring, high-level planning, and security-critical design",
        ),
        RoleClass.IMPLEMENTATION: RoleConfig(
            claude_model="claude-sonnet-5",
            codex_model="gpt-6.1-sol",
            agy_model="gemini-3.8-flash-high",
            effort=EffortLevel.MEDIUM,
            description="Active feature implementation, bug fixes, refactoring, and test writing",
        ),
        RoleClass.SUPPORT: RoleConfig(
            claude_model="claude-haiku-4",
            codex_model="gpt-5.6-luna",
            agy_model="gemini-3.8-flash-medium",
            effort=EffortLevel.LOW,
            description="Lightweight support tasks, symbol search, documentation, and diagnostics",
        ),
    }

    agents = {
        "search": AgentConfig(
            name="search",
            description="Repository mapping, symbol lookup, and dependency tracing (read-only)",
            model_role=RoleClass.SUPPORT,
            read_only=True,
            enabled=True,
            system_prompt=DEFAULT_SEARCH_PROMPT,
        ),
        "tests": AgentConfig(
            name="tests",
            description="Test execution, output collection, and failure diagnosis",
            model_role=RoleClass.IMPLEMENTATION,
            read_only=False,
            enabled=True,
            system_prompt=DEFAULT_TESTS_PROMPT,
        ),
        "docs": AgentConfig(
            name="docs",
            description="Technical documentation, API reference, and compatibility research (read-only)",
            model_role=RoleClass.SUPPORT,
            read_only=True,
            enabled=True,
            system_prompt=DEFAULT_DOCS_PROMPT,
        ),
    }

    permissions = PermissionsConfig(
        allow_dangerous_bypass=False,
        ask_approval=ApprovalPolicy.ON_REQUEST,
        sandbox=SandboxMode.WORKSPACE_WRITE,
    )

    overrides = {
        "claude": {
            "opus_plan": True,
        },
        "codex": {
            "model_reasoning_effort": "high",
        },
        "agy": {
            "mode": "auto",
        },
    }

    return Policy(
        schema_version=DEFAULT_POLICY_VERSION,
        enabled_providers=[ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY],
        roles=roles,
        agents=agents,
        permissions=permissions,
        overrides=overrides,
    )


def serialize_policy_toml(policy: Policy) -> str:
    """Serialize a Policy object to human-readable TOML with comments."""
    lines: list[str] = [
        "# HowlAlign Declarative AI Coding Assistant Policy",
        f'schema_version = "{policy.schema_version}"',
        "",
        "[providers]",
        f"enabled = {[p.value for p in policy.enabled_providers]!r}",
        "",
        "# Model Role Configurations",
    ]

    for role_name in (RoleClass.PLANNING, RoleClass.IMPLEMENTATION, RoleClass.SUPPORT):
        rc = policy.roles.get(role_name)
        if rc:
            lines.append(f"[roles.{role_name.value}]")
            lines.append(f'description = "{rc.description}"')
            lines.append(f'claude_model = "{rc.claude_model}"')
            lines.append(f'codex_model = "{rc.codex_model}"')
            lines.append(f'agy_model = "{rc.agy_model}"')
            lines.append(f'effort = "{rc.effort.value}"')
            if rc.provider_effort:
                lines.append("")
                lines.append(f"[roles.{role_name.value}.provider_effort]")
                for prov in (ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY):
                    if prov in rc.provider_effort:
                        lines.append(f'{prov.value} = "{rc.provider_effort[prov].value}"')
            lines.append("")

    lines.append("# Specialized Agent Definitions")
    for agent_name, ac in policy.agents.items():
        lines.append(f"[agents.{agent_name}]")
        lines.append(f"enabled = {'true' if ac.enabled else 'false'}")
        lines.append(f'description = "{ac.description}"')
        lines.append(f'model_role = "{ac.model_role.value}"')
        lines.append(f"read_only = {'true' if ac.read_only else 'false'}")
        if ac.system_prompt:
            # Escape triple single quotes if present
            clean_prompt = ac.system_prompt.strip()
            lines.append(f"system_prompt = '''\n{clean_prompt}\n'''")
        lines.append("")

    lines.append("# Security & Permission Boundaries")
    lines.append("[permissions]")
    lines.append(
        f"allow_dangerous_bypass = {'true' if policy.permissions.allow_dangerous_bypass else 'false'}"
    )
    lines.append(f'ask_approval = "{policy.permissions.ask_approval.value}"')
    lines.append(f'sandbox = "{policy.permissions.sandbox.value}"')

    if policy.permissions.providers:
        for prov in (ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.AGY):
            if prov in policy.permissions.providers:
                pp = policy.permissions.providers[prov]
                lines.append("")
                lines.append(f"[permissions.providers.{prov.value}]")
                if pp.allow_dangerous_bypass is not None:
                    lines.append(
                        f"allow_dangerous_bypass = {'true' if pp.allow_dangerous_bypass else 'false'}"
                    )
                if pp.ask_approval is not None:
                    lines.append(f'ask_approval = "{pp.ask_approval.value}"')
                if pp.sandbox is not None:
                    lines.append(f'sandbox = "{pp.sandbox.value}"')
    lines.append("")

    lines.append("# Provider Specific Overrides")
    for prov, opts in policy.overrides.items():
        lines.append(f"[overrides.{prov}]")
        for k, v in opts.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            else:
                lines.append(f"{k} = {v!r}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def load_policy_from_dict(data: dict[str, Any]) -> Policy:
    """Validate and convert dictionary data into a Policy object."""
    schema_version = str(data.get("schema_version", ""))
    if not schema_version:
        raise PolicyValidationError("Policy missing required field 'schema_version'")
    if schema_version not in SUPPORTED_POLICY_VERSIONS:
        raise PolicyValidationError(
            f"Unsupported policy schema_version '{schema_version}'. Supported: {sorted(SUPPORTED_POLICY_VERSIONS)}"
        )

    # Providers
    providers_sec = data.get("providers", {})
    if not isinstance(providers_sec, dict):
        raise PolicyValidationError("Invalid [providers] section: expected table")
    raw_enabled = providers_sec.get("enabled", ["claude", "codex", "agy"])
    if not isinstance(raw_enabled, list):
        raise PolicyValidationError(
            f"Invalid providers.enabled: expected list of strings, got {type(raw_enabled).__name__}"
        )
    enabled_providers: list[ProviderType] = []
    for p in raw_enabled:
        if not isinstance(p, str):
            raise PolicyValidationError(
                f"Invalid provider entry in providers.enabled: expected string, got {type(p).__name__}"
            )
        try:
            enabled_providers.append(ProviderType(p.lower()))
        except ValueError:
            valid_providers = [x.value for x in ProviderType]
            raise PolicyValidationError(
                f"Unknown provider '{p}' in providers.enabled. Valid options: {valid_providers}"
            )

    # Roles
    roles: dict[RoleClass, RoleConfig] = {}
    roles_sec = data.get("roles", {})
    if not isinstance(roles_sec, dict):
        raise PolicyValidationError("Invalid [roles] section: expected table")

    for role_key in ("planning", "implementation", "support"):
        r_data = roles_sec.get(role_key, {})
        if not isinstance(r_data, dict):
            raise PolicyValidationError(f"Invalid roles.{role_key} configuration: expected table")
        rc_enum = RoleClass(role_key)

        if "effort" in r_data:
            effort_str = r_data["effort"]
            if not isinstance(effort_str, str):
                raise PolicyValidationError(
                    f"Invalid type for roles.{role_key}.effort: expected string, got {type(effort_str).__name__}"
                )
            try:
                effort = EffortLevel(effort_str.lower())
            except ValueError:
                valid_efforts = [x.value for x in EffortLevel]
                raise PolicyValidationError(
                    f"Invalid effort '{effort_str}' for role '{role_key}'. Valid options: {valid_efforts}"
                )
        else:
            effort = EffortLevel.MEDIUM

        prov_effort: dict[ProviderType, EffortLevel] = {}
        if "provider_effort" in r_data:
            pe_data = r_data["provider_effort"]
            if not isinstance(pe_data, dict):
                raise PolicyValidationError(
                    f"Invalid type for roles.{role_key}.provider_effort: expected table, got {type(pe_data).__name__}"
                )
            for p_key, p_eff in pe_data.items():
                if not isinstance(p_key, str):
                    raise PolicyValidationError(
                        f"Invalid provider key in roles.{role_key}.provider_effort: expected string, got {type(p_key).__name__}"
                    )
                try:
                    p_enum = ProviderType(p_key.lower())
                except ValueError:
                    valid_provs = [x.value for x in ProviderType]
                    raise PolicyValidationError(
                        f"Unknown provider '{p_key}' in roles.{role_key}.provider_effort. Valid options: {valid_provs}"
                    )
                if not isinstance(p_eff, str):
                    raise PolicyValidationError(
                        f"Invalid type for roles.{role_key}.provider_effort.{p_key}: expected string, got {type(p_eff).__name__}"
                    )
                try:
                    prov_effort[p_enum] = EffortLevel(p_eff.lower())
                except ValueError:
                    valid_efforts = [x.value for x in EffortLevel]
                    raise PolicyValidationError(
                        f"Invalid effort '{p_eff}' for provider '{p_key}' in role '{role_key}'. Valid options: {valid_efforts}"
                    )

        # Also support direct claude_effort, codex_effort, agy_effort if provided
        for p_type, attr_name in (
            (ProviderType.CLAUDE, "claude_effort"),
            (ProviderType.CODEX, "codex_effort"),
            (ProviderType.AGY, "agy_effort"),
        ):
            if attr_name in r_data and p_type not in prov_effort:
                raw_eff = r_data[attr_name]
                if not isinstance(raw_eff, str):
                    raise PolicyValidationError(
                        f"Invalid type for roles.{role_key}.{attr_name}: expected string, got {type(raw_eff).__name__}"
                    )
                try:
                    prov_effort[p_type] = EffortLevel(raw_eff.lower())
                except ValueError:
                    valid_efforts = [x.value for x in EffortLevel]
                    raise PolicyValidationError(
                        f"Invalid effort '{raw_eff}' for roles.{role_key}.{attr_name}. Valid options: {valid_efforts}"
                    )

        roles[rc_enum] = RoleConfig(
            claude_model=r_data.get("claude_model", "claude-sonnet-5"),
            codex_model=r_data.get("codex_model", "gpt-6.1-sol"),
            agy_model=r_data.get("agy_model", "gemini-3.8-flash-high"),
            effort=effort,
            description=r_data.get("description", ""),
            provider_effort=prov_effort,
        )

    # Agents
    agents: dict[str, AgentConfig] = {}
    agents_sec = data.get("agents", {})
    if not isinstance(agents_sec, dict):
        raise PolicyValidationError("Invalid [agents] section: expected table")
    default_policy = get_default_policy()

    for agent_key, a_data in agents_sec.items():
        if not isinstance(a_data, dict):
            raise PolicyValidationError(
                f"Invalid definition for agent '{agent_key}': expected table"
            )

        if "model_role" in a_data:
            role_str = a_data["model_role"]
            if not isinstance(role_str, str):
                raise PolicyValidationError(
                    f"Invalid type for agents.{agent_key}.model_role: expected string, got {type(role_str).__name__}"
                )
            try:
                m_role = RoleClass(role_str.lower())
            except ValueError:
                valid_roles = [x.value for x in RoleClass]
                raise PolicyValidationError(
                    f"Invalid model_role '{role_str}' for agent '{agent_key}'. Valid options: {valid_roles}"
                )
        else:
            m_role = RoleClass.SUPPORT

        if "read_only" in a_data and not isinstance(a_data["read_only"], bool):
            raise PolicyValidationError(
                f"Invalid type for agents.{agent_key}.read_only: expected boolean, got {type(a_data['read_only']).__name__}"
            )
        if "enabled" in a_data and not isinstance(a_data["enabled"], bool):
            raise PolicyValidationError(
                f"Invalid type for agents.{agent_key}.enabled: expected boolean, got {type(a_data['enabled']).__name__}"
            )

        default_agent = default_policy.agents.get(agent_key)
        fallback_prompt = default_agent.system_prompt if default_agent else ""
        sys_prompt = a_data.get("system_prompt", fallback_prompt)

        agents[agent_key] = AgentConfig(
            name=agent_key,
            description=a_data.get("description", ""),
            model_role=m_role,
            read_only=bool(a_data.get("read_only", False)),
            enabled=bool(a_data.get("enabled", True)),
            system_prompt=sys_prompt,
        )

    # Permissions
    perm_sec = data.get("permissions", {})
    if not isinstance(perm_sec, dict):
        raise PolicyValidationError("Invalid [permissions] section: expected table")

    if "ask_approval" in perm_sec:
        ask_raw = perm_sec["ask_approval"]
        if not isinstance(ask_raw, str):
            raise PolicyValidationError(
                f"Invalid type for permissions.ask_approval: expected string, got {type(ask_raw).__name__}"
            )
        try:
            ask_app = ApprovalPolicy(ask_raw.lower())
        except ValueError:
            valid_policies = [x.value for x in ApprovalPolicy]
            raise PolicyValidationError(
                f"Invalid permissions.ask_approval '{ask_raw}'. Valid options: {valid_policies}"
            )
    else:
        ask_app = ApprovalPolicy.ON_REQUEST

    if "sandbox" in perm_sec:
        sandbox_raw = perm_sec["sandbox"]
        if not isinstance(sandbox_raw, str):
            raise PolicyValidationError(
                f"Invalid type for permissions.sandbox: expected string, got {type(sandbox_raw).__name__}"
            )
        try:
            sbox = SandboxMode(sandbox_raw.lower())
        except ValueError:
            valid_sandboxes = [x.value for x in SandboxMode]
            raise PolicyValidationError(
                f"Invalid permissions.sandbox '{sandbox_raw}'. Valid options: {valid_sandboxes}"
            )
    else:
        sbox = SandboxMode.WORKSPACE_WRITE

    if "allow_dangerous_bypass" in perm_sec and not isinstance(
        perm_sec["allow_dangerous_bypass"], bool
    ):
        raise PolicyValidationError(
            f"Invalid type for permissions.allow_dangerous_bypass: expected boolean, got {type(perm_sec['allow_dangerous_bypass']).__name__}"
        )

    prov_perms_map: dict[ProviderType, ProviderPermissionsConfig] = {}
    if "providers" in perm_sec:
        raw_providers = perm_sec["providers"]
        if not isinstance(raw_providers, dict):
            raise PolicyValidationError(
                f"Invalid [permissions.providers] section: expected table, got {type(raw_providers).__name__}"
            )
        for p_key, p_data in raw_providers.items():
            if not isinstance(p_key, str):
                raise PolicyValidationError(
                    f"Invalid provider entry in permissions.providers: expected string, got {type(p_key).__name__}"
                )
            try:
                p_enum = ProviderType(p_key.lower())
            except ValueError:
                valid_provs = [x.value for x in ProviderType]
                raise PolicyValidationError(
                    f"Unknown provider '{p_key}' in permissions.providers. Valid options: {valid_provs}"
                )
            if not isinstance(p_data, dict):
                raise PolicyValidationError(
                    f"Invalid configuration for permissions.providers.{p_key}: expected table, got {type(p_data).__name__}"
                )

            p_ask_app: ApprovalPolicy | None = None
            if "ask_approval" in p_data:
                raw_val = p_data["ask_approval"]
                if not isinstance(raw_val, str):
                    raise PolicyValidationError(
                        f"Invalid type for permissions.providers.{p_key}.ask_approval: expected string, got {type(raw_val).__name__}"
                    )
                try:
                    p_ask_app = ApprovalPolicy(raw_val.lower())
                except ValueError:
                    valid_policies = [x.value for x in ApprovalPolicy]
                    raise PolicyValidationError(
                        f"Invalid permissions.providers.{p_key}.ask_approval '{raw_val}'. Valid options: {valid_policies}"
                    )

            p_sbox: SandboxMode | None = None
            if "sandbox" in p_data:
                raw_val = p_data["sandbox"]
                if not isinstance(raw_val, str):
                    raise PolicyValidationError(
                        f"Invalid type for permissions.providers.{p_key}.sandbox: expected string, got {type(raw_val).__name__}"
                    )
                try:
                    p_sbox = SandboxMode(raw_val.lower())
                except ValueError:
                    valid_sandboxes = [x.value for x in SandboxMode]
                    raise PolicyValidationError(
                        f"Invalid permissions.providers.{p_key}.sandbox '{raw_val}'. Valid options: {valid_sandboxes}"
                    )

            p_bypass: bool | None = None
            if "allow_dangerous_bypass" in p_data:
                raw_val = p_data["allow_dangerous_bypass"]
                if not isinstance(raw_val, bool):
                    raise PolicyValidationError(
                        f"Invalid type for permissions.providers.{p_key}.allow_dangerous_bypass: expected boolean, got {type(raw_val).__name__}"
                    )
                p_bypass = raw_val

            prov_perms_map[p_enum] = ProviderPermissionsConfig(
                ask_approval=p_ask_app,
                sandbox=p_sbox,
                allow_dangerous_bypass=p_bypass,
            )

    permissions = PermissionsConfig(
        allow_dangerous_bypass=bool(perm_sec.get("allow_dangerous_bypass", False)),
        ask_approval=ask_app,
        sandbox=sbox,
        providers=prov_perms_map,
    )

    overrides = data.get("overrides", {})

    return Policy(
        schema_version=schema_version,
        enabled_providers=enabled_providers,
        roles=roles,
        agents=agents,
        permissions=permissions,
        overrides=overrides,
    )


def load_policy_file(path: Path | str) -> Policy:
    """Load and parse policy from a TOML file path with domain error handling."""
    target = Path(path).resolve()
    if not target.is_file():
        raise PolicyNotFoundError(f"Policy file not found: {target}")

    try:
        with open(target, "rb") as f:
            data = tomllib.load(f)
    except Exception as err:
        raise PolicySyntaxError(f"Failed to parse policy TOML file at '{target}': {err}") from err

    return load_policy_from_dict(data)


def discover_policy_file(custom_path: str | Path | None = None) -> Path | None:
    """Locate the effective howlalign policy file."""
    if custom_path:
        p = Path(custom_path).resolve()
        return p if p.is_file() else None

    # Check project-level
    candidates = [
        Path.cwd() / POLICY_FILENAME,
        Path.cwd() / HIDDEN_POLICY_FILENAME,
    ]
    for c in candidates:
        if c.is_file():
            return c

    # Walk up to git root if present
    cur = Path.cwd()
    while cur != cur.parent:
        if (cur / ".git").is_dir():
            for c in (cur / POLICY_FILENAME, cur / HIDDEN_POLICY_FILENAME):
                if c.is_file():
                    return c
            break
        cur = cur.parent

    # Global level
    home = Path.home()
    global_candidates = [
        home / ".config" / "howlalign" / POLICY_FILENAME,
        home / HIDDEN_POLICY_FILENAME,
    ]
    for g in global_candidates:
        if g.is_file():
            return g

    return None


def init_policy_file(
    path: str | Path | None = None,
    is_global: bool = False,
    force: bool = False,
) -> Path:
    """Initialize a new howlalign.toml policy file."""
    if path:
        target = Path(path).resolve()
        if target.is_dir():
            target = target / POLICY_FILENAME
    elif is_global:
        config_dir = Path.home() / ".config" / "howlalign"
        config_dir.mkdir(parents=True, exist_ok=True)
        target = config_dir / POLICY_FILENAME
    else:
        target = Path.cwd() / POLICY_FILENAME

    if target.is_file() and not force:
        raise FileExistsError(f"Policy file already exists at: {target}")

    policy = get_default_policy()
    content = serialize_policy_toml(policy)

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)

    return target
