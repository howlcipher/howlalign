"""Google Antigravity CLI (AGY) native configuration adapter."""

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


class AgyAdapter(BaseAdapter):
    """Translates HowlAlign policy to native Google Antigravity CLI (AGY) configuration."""

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.AGY

    def _get_global_settings_path(self) -> Path:
        return self.home / ".gemini" / "antigravity-cli" / "settings.json"

    def _get_workspace_agents_dir(self) -> Path:
        return self.workspace / ".agents"

    def _generate_global_settings(
        self,
        policy: Policy,
        existing_content: str | None,
    ) -> str:
        data: dict[str, Any] = {}
        if existing_content:
            try:
                data = json.loads(existing_content)
            except Exception:
                data = {}

        # Default model
        impl_role = policy.roles.get(RoleClass.IMPLEMENTATION)
        if impl_role:
            data["model"] = impl_role.agy_model

        # Permissions mode
        if policy.permissions.ask_approval == ApprovalPolicy.NEVER:
            data["toolPermission"] = "always-proceed"
        elif policy.permissions.ask_approval == ApprovalPolicy.ALWAYS:
            data["toolPermission"] = "request-review"
        else:
            data["toolPermission"] = "proceed-in-sandbox"

        return json.dumps(data, indent=2) + "\n"

    def _generate_skill_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
    ) -> str:
        return f"""---
name: {name}
description: >-
  {description}
---

# {name.capitalize()} Skill

{prompt.strip()}
"""

    def _generate_agent_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
        model: str = "gemini-3.8-flash-high",
    ) -> str:
        return f"""---
name: {name}
description: >-
  {description}
mainAgent: false
subagent: true
model: {model}
---

# {name.capitalize()} Agent

{prompt.strip()}
"""

    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        changes: list[ConfigChange] = []

        if is_global:
            # Global settings.json
            settings_path = self._get_global_settings_path()
            existing = (
                settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None
            )
            proposed = self._generate_global_settings(policy, existing)
            changes.append(
                ConfigChange(
                    file_path=settings_path,
                    original_content=existing,
                    proposed_content=proposed,
                    description="Align AGY CLI global settings",
                    provider=ProviderType.AGY,
                    is_creation=existing is None,
                )
            )
            return changes

        # Workspace project changes
        agents_root = self._get_workspace_agents_dir()

        # 1. Workspace Skills
        for agent_name, agent_cfg in policy.agents.items():
            if not agent_cfg.enabled:
                continue

            skill_file = agents_root / "skills" / agent_name / "SKILL.md"
            existing_skill = (
                skill_file.read_text(encoding="utf-8") if skill_file.is_file() else None
            )
            proposed_skill = self._generate_skill_markdown(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
            )

            changes.append(
                ConfigChange(
                    file_path=skill_file,
                    original_content=existing_skill,
                    proposed_content=proposed_skill,
                    description=f"Align AGY workspace skill '{agent_name}'",
                    provider=ProviderType.AGY,
                    is_creation=existing_skill is None,
                )
            )

        # 2. Workspace Agents
        for agent_name, agent_cfg in policy.agents.items():
            if not agent_cfg.enabled:
                continue

            agent_file = agents_root / "agents" / agent_name / "agent.md"
            existing_agent = (
                agent_file.read_text(encoding="utf-8") if agent_file.is_file() else None
            )
            role_cfg = policy.roles.get(agent_cfg.model_role)
            model_slug = role_cfg.agy_model if role_cfg else "gemini-3.8-flash-high"

            proposed_agent = self._generate_agent_markdown(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
                model=model_slug,
            )

            changes.append(
                ConfigChange(
                    file_path=agent_file,
                    original_content=existing_agent,
                    proposed_content=proposed_agent,
                    description=f"Align AGY specialized subagent '{agent_name}'",
                    provider=ProviderType.AGY,
                    is_creation=existing_agent is None,
                )
            )

        # 3. GEMINI.md in workspace root
        gemini_md_path = self.workspace / "GEMINI.md"
        existing_gemini_md = (
            gemini_md_path.read_text(encoding="utf-8") if gemini_md_path.is_file() else None
        )

        if existing_gemini_md is None:
            proposed_gemini_md = f"""# Workspace Rules (Aligned via HowlAlign)

This workspace is aligned to HowlAlign policy schema v{policy.schema_version}.

## Guidelines
- Follow hierarchical planning: resolve architecture before issuing code edits.
- Use progressive skills in `.agents/skills/` when executing domain-specific procedures.
- Specialized agents: delegate repository discovery to `search` and test analysis to `tests`.
- Keep rules concise and under the 24 KB aggregate budget.
"""
            changes.append(
                ConfigChange(
                    file_path=gemini_md_path,
                    original_content=None,
                    proposed_content=proposed_gemini_md,
                    description="Create project GEMINI.md rules",
                    provider=ProviderType.AGY,
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
                    message="Google Antigravity CLI ('agy') is not found on PATH.",
                    provider="agy",
                    action="Install AGY CLI or configure PATH.",
                )
            )
            return items

        items.append(
            DiagnosticItem(
                severity="INFO",
                category="VERSION",
                message=f"AGY CLI detected at {info.executable_path} (version: {info.version or 'unknown'}).",
                provider="agy",
            )
        )

        # Check rule file size limit if GEMINI.md exists
        gemini_md = self.workspace / "GEMINI.md"
        if gemini_md.is_file():
            size = gemini_md.stat().st_size
            if size > 24000:
                items.append(
                    DiagnosticItem(
                        severity="WARNING",
                        category="COMPATIBILITY",
                        message=f"GEMINI.md size ({size} bytes) exceeds AGY 24 KB limit and will be truncated by CLI.",
                        provider="agy",
                        action="Reduce GEMINI.md content below 24,000 bytes.",
                    )
                )

        return items
