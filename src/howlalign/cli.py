"""CLI entry point for HowlAlign."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from howlalign import __version__
from howlalign.core.exceptions import (
    HowlAlignError,
)
from howlalign.core.models import Scope


def resolve_scope(is_global: bool, scope_opt: str | None) -> Scope:
    """Resolve scope between --global flag and --scope option."""
    if is_global:
        return Scope.GLOBAL
    if scope_opt:
        try:
            return Scope(scope_opt.lower())
        except ValueError:
            pass
    return Scope.PROJECT


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="howlalign")
def cli() -> None:
    """HowlAlign: Provider-agnostic AI coding assistant configuration and alignment.

    Aligns model preferences, specialized subagents, and workflow conventions
    across Claude Code, OpenAI Codex CLI, and Google Antigravity CLI (AGY).
    """
    pass


@cli.command("init")
@click.option(
    "--path",
    type=click.Path(dir_okay=True, file_okay=True, writable=True),
    default=None,
    help="Target path or directory for the policy file (defaults to ./howlalign.toml).",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Initialize global configuration in user configuration directory.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing policy file if present.",
)
def init_cmd(path: str | None, is_global: bool, force: bool) -> None:
    """Create a valid initial policy based on discovered providers."""
    from howlalign.core.policy import init_policy_file

    try:
        policy_path = init_policy_file(path=path, is_global=is_global, force=force)
        click.echo(f"Initialized HowlAlign policy at: {policy_path}")
    except FileExistsError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        click.echo("Use --force to overwrite an existing policy.")
        sys.exit(1)
    except HowlAlignError as err:
        click.secho(f"Configuration error: {err}", fg="red", err=True)
        sys.exit(1)
    except Exception as err:
        click.secho(f"Error initializing policy: {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("check")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Target user global configuration instead of project workspace.",
)
@click.option(
    "--scope",
    "scope_opt",
    type=click.Choice(["project", "global", "all"], case_sensitive=False),
    default=None,
    help="Explicitly specify target configuration scope.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output findings as JSON.",
)
def check_cmd(
    config_path: str | None, is_global: bool, scope_opt: str | None, json_output: bool
) -> None:
    """Read-only inspection of discovered providers, capabilities, and drift."""
    from howlalign.core.engine import AlignmentEngine

    target_scope = resolve_scope(is_global, scope_opt)
    try:
        engine = AlignmentEngine(config_path=config_path, scope=target_scope)
        exit_code = engine.check(json_output=json_output)
        sys.exit(exit_code)
    except HowlAlignError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("explain")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Target user global configuration instead of project workspace.",
)
@click.option(
    "--scope",
    "scope_opt",
    type=click.Choice(["project", "global", "all"], case_sensitive=False),
    default=None,
    help="Explicitly specify target configuration scope.",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "codex", "agy", "all"], case_sensitive=False),
    default="all",
    help="Filter inspection to a specific provider.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output effective policy details as JSON.",
)
def explain_cmd(
    config_path: str | None,
    is_global: bool,
    scope_opt: str | None,
    provider: str,
    json_output: bool,
) -> None:
    """Inspect and explain resolved effective models, reasoning effort, and permissions."""
    from howlalign.core.engine import AlignmentEngine

    target_scope = resolve_scope(is_global, scope_opt)
    try:
        engine = AlignmentEngine(config_path=config_path, scope=target_scope)
        exit_code = engine.explain(provider_filter=provider, json_output=json_output)
        sys.exit(exit_code)
    except HowlAlignError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("diff")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Target user global configuration instead of project workspace.",
)
@click.option(
    "--scope",
    "scope_opt",
    type=click.Choice(["project", "global", "all"], case_sensitive=False),
    default=None,
    help="Explicitly specify target configuration scope.",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "codex", "agy", "all"], case_sensitive=False),
    default="all",
    help="Filter diff to a specific provider.",
)
def diff_cmd(
    config_path: str | None, is_global: bool, scope_opt: str | None, provider: str
) -> None:
    """Calculate and display proposed unified diffs for native configurations."""
    from howlalign.core.engine import AlignmentEngine

    target_scope = resolve_scope(is_global, scope_opt)
    try:
        engine = AlignmentEngine(config_path=config_path, scope=target_scope)
        exit_code = engine.diff(provider_filter=provider)
        sys.exit(exit_code)
    except HowlAlignError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("apply")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Target user global configuration instead of project workspace.",
)
@click.option(
    "--scope",
    "scope_opt",
    type=click.Choice(["project", "global", "all"], case_sensitive=False),
    default=None,
    help="Explicitly specify target configuration scope.",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "codex", "agy", "all"], case_sensitive=False),
    default="all",
    help="Filter changes to a specific provider.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Non-interactive approval to apply changes.",
)
@click.option(
    "--no-backup",
    is_flag=True,
    default=False,
    help="Skip creating backup copies before applying changes (not recommended).",
)
def apply_cmd(
    config_path: str | None,
    is_global: bool,
    scope_opt: str | None,
    provider: str,
    yes: bool,
    no_backup: bool,
) -> None:
    """Apply explicitly approved configuration changes with backups and revalidation."""
    from howlalign.core.engine import AlignmentEngine

    target_scope = resolve_scope(is_global, scope_opt)
    try:
        engine = AlignmentEngine(config_path=config_path, scope=target_scope)
        exit_code = engine.apply(provider_filter=provider, auto_approve=yes, backup=not no_backup)
        sys.exit(exit_code)
    except HowlAlignError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("restore")
@click.argument("backup_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Force restore even if target files have drifted since apply.",
)
@click.option(
    "--workspace",
    "-w",
    "workspace_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Explicit trusted workspace directory for cross-mount restoration.",
)
def restore_cmd(backup_dir: str, force: bool, workspace_path: str | None) -> None:
    """Restore configuration files from a backup directory."""
    from howlalign.core.writer import ConfigWriter

    trusted_ws = Path(workspace_path) if workspace_path else None
    writer = ConfigWriter()
    res = writer.restore_backup(Path(backup_dir), force=force, trusted_workspace=trusted_ws)
    if res.success:
        click.secho(f"✓ Successfully restored configuration from {backup_dir}!", fg="green")
        for f in res.applied_files:
            click.echo(f"  - {f}")
        sys.exit(0)
    else:
        click.secho("✗ Failed to restore backup:", fg="red", err=True)
        for err in res.errors:
            click.secho(f"  - {err}", fg="red", err=True)
        sys.exit(1)


@cli.command("doctor")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--global",
    "is_global",
    is_flag=True,
    default=False,
    help="Target user global configuration instead of project workspace.",
)
@click.option(
    "--scope",
    "scope_opt",
    type=click.Choice(["project", "global", "all"], case_sensitive=False),
    default=None,
    help="Explicitly specify target configuration scope.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output diagnostics as JSON.",
)
def doctor_cmd(
    config_path: str | None,
    is_global: bool,
    scope_opt: str | None,
    json_output: bool,
) -> None:
    """Validate configuration health, security boundaries, and provider compatibility."""
    from howlalign.core.doctor import run_doctor

    target_scope = resolve_scope(is_global, scope_opt)
    try:
        exit_code = run_doctor(config_path=config_path, json_output=json_output, scope=target_scope)
        sys.exit(exit_code)
    except HowlAlignError as err:
        click.secho(f"Error: {err}", fg="red", err=True)
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main()
