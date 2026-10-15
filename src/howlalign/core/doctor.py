"""Doctor diagnostic and configuration health verification module."""

from __future__ import annotations

import json
from pathlib import Path

import click

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.base import BaseAdapter
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.differ import (
    SECRET_BEARER_PATTERN,
    SECRET_MULTILINE_PATTERN,
    SECRET_QUOTED_PATTERN,
    SECRET_STANDALONE_TOKEN_PATTERN,
    SECRET_UNQUOTED_PATTERN,
)
from howlalign.core.discovery import ProviderDiscovery
from howlalign.core.models import (
    DiagnosticItem,
    ProviderType,
    SandboxMode,
    Scope,
)
from howlalign.core.policy import discover_policy_file, get_default_policy, load_policy_file


def check_for_leaked_secrets(content: str) -> list[str]:
    """Scan text for suspected credential assignments, returning safe masked descriptions."""
    findings: list[str] = []
    if SECRET_MULTILINE_PATTERN.search(content):
        findings.append("Secret pattern matched: Private Key block [REDACTED]")
    for match in SECRET_QUOTED_PATTERN.finditer(content):
        key_name = match.group(1).split("=")[0].split(":")[0].strip().strip('"').strip("'")
        findings.append(f"Secret pattern matched with value for '{key_name}': ****[REDACTED]****")
    for match in SECRET_UNQUOTED_PATTERN.finditer(content):
        key_name = match.group(1).split("=")[0].split(":")[0].strip()
        findings.append(f"Secret pattern matched with value for '{key_name}': ****[REDACTED]****")
    for _ in SECRET_BEARER_PATTERN.finditer(content):
        findings.append("Secret pattern matched with value for Bearer token: ****[REDACTED]****")
    for _ in SECRET_STANDALONE_TOKEN_PATTERN.finditer(content):
        findings.append("Secret pattern matched: Standalone API token [REDACTED]")
    return findings


class Doctor:
    """Validates configuration health, security bounds, and provider compatibility."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
        scope: Scope = Scope.PROJECT,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()
        self.scope = scope
        self.is_global = scope == Scope.GLOBAL

        self.policy_path = discover_policy_file(config_path)
        if self.policy_path:
            try:
                self.policy = load_policy_file(self.policy_path)
                self.policy_error = None
            except Exception as err:
                self.policy = get_default_policy()
                self.policy_error = str(err)
        else:
            self.policy = get_default_policy()
            self.policy_error = None

        self.discovery = ProviderDiscovery(home_dir=self.home, workspace_dir=self.workspace)
        self.adapters: dict[ProviderType, BaseAdapter] = {
            ProviderType.CLAUDE: ClaudeAdapter(workspace_dir=self.workspace, home_dir=self.home),
            ProviderType.CODEX: CodexAdapter(workspace_dir=self.workspace, home_dir=self.home),
            ProviderType.AGY: AgyAdapter(workspace_dir=self.workspace, home_dir=self.home),
        }

    def run_diagnostics(self) -> list[DiagnosticItem]:
        """Perform comprehensive system diagnostics."""
        items: list[DiagnosticItem] = []

        # 1. Policy diagnostics
        if self.policy_error:
            items.append(
                DiagnosticItem(
                    severity="ERROR",
                    category="CONFIGURATION",
                    message=f"Failed to parse policy at {self.policy_path}: {self.policy_error}",
                    action="Check syntax in howlalign.toml.",
                )
            )
        elif not self.policy_path:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="CONFIGURATION",
                    message="No howlalign.toml policy found. Running with default in-memory policy.",
                    action="Run 'howlalign init' to create a repository policy file.",
                )
            )
        else:
            items.append(
                DiagnosticItem(
                    severity="INFO",
                    category="CONFIGURATION",
                    message=f"Policy loaded from {self.policy_path} (schema v{self.policy.schema_version}, scope: {self.scope.value}).",
                )
            )

        # 2. Security diagnostics
        if self.policy.permissions.allow_dangerous_bypass:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message="Dangerous permission bypass is enabled in policy ('allow_dangerous_bypass = true').",
                    action="Disable dangerous bypass for safe repository operations.",
                )
            )

        if self.policy.permissions.sandbox == SandboxMode.DANGER_FULL_ACCESS:
            items.append(
                DiagnosticItem(
                    severity="WARNING",
                    category="SECURITY",
                    message="Sandbox mode is set to 'danger-full-access'. File writes will not be restricted to workspace.",
                    action="Consider using 'workspace-write' sandbox.",
                )
            )

        # 3. Secret leaks scan in policy
        if self.policy_path and self.policy_path.is_file():
            policy_text = self.policy_path.read_text(encoding="utf-8")
            secrets = check_for_leaked_secrets(policy_text)
            for s in secrets:
                items.append(
                    DiagnosticItem(
                        severity="ERROR",
                        category="SECURITY",
                        message=f"Potential credential exposure in policy file: {s}",
                        action="Remove secret credentials from policy file immediately.",
                    )
                )

        # 4. Provider adapter diagnostics
        providers_info = self.discovery.discover_all()
        for prov_type in self.policy.enabled_providers:
            info = providers_info.get(prov_type)
            adapter = self.adapters.get(prov_type)
            if info and adapter:
                items.extend(adapter.check_health(self.policy, info, is_global=self.is_global))

        return items


def run_doctor(
    config_path: str | Path | None = None,
    json_output: bool = False,
    workspace_dir: Path | None = None,
    home_dir: Path | None = None,
    scope: Scope = Scope.PROJECT,
) -> int:
    """Execute doctor command and format output."""
    doctor = Doctor(
        config_path=config_path,
        workspace_dir=workspace_dir,
        home_dir=home_dir,
        scope=scope,
    )
    items = doctor.run_diagnostics()

    has_errors = any(i.severity == "ERROR" for i in items)

    if json_output:
        data = [
            {
                "severity": i.severity,
                "category": i.category,
                "message": i.message,
                "provider": i.provider,
                "action": i.action,
            }
            for i in items
        ]
        click.echo(json.dumps(data, indent=2))
        return 1 if has_errors else 0

    click.echo(f"=== HowlAlign Doctor Diagnostics [Scope: {scope.value}] ===\n")

    for item in items:
        if item.severity == "ERROR":
            tag = click.style("[ERROR]", fg="red", bold=True)
        elif item.severity == "WARNING":
            tag = click.style("[WARNING]", fg="yellow", bold=True)
        else:
            tag = click.style("[INFO]", fg="cyan")

        prov = f"[{item.provider}] " if item.provider else ""
        click.echo(f"{tag} {prov}{item.message}")
        if item.action:
            click.echo(f"       -> Action: {item.action}")

    click.echo("")
    if has_errors:
        click.secho("Doctor found critical errors that must be resolved.", fg="red", err=True)
        return 1
    else:
        click.secho("Doctor diagnostics completed. No critical issues detected.", fg="green")
        return 0
