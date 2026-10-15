"""Claude Code native configuration adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from howlalign.adapters.base import BaseAdapter
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
        is_global: bool,
    ) -> str:
        data: dict[str, Any] = {}
        if existing_content:
            try:
                data = json.loads(existing_content)
            except Exception:
                data = {}

        # 1. Model resolution
        claude_overrides = policy.overrides.get("claude", {})
        use_opus_plan = claude_overrides.get("opus_plan", True)
        if use_opus_plan:
            data["model"] = "opusplan"
        else:
            impl_role = policy.roles.get(RoleClass.IMPLEMENTATION)
            if impl_role:
                data["model"] = impl_role.claude_model

        # 2. Effort settings
        model_settings = data.setdefault("modelSettings", {})
        plan_role = policy.roles.get(RoleClass.PLANNING)
        if plan_role:
            plan_entry = model_settings.setdefault(plan_role.claude_model, {})
            plan_entry["effortLevel"] = plan_role.effort.value

        impl_role = policy.roles.get(RoleClass.IMPLEMENTATION)
        if impl_role:
            impl_entry = model_settings.setdefault(impl_role.claude_model, {})
            impl_entry["effortLevel"] = impl_role.effort.value

        # 3. Permissions
        permissions = data.setdefault("permissions", {})
        if policy.permissions.ask_approval == ApprovalPolicy.NEVER:
            permissions["defaultMode"] = "acceptEdits"
        elif policy.permissions.ask_approval == ApprovalPolicy.ALWAYS:
            permissions["defaultMode"] = "default"
        else:
            permissions["defaultMode"] = "acceptEdits"

        # Safe defaults for tools
        allow_list = permissions.setdefault("allow", [])
        safe_defaults = [
            "Bash(git status)",
            "Bash(git diff)",
            "Bash(git log *)",
        ]
        for item in safe_defaults:
            if item not in allow_list:
                allow_list.append(item)

        return json.dumps(data, indent=2) + "\n"

    def _generate_agent_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
        tools: list[str],
        disallowed_tools: list[str],
        permission_mode: str,
        model: str = "inherit",
    ) -> str:
        tools_formatted = "\n".join(f"  - {t}" for t in tools)
        disallowed_formatted = "\n".join(f"  - {t}" for t in disallowed_tools)
        return f"""---
name: {name}
description: {description}
tools:
{tools_formatted}
disallowedTools:
{disallowed_formatted}
model: {model}
permissionMode: {permission_mode}
---

{prompt.strip()}
"""

    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        changes: list[ConfigChange] = []

        # 1. Settings JSON
        settings_path = self._get_target_settings_path(is_global)
        existing_settings = (
            settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None
        )
        proposed_settings = self._generate_settings_content(policy, existing_settings, is_global)

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

            tool_spec = agent_tool_map.get(
                agent_name,
                {
                    "tools": ["Read", "Glob", "Grep"],
                    "disallowed": ["Edit", "Write"],
                    "mode": "plan",
                },
            )
            agent_file = agents_dir / f"{agent_name}.md"
            existing_agent = (
                agent_file.read_text(encoding="utf-8") if agent_file.is_file() else None
            )
            proposed_agent = self._generate_agent_markdown(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
                tools=tool_spec["tools"],
                disallowed_tools=tool_spec["disallowed"],
                permission_mode=tool_spec["mode"],
                model="inherit",
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
            existing_claude_md = (
                claude_md_path.read_text(encoding="utf-8") if claude_md_path.is_file() else None
            )

            # If CLAUDE.md already exists, preserve it and only ensure alignment header if empty
            if existing_claude_md is None:
                proposed_claude_md = f"""# Project Engineering Guidelines (Aligned via HowlAlign)

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
        if policy.permissions.allow_dangerous_bypass:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message="Policy specifies 'allow_dangerous_bypass = true'. Claude Code security policy blocks bypass mode from repository settings.",
                    provider="claude",
                    action="Disable allow_dangerous_bypass in policy or pass flag at runtime.",
                )
            )

        # Check settings path
        settings_path = self._get_target_settings_path(is_global)
        if not settings_path.is_file():
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="CONFIGURATION",
                    message=f"No existing settings found at {settings_path}. Will be initialized on apply.",
                    provider="claude",
                )
            )

        return items
