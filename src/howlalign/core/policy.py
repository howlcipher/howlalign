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
    raw_enabled = providers_sec.get("enabled", ["claude", "codex", "agy"])
    enabled_providers: list[ProviderType] = []
    for p in raw_enabled:
        try:
            enabled_providers.append(ProviderType(p.lower()))
        except ValueError:
            pass

    # Roles
    roles: dict[RoleClass, RoleConfig] = {}
    roles_sec = data.get("roles", {})
    for role_key in ("planning", "implementation", "support"):
        r_data = roles_sec.get(role_key, {})
        rc_enum = RoleClass(role_key)
        effort_str = r_data.get("effort", "medium").lower()
        try:
            effort = EffortLevel(effort_str)
        except ValueError:
            effort = EffortLevel.MEDIUM

        roles[rc_enum] = RoleConfig(
            claude_model=r_data.get("claude_model", "claude-sonnet-5"),
            codex_model=r_data.get("codex_model", "gpt-6.1-sol"),
            agy_model=r_data.get("agy_model", "gemini-3.8-flash-high"),
            effort=effort,
            description=r_data.get("description", ""),
        )

    # Agents
    agents: dict[str, AgentConfig] = {}
    agents_sec = data.get("agents", {})
    default_policy = get_default_policy()

    for agent_key, a_data in agents_sec.items():
        role_str = a_data.get("model_role", "support").lower()
        try:
            m_role = RoleClass(role_str)
        except ValueError:
            m_role = RoleClass.SUPPORT

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
    try:
        ask_app = ApprovalPolicy(perm_sec.get("ask_approval", "on-request").lower())
    except ValueError:
        ask_app = ApprovalPolicy.ON_REQUEST

    try:
        sbox = SandboxMode(perm_sec.get("sandbox", "workspace-write").lower())
    except ValueError:
        sbox = SandboxMode.WORKSPACE_WRITE

    permissions = PermissionsConfig(
        allow_dangerous_bypass=bool(perm_sec.get("allow_dangerous_bypass", False)),
        ask_approval=ask_app,
        sandbox=sbox,
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
