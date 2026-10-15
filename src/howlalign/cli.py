"""CLI entry point for HowlAlign."""

from __future__ import annotations

import sys

import click

from howlalign import __version__


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="howlalign")
def cli() -> None:
    """HowlAlign: Provider-agnostic AI coding assistant configuration and alignment.

    Aligns model preferences, specialized subagents, and workflow conventions
    across Claude Code, OpenAI Codex CLI, and Google Antigravity CLI (AGY).
    """


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
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output findings as JSON.",
)
def check_cmd(config_path: str | None, json_output: bool) -> None:
    """Read-only inspection of discovered providers, capabilities, and drift."""
    from howlalign.core.engine import AlignmentEngine

    engine = AlignmentEngine(config_path=config_path)
    exit_code = engine.check(json_output=json_output)
    sys.exit(exit_code)


@cli.command("diff")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "codex", "agy", "all"], case_sensitive=False),
    default="all",
    help="Filter diff to a specific provider.",
)
def diff_cmd(config_path: str | None, provider: str) -> None:
    """Calculate and display proposed unified diffs for native configurations."""
    from howlalign.core.engine import AlignmentEngine

    engine = AlignmentEngine(config_path=config_path)
    exit_code = engine.diff(provider_filter=provider)
    sys.exit(exit_code)


@cli.command("apply")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to howlalign.toml policy.",
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
def apply_cmd(config_path: str | None, provider: str, yes: bool, no_backup: bool) -> None:
    """Apply explicitly approved configuration changes with backups and revalidation."""
    from howlalign.core.engine import AlignmentEngine

    engine = AlignmentEngine(config_path=config_path)
    exit_code = engine.apply(provider_filter=provider, auto_approve=yes, backup=not no_backup)
    sys.exit(exit_code)


@cli.command("restore")
@click.argument("backup_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
def restore_cmd(backup_dir: str) -> None:
    """Restore configuration files from a backup directory."""
    from pathlib import Path

    from howlalign.core.writer import ConfigWriter

    writer = ConfigWriter()
    res = writer.restore_backup(Path(backup_dir))
    if res.success:
        click.secho(f"✓ Successfully restored configuration from {backup_dir}!", fg="green")
        for f in res.applied_files:
            click.echo(f"  - {f}")
        sys.exit(0)
    else:
        click.secho(f"✗ Failed to restore backup: {res.errors}", fg="red", err=True)
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
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output diagnostics as JSON.",
)
def doctor_cmd(config_path: str | None, json_output: bool) -> None:
    """Validate configuration health, security boundaries, and provider compatibility."""
    from howlalign.core.doctor import run_doctor

    exit_code = run_doctor(config_path=config_path, json_output=json_output)
    sys.exit(exit_code)


def main() -> None:
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main()
