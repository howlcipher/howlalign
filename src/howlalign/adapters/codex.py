"""OpenAI Codex CLI native configuration adapter."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import toml

from howlalign.adapters.base import (
    BaseAdapter,
    compute_managed_fingerprint,
    has_user_modifications,
    is_file_managed_by_howlalign,
    safe_read_text,
)
from howlalign.core.constants import MANAGED_BY_MARKER_MD, MANAGED_BY_MARKER_TOML
from howlalign.core.exceptions import ConfigurationParseError
from howlalign.core.models import (
    ApprovalPolicy,
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
    RoleClass,
    SandboxMode,
)


class CodexAdapter(BaseAdapter):
    """Translates HowlAlign policy to native OpenAI Codex CLI configuration."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CODEX

    def _get_target_config_path(self, is_global: bool) -> Path:
        if is_global:
            codex_home = Path(os.environ.get("CODEX_HOME", str(self.home / ".codex")))
            return codex_home / "config.toml"
        return self.workspace / ".codex" / "config.toml"

    def _get_agents_dir(self, is_global: bool) -> Path:
        if is_global:
            codex_home = Path(os.environ.get("CODEX_HOME", str(self.home / ".codex")))
            return codex_home / "agents"
        return self.workspace / ".codex" / "agents"

    def _generate_config_content(
        self,
        policy: Policy,
        existing_content: str | None,
        cfg_path: Path,
        is_global: bool,
    ) -> str:
        data: dict[str, Any] = {}
        if existing_content and existing_content.strip():
            try:
                data = toml.loads(existing_content)
            except Exception as err:
                raise ConfigurationParseError(cfg_path, "TOML", err) from err

        # 1. Model resolution
        impl_role = policy.roles.get(RoleClass.IMPLEMENTATION)
        if impl_role:
            data["model"] = impl_role.codex_model
            data["model_reasoning_effort"] = impl_role.effort.value

        plan_role = policy.roles.get(RoleClass.PLANNING)
        if plan_role:
            data["plan_mode_reasoning_effort"] = plan_role.effort.value

        support_role = policy.roles.get(RoleClass.SUPPORT)
        if support_role:
            data["default_subagent_model"] = support_role.codex_model
            data["default_subagent_reasoning_effort"] = support_role.effort.value

        # Honor explicit provider overrides
        codex_overrides = policy.overrides.get("codex", {})
        if "model_reasoning_effort" in codex_overrides:
            data["model_reasoning_effort"] = codex_overrides["model_reasoning_effort"]
        if "plan_mode_reasoning_effort" in codex_overrides:
            data["plan_mode_reasoning_effort"] = codex_overrides["plan_mode_reasoning_effort"]

        # 2. Sandbox mode
        if policy.permissions.sandbox == SandboxMode.READ_ONLY:
            data["sandbox_mode"] = "read-only"
        elif policy.permissions.sandbox == SandboxMode.DANGER_FULL_ACCESS:
            data["sandbox_mode"] = "danger-full-access"
        else:
            data["sandbox_mode"] = "workspace-write"

        # 3. Approval policy
        if policy.permissions.ask_approval == ApprovalPolicy.NEVER:
            data["approval_policy"] = "never"
            data["approvals_reviewer"] = "auto_review"
        else:
            data["approval_policy"] = "on-request"
            data["approvals_reviewer"] = "user"

        # 4. Custom agents table with relative paths for project scope
        agents_table = data.setdefault("agents", {})
        for agent_name, agent_cfg in policy.agents.items():
            if not agent_cfg.enabled:
                continue

            # In project scope, use portable relative path: .codex/agents/<name>.toml
            config_file_ref = (
                f".codex/agents/{agent_name}.toml"
                if not is_global
                else str(self._get_agents_dir(True) / f"{agent_name}.toml")
            )

            # Preserve any existing user-configured agent settings while aligning core descriptor
            agent_entry = agents_table.setdefault(agent_name, {})
            agent_entry["description"] = agent_cfg.description
            agent_entry["config_file"] = config_file_ref

        return toml.dumps(data)

    def _generate_role_toml(
        self,
        name: str,
        description: str,
        prompt: str,
        model: str,
        effort: str,
        read_only: bool = False,
    ) -> str:
        role_data: dict[str, Any] = {
            "managed_by": "howlalign",
            "name": name,
            "description": description,
            "developer_instructions": prompt.strip(),
            "model": model,
            "model_reasoning_effort": effort,
            "nickname_candidates": [name, f"{name}-agent"],
        }
        if read_only:
            role_data["sandbox_mode"] = "read-only"

        role_body = toml.dumps(role_data)
        fp = compute_managed_fingerprint(role_body)
        return f'# {MANAGED_BY_MARKER_TOML}\n# managed_fingerprint = "{fp}"\n' + role_body

    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        changes: list[ConfigChange] = []

        # 1. config.toml
        cfg_path = self._get_target_config_path(is_global)
        existing_cfg = safe_read_text(cfg_path)
        proposed_cfg = self._generate_config_content(policy, existing_cfg, cfg_path, is_global)

        changes.append(
            ConfigChange(
                file_path=cfg_path,
                original_content=existing_cfg,
                proposed_content=proposed_cfg,
                description=f"Align Codex CLI {'global' if is_global else 'project'} config",
                provider=ProviderType.CODEX,
                is_creation=existing_cfg is None,
            )
        )

        # 2. Custom Agent Role TOML files
        agents_dir = self._get_agents_dir(is_global)
        for agent_name, agent_cfg in policy.agents.items():
            if not agent_cfg.enabled:
                continue

            role_file = agents_dir / f"{agent_name}.toml"
            existing_role = safe_read_text(role_file)

            # Conflict Detection: Preserve user-authored or user-modified agent files
            if existing_role is not None:
                if not is_file_managed_by_howlalign(existing_role, "toml"):
                    changes.append(
                        ConfigChange(
                            file_path=role_file,
                            original_content=existing_role,
                            proposed_content=existing_role,
                            description=f"User-authored Codex agent role '{agent_name}' detected. Preserved without modification.",
                            provider=ProviderType.CODEX,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue
                elif has_user_modifications(existing_role, "toml"):
                    changes.append(
                        ConfigChange(
                            file_path=role_file,
                            original_content=existing_role,
                            proposed_content=existing_role,
                            description=f"User modifications detected in managed Codex agent role '{agent_name}'. Preserved without modification.",
                            provider=ProviderType.CODEX,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue

            agent_role_class = agent_cfg.model_role
            role_cfg = policy.roles.get(agent_role_class)
            model = role_cfg.codex_model if role_cfg else "gpt-6.1-sol"
            effort = role_cfg.effort.value if role_cfg else "medium"

            proposed_role = self._generate_role_toml(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
                model=model,
                effort=effort,
                read_only=agent_cfg.read_only,
            )

            changes.append(
                ConfigChange(
                    file_path=role_file,
                    original_content=existing_role,
                    proposed_content=proposed_role,
                    description=f"Align Codex specialized agent role '{agent_name}'",
                    provider=ProviderType.CODEX,
                    is_creation=existing_role is None,
                )
            )

        # 3. AGENTS.md (at repository root if project level)
        if not is_global:
            agents_md_path = self.workspace / "AGENTS.md"
            existing_agents_md = safe_read_text(agents_md_path)

            if existing_agents_md is None:
                proposed_agents_md = f"""# AGENTS.md
<!-- {MANAGED_BY_MARKER_MD} -->

Repository engineering conventions aligned via HowlAlign (policy v{policy.schema_version}).

## Guidelines & Responsibilities
- Planning: Use strong reasoning for architecture and design.
- Implementation: Write clean, self-contained code accompanied by tests.
- Subagents: Use `spawn_agent` for search, testing, and documentation research when tasks can be decoupled.
- Verification: Always run tests and verify exit codes before concluding a task.
"""
                changes.append(
                    ConfigChange(
                        file_path=agents_md_path,
                        original_content=None,
                        proposed_content=proposed_agents_md,
                        description="Create project AGENTS.md guidelines",
                        provider=ProviderType.CODEX,
                        is_creation=True,
                    )
                )

        return changes

    def check_health(
        self,
        policy: Policy,
        info: ProviderInfo,
        is_global: bool = False,
    ) -> list[DiagnosticItem]:
        items: list[DiagnosticItem] = []

        if not info.installed:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="VERSION",
                    message="OpenAI Codex CLI ('codex') is not found on PATH.",
                    provider="codex",
                    action="Install Codex CLI or configure environment.",
                )
            )
            return items

        items.append(
            DiagnosticItem(
                severity="INFO",
                category="VERSION",
                message=f"Codex CLI detected at {info.executable_path} (version: {info.version or 'unknown'}).",
                provider="codex",
            )
        )

        # Check existing config syntax validity
        cfg_path = self._get_target_config_path(is_global)
        if cfg_path.is_file():
            content = safe_read_text(cfg_path)
            if content and content.strip():
                try:
                    toml.loads(content)
                except Exception as err:
                    items.append(
                        DiagnosticItem(
                            severity="ERROR",
                            category="CONFIGURATION",
                            message=f"Existing Codex config at '{cfg_path}' is malformed TOML: {err}",
                            provider="codex",
                            action="Repair syntax in config.toml to enable alignment.",
                        )
                    )

        # Check repository trust requirement for project configs
        if not is_global:
            codex_home = Path(os.environ.get("CODEX_HOME", str(self.home / ".codex")))
            user_config_path = codex_home / "config.toml"
            workspace_str = str(self.workspace)
            trusted = False
            if user_config_path.is_file():
                content = safe_read_text(user_config_path)
                if content and content.strip():
                    try:
                        u_data = toml.loads(content)
                        projects = u_data.get("projects", {})
                        if projects.get(workspace_str, {}).get("trust_level") == "trusted":
                            trusted = True
                    except Exception:
                        pass

            if not trusted:
                items.append(
                    DiagnosticItem(
                        severity="WARNING",
                        category="SECURITY",
                        message=f"Project '{self.workspace}' is not marked as trusted in user config. Codex CLI will ignore project-level .codex/config.toml until trusted.",
                        provider="codex",
                        action=f'Add [projects."{workspace_str}"] trust_level = "trusted" to {user_config_path}.',
                    )
                )

        return items
