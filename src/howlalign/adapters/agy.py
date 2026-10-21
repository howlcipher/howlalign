"""Google Antigravity CLI (AGY) native configuration adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from howlalign.adapters.base import (
    BaseAdapter,
    embed_managed_fingerprint,
    has_user_modifications,
    is_file_managed_by_howlalign,
    safe_read_text,
)
from howlalign.core.constants import (
    AGY_MAX_AGGREGATE_RULE_BYTES,
    AGY_MAX_RULE_BYTES,
    MANAGED_BY_MARKER_MD,
)
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
        settings_path: Path,
    ) -> str:
        data: dict[str, Any] = {}
        if existing_content and existing_content.strip():
            try:
                data = json.loads(existing_content)
            except Exception as err:
                raise ConfigurationParseError(settings_path, "JSON", err) from err

        # Implementation model and effort resolution via centralized engine
        data["model"] = policy.get_effective_model(ProviderType.AGY, RoleClass.IMPLEMENTATION)
        data["effort"] = policy.get_effective_effort(
            ProviderType.AGY, RoleClass.IMPLEMENTATION
        ).value

        # Permissions resolution via centralized engine
        eff_perms = policy.get_effective_permissions(ProviderType.AGY)
        if eff_perms.ask_approval == ApprovalPolicy.NEVER:
            data["toolPermission"] = "always-proceed"
        elif eff_perms.ask_approval == ApprovalPolicy.ALWAYS:
            data["toolPermission"] = "request-review"
        else:
            data["toolPermission"] = "proceed-in-sandbox"

        if eff_perms.sandbox == SandboxMode.DANGER_FULL_ACCESS:
            data["allowNonWorkspaceAccess"] = True

        # Apply mode override if specified
        agy_overrides = policy.overrides.get("agy", {})
        if "mode" in agy_overrides:
            data["mode"] = agy_overrides["mode"]

        return json.dumps(data, indent=2) + "\n"

    def _generate_skill_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
    ) -> str:
        raw = f"""---
managed_by: howlalign
name: {name}
description: >-
  {description}
---

<!-- {MANAGED_BY_MARKER_MD} -->
# {name.capitalize()} Skill

{prompt.strip()}
"""
        return embed_managed_fingerprint(raw, format_type="md")

    def _generate_agent_markdown(
        self,
        name: str,
        description: str,
        prompt: str,
        model: str,
        read_only: bool = False,
    ) -> str:
        disallowed_block = 'disallowedTools: ["Edit", "Write"]\n' if read_only else ""
        raw = f"""---
managed_by: howlalign
name: {name}
description: >-
  {description}
mainAgent: false
subagent: true
model: {model}
{disallowed_block}---

<!-- {MANAGED_BY_MARKER_MD} -->
# {name.capitalize()} Agent

{prompt.strip()}
"""
        return embed_managed_fingerprint(raw, format_type="md")

    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        changes: list[ConfigChange] = []

        if is_global:
            # Global settings.json
            settings_path = self._get_global_settings_path()
            existing = safe_read_text(settings_path)
            proposed = self._generate_global_settings(policy, existing, settings_path)
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
            existing_skill = safe_read_text(skill_file)

            # Conflict Detection: Avoid overwriting user-authored or user-modified skills
            if existing_skill is not None:
                if not is_file_managed_by_howlalign(existing_skill, "md"):
                    changes.append(
                        ConfigChange(
                            file_path=skill_file,
                            original_content=existing_skill,
                            proposed_content=existing_skill,
                            description=f"User-authored AGY skill '{agent_name}' detected. Preserved without modification.",
                            provider=ProviderType.AGY,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue
                elif has_user_modifications(existing_skill, "md"):
                    changes.append(
                        ConfigChange(
                            file_path=skill_file,
                            original_content=existing_skill,
                            proposed_content=existing_skill,
                            description=f"User modifications detected in managed AGY skill '{agent_name}'. Preserved without modification.",
                            provider=ProviderType.AGY,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue

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
            existing_agent = safe_read_text(agent_file)

            # Conflict Detection: Avoid overwriting user-authored or user-modified subagents
            if existing_agent is not None:
                if not is_file_managed_by_howlalign(existing_agent, "md"):
                    changes.append(
                        ConfigChange(
                            file_path=agent_file,
                            original_content=existing_agent,
                            proposed_content=existing_agent,
                            description=f"User-authored AGY agent '{agent_name}' detected. Preserved without modification.",
                            provider=ProviderType.AGY,
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
                            description=f"User modifications detected in managed AGY agent '{agent_name}'. Preserved without modification.",
                            provider=ProviderType.AGY,
                            is_user_owned_conflict=True,
                        )
                    )
                    continue

            model_slug = policy.get_effective_model(ProviderType.AGY, agent_cfg.model_role)

            proposed_agent = self._generate_agent_markdown(
                name=agent_name,
                description=agent_cfg.description,
                prompt=agent_cfg.system_prompt,
                model=model_slug,
                read_only=agent_cfg.read_only,
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
        existing_gemini_md = safe_read_text(gemini_md_path)

        if existing_gemini_md is None:
            proposed_gemini_md = f"""# Workspace Rules (Aligned via HowlAlign)
<!-- {MANAGED_BY_MARKER_MD} -->

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
        info: ProviderInfo | None = None,
        is_global: bool = False,
    ) -> list[DiagnosticItem]:
        items: list[DiagnosticItem] = []

        if info is not None and not info.installed:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="VERSION",
                    message="Google Antigravity CLI ('agy') is not found on PATH.",
                    provider="agy",
                    action="Install AGY CLI or configure PATH.",
                )
            )
        elif info is not None:
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="VERSION",
                    message=f"AGY CLI detected at {info.executable_path} (version: {info.version or 'unknown'}).",
                    provider="agy",
                )
            )

        # Settings are validated whether or not the CLI is installed.
        # Validate syntax of existing settings.json
        settings_path = self._get_global_settings_path()
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
                            message=f"Existing AGY settings file at '{settings_path}' is malformed JSON: {err}",
                            provider="agy",
                            action="Repair syntax in settings.json to enable alignment.",
                        )
                    )

        # Check planning model capability in AGY
        plan_role = policy.roles.get(RoleClass.PLANNING)
        impl_role = policy.roles.get(RoleClass.IMPLEMENTATION)
        if plan_role and impl_role and plan_role.agy_model != impl_role.agy_model:
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="COMPATIBILITY",
                    message=(
                        f"Policy specifies planning model '{plan_role.agy_model}' differing from implementation model '{impl_role.agy_model}'. "
                        "AGY CLI settings.json supports global 'model' configuration; use progressive skills or runtime launcher flags for specialized planning delegation."
                    ),
                    provider="agy",
                    action="Configure specialized planning skills in .agents/skills/ for automated model routing.",
                )
            )

        # Check conflicting settings
        for conflict in policy.get_conflicting_settings(ProviderType.AGY):
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="CONFIGURATION",
                    message=conflict,
                    provider="agy",
                )
            )

        # Check permission escalation
        for escalation in policy.detect_permission_escalation(ProviderType.AGY):
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message=escalation,
                    provider="agy",
                    action="Review permissions.providers.agy to ensure widening was intended.",
                )
            )

        # Comprehensive rule file budget check across all candidate rule files
        if not is_global:
            rule_candidates = [
                self.workspace / "GEMINI.md",
                self.workspace / "AGENTS.md",
            ]
            rules_dir = self.workspace / ".agents" / "rules"
            if rules_dir.is_dir():
                rule_candidates.extend(rules_dir.glob("*.md"))

            total_rule_bytes = 0
            for rf in rule_candidates:
                if rf.is_file():
                    size = rf.stat().st_size
                    total_rule_bytes += size
                    if size > AGY_MAX_RULE_BYTES:
                        items.append(
                            DiagnosticItem(
                                severity="ERROR",
                                category="COMPATIBILITY",
                                message=f"Rule file '{rf.name}' ({size} bytes) exceeds AGY 24 KB limit and will be truncated by CLI.",
                                provider="agy",
                                action="Reduce rule size below 24,000 bytes or convert to a skill.",
                            )
                        )

            if total_rule_bytes > AGY_MAX_AGGREGATE_RULE_BYTES:
                items.append(
                    DiagnosticItem(
                        severity="WARNING",
                        category="COMPATIBILITY",
                        message=f"Aggregate workspace rule size ({total_rule_bytes} bytes) likely exceeds AGY 20,000 token budget.",
                        provider="agy",
                        action="Demote secondary rules to on-demand skills.",
                    )
                )

            # Validate workspace skills and agents schema
            agents_root = self._get_workspace_agents_dir()
            skills_dir = agents_root / "skills"
            if skills_dir.is_dir():
                for skill_folder in skills_dir.iterdir():
                    if not skill_folder.is_dir():
                        continue
                    skill_md = skill_folder / "SKILL.md"
                    if skill_md.is_file():
                        text = safe_read_text(skill_md)
                        if text and text.startswith("---"):
                            parts = text.split("---", 2)
                            if len(parts) >= 3:
                                try:
                                    fm = yaml.safe_load(parts[1])
                                    if (
                                        not isinstance(fm, dict)
                                        or not fm.get("name")
                                        or not fm.get("description")
                                    ):
                                        items.append(
                                            DiagnosticItem(
                                                severity="ERROR",
                                                category="CONFIGURATION",
                                                message=f"AGY skill '{skill_folder.name}' SKILL.md frontmatter is missing required 'name' or 'description'.",
                                                provider="agy",
                                                action="Update SKILL.md frontmatter to include valid name and description.",
                                            )
                                        )
                                except Exception as err:
                                    items.append(
                                        DiagnosticItem(
                                            severity="ERROR",
                                            category="CONFIGURATION",
                                            message=f"AGY skill '{skill_folder.name}' SKILL.md frontmatter is invalid YAML: {err}",
                                            provider="agy",
                                            action="Correct YAML syntax in SKILL.md frontmatter.",
                                        )
                                    )

            custom_agents_dir = agents_root / "agents"
            if custom_agents_dir.is_dir():
                for agent_folder in custom_agents_dir.iterdir():
                    if not agent_folder.is_dir():
                        continue
                    agent_md = agent_folder / "agent.md"
                    if agent_md.is_file():
                        text = safe_read_text(agent_md)
                        if text and text.startswith("---"):
                            parts = text.split("---", 2)
                            if len(parts) >= 3:
                                try:
                                    fm = yaml.safe_load(parts[1])
                                    if (
                                        not isinstance(fm, dict)
                                        or not fm.get("name")
                                        or not fm.get("model")
                                    ):
                                        items.append(
                                            DiagnosticItem(
                                                severity="ERROR",
                                                category="CONFIGURATION",
                                                message=f"AGY custom agent '{agent_folder.name}' agent.md frontmatter is missing required 'name' or 'model'.",
                                                provider="agy",
                                                action="Update agent.md frontmatter to include valid name and model.",
                                            )
                                        )
                                except Exception as err:
                                    items.append(
                                        DiagnosticItem(
                                            severity="ERROR",
                                            category="CONFIGURATION",
                                            message=f"AGY custom agent '{agent_folder.name}' agent.md frontmatter is invalid YAML: {err}",
                                            provider="agy",
                                            action="Correct YAML syntax in agent.md frontmatter.",
                                        )
                                    )

        return items
