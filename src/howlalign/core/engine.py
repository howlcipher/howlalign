"""Main orchestration engine for HowlAlign."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping

import click

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.base import BaseAdapter
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.differ import Differ
from howlalign.core.discovery import ProviderDiscovery
from howlalign.core.models import (
    ApplyResult,
    ConfigChange,
    ProviderInfo,
    ProviderType,
    RecoveryState,
    Scope,
)
from howlalign.core.policy import discover_policy_file, get_default_policy, load_policy_file
from howlalign.core.writer import ConfigWriter


class AlignmentEngine:
    """Orchestrates discovery, adapter translation, diffing, and safe application."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
        scope: Scope = Scope.PROJECT,
        backup_root: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()
        self.scope = scope
        self.is_global = scope == Scope.GLOBAL
        self.env = env
        self.backup_root = backup_root

        # Locate policy
        resolved_policy_path = discover_policy_file(config_path)
        if resolved_policy_path:
            self.policy_path = resolved_policy_path
            self.policy = load_policy_file(resolved_policy_path)
        else:
            self.policy_path = None
            self.policy = get_default_policy()

        self.discovery = ProviderDiscovery(home_dir=self.home, workspace_dir=self.workspace)
        self.writer = ConfigWriter(
            workspace_dir=self.workspace,
            home_dir=self.home,
            backup_root=self.backup_root,
            env=self.env,
        )

        self.adapters: dict[ProviderType, BaseAdapter] = {
            ProviderType.CLAUDE: ClaudeAdapter(workspace_dir=self.workspace, home_dir=self.home),
            ProviderType.CODEX: CodexAdapter(workspace_dir=self.workspace, home_dir=self.home),
            ProviderType.AGY: AgyAdapter(workspace_dir=self.workspace, home_dir=self.home),
        }

    def get_providers_info(self) -> dict[ProviderType, ProviderInfo]:
        """Discover status of all providers."""
        return self.discovery.discover_all()

    def generate_all_changes(
        self,
        provider_filter: str = "all",
        is_global: bool | None = None,
    ) -> list[ConfigChange]:
        """Generate planned configuration changes across all enabled providers and scopes."""
        changes: list[ConfigChange] = []
        target_filter = provider_filter.lower()

        # If is_global not explicitly overridden, derive from scope
        target_global_flags: list[bool] = []
        if is_global is not None:
            target_global_flags = [is_global]
        elif self.scope == Scope.ALL:
            target_global_flags = [False, True]
        else:
            target_global_flags = [self.scope == Scope.GLOBAL]

        for flag in target_global_flags:
            for prov_type in self.policy.enabled_providers:
                if target_filter != "all" and prov_type.value != target_filter:
                    continue

                adapter = self.adapters.get(prov_type)
                if adapter:
                    changes.extend(adapter.generate_changes(self.policy, is_global=flag))

        return changes

    def check(self, json_output: bool = False) -> int:
        """Inspect providers, capabilities, and drift without modifications."""
        providers = self.get_providers_info()
        changes = self.generate_all_changes()

        drift_files = [
            c
            for c in changes
            if c.original_content != c.proposed_content and not c.is_user_owned_conflict
        ]
        conflict_files = [c for c in changes if c.is_user_owned_conflict]

        if json_output:
            data = {
                "policy_path": str(self.policy_path) if self.policy_path else None,
                "policy_schema_version": self.policy.schema_version,
                "scope": self.scope.value,
                "providers": {
                    p.value: {
                        "installed": info.installed,
                        "version": info.version,
                        "executable": info.executable_path,
                        "capabilities": info.capabilities,
                        "unsupported_features": info.unsupported_features,
                    }
                    for p, info in providers.items()
                },
                "drift_count": len(drift_files),
                "drift_files": [str(c.file_path) for c in drift_files],
                "conflict_count": len(conflict_files),
                "conflict_files": [str(c.file_path) for c in conflict_files],
            }
            click.echo(json.dumps(data, indent=2))
            return 0

        click.echo(f"=== HowlAlign Provider Inspection [Scope: {self.scope.value}] ===")
        if self.policy_path:
            click.echo(f"Active Policy: {self.policy_path} (schema v{self.policy.schema_version})")
        else:
            click.secho(
                "Active Policy: Using default in-memory policy (no howlalign.toml found).",
                fg="yellow",
            )

        click.echo("")
        for p, info in providers.items():
            status = (
                click.style("INSTALLED", fg="green")
                if info.installed
                else click.style("NOT FOUND", fg="yellow")
            )
            ver = f"v{info.version}" if info.version else "version unknown"
            click.echo(f"Provider: {p.value.upper():<8} [{status}] ({ver})")
            if info.installed:
                click.echo(f"  Executable: {info.executable_path}")
            if info.unsupported_features:
                click.echo(f"  Unsupported notes: {', '.join(info.unsupported_features)}")

        click.echo("")
        click.echo("=== Configuration Drift & Conflicts ===")
        if conflict_files:
            click.secho(
                f"Found {len(conflict_files)} user-authored file(s) preserved without modification:",
                fg="cyan",
            )
            for c in conflict_files:
                click.echo(f"  [PRESERVED] {c.file_path} ({c.provider.value})")

        if not drift_files:
            click.secho("✓ All enabled providers are fully aligned with policy.", fg="green")
        else:
            click.secho(f"Found {len(drift_files)} file(s) with configuration drift:", fg="yellow")
            for c in drift_files:
                action = "CREATE" if c.is_creation or c.original_content is None else "MODIFY"
                click.echo(f"  [{action}] {c.file_path} ({c.provider.value})")
            click.echo("\nRun 'howlalign diff' to inspect changes, or 'howlalign apply' to align.")

        return 0

    def diff(self, provider_filter: str = "all") -> int:
        """Calculate and display exact unified diffs."""
        changes = self.generate_all_changes(provider_filter=provider_filter)
        diff_res = Differ.compute_diff(changes, workspace_root=self.workspace)

        if not diff_res.unified_diff and not diff_res.has_conflicts:
            click.secho("No configuration changes needed. Configurations are aligned.", fg="green")
            return 0

        if diff_res.unified_diff:
            click.echo(f"=== Proposed Unified Diff [Scope: {self.scope.value}] ===")
            click.echo(diff_res.unified_diff)

        click.echo("\n=== Summary ===")
        click.echo(diff_res.summary)
        return 0

    def apply(
        self,
        provider_filter: str = "all",
        auto_approve: bool = False,
        backup: bool = True,
    ) -> int:
        """Apply approved changes with revalidation and backups."""
        changes = self.generate_all_changes(provider_filter=provider_filter)
        # Filter out user-owned conflicts and no-op changes
        actionable_changes = [
            c
            for c in changes
            if c.original_content != c.proposed_content and not c.is_user_owned_conflict
        ]

        if not actionable_changes:
            click.secho(
                "No changes needed. All provider configurations are already aligned.", fg="green"
            )
            return 0

        diff_res = Differ.compute_diff(actionable_changes, workspace_root=self.workspace)
        click.echo("=== Changes to Apply ===")
        click.echo(diff_res.summary)
        click.echo("")

        if not auto_approve:
            if not sys.stdin.isatty():
                click.secho(
                    "Error: Standard input is not a terminal and --yes was not provided. Aborting.",
                    fg="red",
                    err=True,
                )
                return 1

            confirm = click.confirm(
                "Do you want to apply these configuration changes?", default=False
            )
            if not confirm:
                click.echo("Operation cancelled by user.")
                return 0

        click.echo("Applying configuration changes...")
        result: ApplyResult = self.writer.apply(actionable_changes, create_backup=backup)

        if result.success:
            click.secho("✓ Successfully aligned configuration!", fg="green")
            if result.backup_dir:
                click.echo(f"Backup created at: {result.backup_dir}")
            click.echo("Modified files:")
            for f in result.applied_files:
                click.echo(f"  - {f}")
            return 0
        else:
            click.secho("✗ Failed to apply configuration changes!", fg="red", err=True)
            for err in result.errors:
                click.secho(f"  Error: {err}", fg="red", err=True)
            if result.recovery_state == RecoveryState.SUCCEEDED:
                click.secho(
                    "  [ROLLBACK] All partially applied files were reverted successfully.",
                    fg="yellow",
                )
            elif result.recovery_state == RecoveryState.PARTIAL:
                click.secho(
                    f"  [ROLLBACK WARNING] Partial rollback! The following files could not be reverted: {result.remaining_modified_files}",
                    fg="red",
                    err=True,
                )
            elif result.recovery_state == RecoveryState.FAILED:
                click.secho(
                    f"  [ROLLBACK FAILED] Rollback could not revert files: {result.remaining_modified_files}. "
                    f"Manual recovery required from backup directory: {result.backup_dir}",
                    fg="red",
                    err=True,
                )
            elif result.rolled_back:
                click.secho(
                    "  [ROLLBACK] All partially applied files were reverted successfully.",
                    fg="yellow",
                )
            return 1
