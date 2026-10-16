"""Claude Code native configuration adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from howlalign.adapters.base import (
    BaseAdapter,
    embed_managed_fingerprint,
    has_user_modifications,
    is_file_managed_by_howlalign,
    safe_read_text,
)
from howlalign.core.constants import MANAGED_BY_MARKER_MD
from howlalign.core.exceptions import ConfigurationParseError
from howlalign.core.models import (
    ApprovalPolicy,
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
    RoleClass,
)


class ClaudeAdapter(BaseAdapter):
    """Translates HowlAlign policy to native Claude Code configuration."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CLAUDE

    def _get_target_settings_path(self, is_global: bool) -> Path:
        if is_global:
            return self.home / ".claude" / "settings.json"
        return self.workspace / ".claude" / "settings.json"

    def _get_agents_dir(self, is_global: bool) -> Path:
        if is_global:
            return self.home / ".claude" / "agents"
        return self.workspace / ".claude" / "agents"

    def _generate_settings_content(
        self,
        policy: Policy,
        existing_content: str | None,
        settings_path: Path,
    ) -> str:
        data: dict[str, Any] = {}
        if existing_content and existing_content.strip():
            try:
                data = json.loads(existing_content)
            except Exception as err:
                raise ConfigurationParseError(settings_path, "JSON", err) from err

        # 1. Model resolution
        claude_overrides = policy.overrides.get("claude", {})
        use_opus_plan = claude_overrides.get("opus_plan", True)
        if use_opus_plan:
            data["model"] = "opusplan"
        else:
            data["model"] = policy.get_effective_model(
                ProviderType.CLAUDE, RoleClass.IMPLEMENTATION
            )

        # 2. Effort settings
        model_settings = data.setdefault("modelSettings", {})
        for role_class in (RoleClass.PLANNING, RoleClass.IMPLEMENTATION, RoleClass.SUPPORT):
            model_name = policy.get_effective_model(ProviderType.CLAUDE, role_class)
            effort = policy.get_effective_effort(ProviderType.CLAUDE, role_class)
            m_entry = model_settings.setdefault(model_name, {})
            m_entry["effortLevel"] = effort.value

        # 3. Permissions - conservative mapping
        eff_perms = policy.get_effective_permissions(ProviderType.CLAUDE)
        permissions = data.setdefault("permissions", {})
        if eff_perms.ask_approval == ApprovalPolicy.NEVER:
            permissions["defaultMode"] = "acceptEdits"
        elif eff_perms.ask_approval == ApprovalPolicy.ALWAYS:
            permissions["defaultMode"] = "default"
        else:
            # Default ON_REQUEST maps conservatively to standard "default" (prompts before mutations)
            permissions["defaultMode"] = "default"

        return json.dumps(data, indent=2) + "\n"

    def _generate_agent_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
        tools: list[str],
        disallowed_tools: list[str],
        permission_mode: str,
        model: str,
    ) -> str:
        tools_formatted = "\n".join(f"  - {t}" for t in tools)
        disallowed_formatted = "\n".join(f"  - {t}" for t in disallowed_tools)
        raw = f"""---
managed_by: howlalign
name: {name}
description: {description}
tools:
{tools_formatted}
disallowedTools:
{disallowed_formatted}
model: {model}
permissionMode: {permission_mode}
---

<!-- {MANAGED_BY_MARKER_MD} -->
{prompt.strip()}
"""
        return embed_managed_fingerprint(raw, format_type="md")

    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        changes: list[ConfigChange] = []

        # 1. Settings JSON
        settings_path = self._get_target_settings_path(is_global)
        existing_settings = safe_read_text(settings_path)
        proposed_settings = self._generate_settings_content(
            policy, existing_settings, settings_path
        )

        changes.append(
            ConfigChange(
                file_path=settings_path,
                original_content=existing_settings,
                proposed_content=proposed_settings,
                description=f"Align Claude Code {'global' if is_global else 'project'} settings",
                provider=ProviderType.CLAUDE,
                is_creation=existing_settings is None,
            )
        )

        # 2. Custom Agents
        agents_dir = self._get_agents_dir(is_global)
        agent_tool_map = {
            "search": {
                "tools": ["Read", "Glob", "Grep", "WebSearch"],
                "disallowed": ["Edit", "Write", "NotebookEdit", "Bash"],
                "mode": "plan",
            },
            "tests": {
                "tools": ["Read", "Glob", "Grep", "Bash"],
                "disallowed": ["Edit", "Write", "NotebookEdit"],
                "mode": "acceptEdits",
            },
            "docs": {
                "tools": ["Read", "WebFetch", "WebSearch"],
                "disallowed": ["Edit", "Write", "NotebookEdit", "Bash"],
                "mode": "plan",
            },
        }

        for agent_name, agent_cfg in policy.agents.items():
            if not agent_cfg.enabled:
                continue

            agent_file = agents_dir / f"{agent_name}.md"
            existing_agent = safe_read_text(agent_file)

            # Conflict Detection: Avoid silently overwriting user-authored or user-modified agent files
            if existing_agent is not None:
                if not is_file_managed_by_howlalign(existing_agent, "md"):
                    changes.append(
                        ConfigChange(
                            file_path=agent_file,
                            original_content=existing_agent,
                            proposed_content=existing_agent,
                            description=f"User-authored custom agent '{agent_name}' detected. Preserved without modification.",
                            provider=ProviderType.CLAUDE,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue
                elif has_user_modifications(existing_agent, "md"):
                    changes.append(
                        ConfigChange(
                            file_path=agent_file,
                            original_content=existing_agent,
                            proposed_content=existing_agent,
                            description=f"User modifications detected in managed agent '{agent_name}'. Preserved without modification.",
                            provider=ProviderType.CLAUDE,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue

            # Determine tools based on configuration or default map
            tool_spec = agent_tool_map.get(
                agent_name,
                {
                    "tools": ["Read", "Glob", "Grep"]
                    if agent_cfg.read_only
                    else ["Read", "Glob", "Grep", "Edit", "Write"],
                    "disallowed": ["Edit", "Write"] if agent_cfg.read_only else [],
                    "mode": "plan" if agent_cfg.read_only else "default",
                },
            )

            # Dynamic Model Resolution: Support role uses Haiku, Implementation uses Sonnet
            model_target = policy.get_effective_model(ProviderType.CLAUDE, agent_cfg.model_role)

            proposed_agent = self._generate_agent_markdown(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
                tools=tool_spec["tools"],
                disallowed_tools=tool_spec["disallowed"],
                permission_mode=tool_spec["mode"],
                model=model_target,
            )

            changes.append(
                ConfigChange(
                    file_path=agent_file,
                    original_content=existing_agent,
                    proposed_content=proposed_agent,
                    description=f"Align Claude Code specialized agent '{agent_name}'",
                    provider=ProviderType.CLAUDE,
                    is_creation=existing_agent is None,
                )
            )

        # 3. Project-level CLAUDE.md
        if not is_global:
            claude_md_path = self.workspace / "CLAUDE.md"
            existing_claude_md = safe_read_text(claude_md_path)

            if existing_claude_md is None:
                proposed_claude_md = f"""# Project Engineering Guidelines (Aligned via HowlAlign)
<!-- {MANAGED_BY_MARKER_MD} -->

This repository is aligned with HowlAlign policy schema v{policy.schema_version}.

## Workflow Expectations
- Planning Role: Focus on system architecture, design tradeoffs, and complex defects.
- Implementation Role: Clean feature implementation with robust automated tests.
- Specialized Agents: Use `/search` for symbol discovery, `/tests` for diagnostic runs, and `/docs` for API lookups.
- Security: Maintain strict permission boundaries and clean commit history.
"""
                changes.append(
                    ConfigChange(
                        file_path=claude_md_path,
                        original_content=None,
                        proposed_content=proposed_claude_md,
                        description="Create aligned project CLAUDE.md guidelines",
                        provider=ProviderType.CLAUDE,
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
                    message="Claude Code CLI ('claude') is not found on PATH.",
                    provider="claude",
                    action="Install Claude Code via npm or your package manager.",
                )
            )
            return items

        items.append(
            DiagnosticItem(
                severity="INFO",
                category="VERSION",
                message=f"Claude Code detected at {info.executable_path} (version: {info.version or 'unknown'}).",
                provider="claude",
            )
        )

        # Check permissions
        eff_perms = policy.get_effective_permissions(ProviderType.CLAUDE)
        if eff_perms.allow_dangerous_bypass:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message="Effective policy specifies 'allow_dangerous_bypass = true'. Claude Code security policy blocks bypass mode from repository settings.",
                    provider="claude",
                    action="Disable allow_dangerous_bypass in policy or pass flag at runtime.",
                )
            )

        # Report conflicting settings and permission escalations
        for conflict in policy.get_conflicting_settings(ProviderType.CLAUDE):
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="CONFIGURATION",
                    message=conflict,
                    provider="claude",
                )
            )

        for escalation in policy.detect_permission_escalation(ProviderType.CLAUDE):
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message=escalation,
                    provider="claude",
                    action="Review permissions.providers.claude to ensure widening was intended.",
                )
            )

        # Check existing settings syntax validity
        settings_path = self._get_target_settings_path(is_global)
        if settings_path.is_file():
            content = safe_read_text(settings_path)
            if content and content.strip():
                try:
                    json.loads(content)
                except Exception as err:
                    items.append(
                        DiagnosticItem(
                            severity="ERROR",
                            category="CONFIGURATION",
                            message=f"Existing Claude Code settings file at '{settings_path}' is malformed JSON: {err}",
                            provider="claude",
                            action="Repair syntax in settings.json to enable alignment.",
                        )
                    )
        else:
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="CONFIGURATION",
                    message=f"No existing settings found at {settings_path}. Will be initialized on apply.",
                    provider="claude",
                )
            )

        return items
