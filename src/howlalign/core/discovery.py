"""Provider discovery, version detection, and capability resolution."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from howlalign.core.models import ProviderInfo, ProviderType


def run_version_command(binary_path: str, args: list[str]) -> str | None:
    """Safely execute a version command with timeout."""
    try:
        proc = subprocess.run(
            [binary_path, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = proc.stdout.strip() or proc.stderr.strip()
        return output if proc.returncode == 0 else None
    except Exception:
        return None


def extract_version_semver(text: str | None) -> str | None:
    """Extract semantic version string from command output."""
    if not text:
        return None
    match = re.search(r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)*)", text)
    return match.group(1) if match else text.split()[0] if text else None


def discover_agy_models(binary_path: str = "agy") -> list[str]:
    """Discover available AGY model identifiers via 'agy models'."""
    try:
        proc = subprocess.run(
            [binary_path, "models"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return []
        models: list[str] = []
        for line in proc.stdout.splitlines():
            clean_line = re.sub(r"^[^\w\s]*", "", line).strip()
            parts = clean_line.split()
            if (
                parts
                and re.match(r"^[a-zA-Z0-9.-]+$", parts[0])
                and not parts[0].startswith("Fetching")
            ):
                models.append(parts[0])
        return models
    except Exception:
        return []


class ProviderDiscovery:
    """Detects installed AI coding assistants and resolves capabilities."""

    def __init__(
        self,
        home_dir: Path | None = None,
        workspace_dir: Path | None = None,
    ) -> None:
        self.home = Path(home_dir) if home_dir else Path.home()
        self.workspace = Path(workspace_dir) if workspace_dir else Path.cwd()

    def discover_claude(self) -> ProviderInfo:
        """Inspect Claude Code CLI installation and paths."""
        exe = shutil.which("claude")
        version_str: str | None = None
        if exe:
            raw_ver = run_version_command(exe, ["--version"])
            version_str = extract_version_semver(raw_ver)

        global_cfg = self.home / ".claude" / "settings.json"
        project_cfg = self.workspace / ".claude" / "settings.json"

        capabilities = [
            "hierarchical_settings",
            "model_effort_levels",
            "opusplan_mode_routing",
            "custom_markdown_agents",
            "fine_grained_permissions",
            "claude_md_context",
            "headless_print_execution",
        ]
        unsupported = [
            "arbitrary_runtime_model_switching",
            "untrusted_repo_privilege_elevation",
        ]

        return ProviderInfo(
            provider=ProviderType.CLAUDE,
            installed=bool(exe),
            version=version_str,
            executable_path=exe,
            global_config_path=str(global_cfg) if global_cfg.is_file() else None,
            project_config_path=str(project_cfg) if project_cfg.is_file() else None,
            capabilities=capabilities,
            unsupported_features=unsupported,
        )

    def discover_codex(self) -> ProviderInfo:
        """Inspect OpenAI Codex CLI installation and paths."""
        exe = shutil.which("codex")
        version_str: str | None = None
        if exe:
            raw_ver = run_version_command(exe, ["--version"])
            version_str = extract_version_semver(raw_ver)

        codex_home = Path(os.environ.get("CODEX_HOME", str(self.home / ".codex")))
        global_cfg = codex_home / "config.toml"
        project_cfg = self.workspace / ".codex" / "config.toml"

        capabilities = [
            "toml_configuration",
            "six_tier_reasoning_effort",
            "native_custom_agent_roles",
            "agents_md_hierarchical_context",
            "bubblewrap_sandbox_modes",
            "guardian_auto_review",
            "headless_exec_streaming",
        ]
        unsupported = [
            "automatic_runtime_model_switching",
            "untrusted_project_config_execution",
        ]

        return ProviderInfo(
            provider=ProviderType.CODEX,
            installed=bool(exe),
            version=version_str,
            executable_path=exe,
            global_config_path=str(global_cfg) if global_cfg.is_file() else None,
            project_config_path=str(project_cfg) if project_cfg.is_file() else None,
            capabilities=capabilities,
            unsupported_features=unsupported,
        )

    def discover_agy(self) -> ProviderInfo:
        """Inspect Google Antigravity CLI (AGY) installation and paths."""
        exe = shutil.which("agy")
        version_str: str | None = None
        if exe:
            raw_ver = run_version_command(exe, ["--version"])
            version_str = extract_version_semver(raw_ver)

        global_cfg = self.home / ".gemini" / "antigravity-cli" / "settings.json"
        project_cfg = self.workspace / ".agents" / "skills.json"
        rules_cfg = self.workspace / "GEMINI.md"
        skills_dir = self.workspace / ".agents" / "skills"
        agents_dir = self.workspace / ".agents" / "agents"

        effective_project = None
        if project_cfg.is_file():
            effective_project = str(project_cfg)
        elif rules_cfg.is_file():
            effective_project = str(rules_cfg)
        elif skills_dir.is_dir():
            effective_project = str(skills_dir)
        elif agents_dir.is_dir():
            effective_project = str(agents_dir)

        capabilities = [
            "workspace_skills_runbooks",
            "workspace_markdown_rules",
            "custom_markdown_agents",
            "multi_tier_thinking_effort",
            "execution_modes_auto_plan",
            "proceed_in_sandbox_policy",
            "multi_agent_subagent_dispatch",
        ]
        unsupported = [
            "automatic_runtime_model_switching",
            "unquoted_rule_frontmatter_colons",
        ]

        return ProviderInfo(
            provider=ProviderType.AGY,
            installed=bool(exe),
            version=version_str,
            executable_path=exe,
            global_config_path=str(global_cfg) if global_cfg.is_file() else None,
            project_config_path=effective_project,
            capabilities=capabilities,
            unsupported_features=unsupported,
        )

    def discover_all(self) -> dict[ProviderType, ProviderInfo]:
        """Discover all supported assistant providers."""
        return {
            ProviderType.CLAUDE: self.discover_claude(),
            ProviderType.CODEX: self.discover_codex(),
            ProviderType.AGY: self.discover_agy(),
        }
