# HowlAlign

**Provider-agnostic AI coding assistant configuration, model preferences, specialized agents, and workflow alignment.**

HowlAlign is an independent member of the Howl ecosystem designed to solve a ubiquitous multi-assistant developer problem:

> *"I use Claude Code, Codex, and AGY across many different software repositories. I want consistent planning, implementation, specialized agents, model preferences, and safe permission conventions without manually maintaining three independent configurations."*

HowlAlign allows developers to define an AI engineering workflow policy once (`howlalign.toml`) and safely translate that policy into native configurations for supported coding assistants.

---

## Supported Providers

1. **Claude Code** (Anthropic CLI)
2. **OpenAI Codex CLI**
3. **Google Antigravity CLI (AGY)**

---

## Key Capabilities

- **Provider Discovery:** Non-destructive detection of installed assistant CLIs, active versions, and configuration paths.
- **Shared Declarative Policy:** Unified policy specifying planning, implementation, and support roles, specialized subagents, and security policies.
- **Specialized Subagents:** Neutral role definitions (`search`, `tests`, `docs`) translated into native assistant subagents and skills.
- **Precedence Layers:** Global user defaults, repository/project conventions, and runtime execution flags.
- **Exact Configuration Diffs:** Unified diff previews before making any filesystem modifications.
- **Safe Application & Recovery:** Atomic writes, strict path validation, revalidation before writing, and timestamped backups with full rollback support.
- **Configuration Doctor:** Health checks, version mismatch warnings, drift detection, and credential-safe diagnostics.

---

## Quick Start

### Installation

```bash
pip install -e .
```

### 1. Initialize a Policy

Create a baseline `howlalign.toml` configuration:

```bash
howlalign init
```

### 2. Inspect Environment & Drift

Check discovered providers and current configuration alignment without modifying any files:

```bash
# Project workspace inspection
howlalign check

# Global user-level configuration inspection
howlalign check --scope global

# Aggregate inspection across all scopes
howlalign check --scope all
```

### 3. Preview Diffs

Inspect the exact unified diffs HowlAlign proposes applying to native provider configurations (sensitive credentials automatically masked):

```bash
howlalign diff
howlalign diff --scope global
```

### 4. Apply Changes Safely

Apply the configuration with automatic, isolated backups in `$XDG_STATE_HOME/howlalign/backups/`:

```bash
howlalign apply
```

To run non-interactively in automated pipelines:

```bash
howlalign apply --yes
```

### 5. Restore from Backup

Revert applied changes safely using a timestamped backup directory:

```bash
howlalign restore ~/.local/state/howlalign/backups/<backup_folder>

# Overwrite even if files have drifted after apply
howlalign restore ~/.local/state/howlalign/backups/<backup_folder> --force
```

### 6. Diagnostics

Run configuration, rule budget, and security diagnostics:

```bash
howlalign doctor
howlalign doctor --scope all
```

---

## Security Guarantees

HowlAlign operates under strict configuration safety rules:
- **User Provenance Protection:** Automatically tags and preserves user-authored subagents and rules lacking HowlAlign provenance markers.
- **Fail-Closed Parsing:** Halts with explicit `ConfigurationParseError` rather than resetting or corrupting malformed configurations.
- **Dedicated Private Backups:** Backups are stored in user-private XDG state locations with restrictive permissions (`0o700` directories, `0o600` files), preventing accidental git commits.
- **Target Drift Detection:** Restore operations refuse to overwrite target files that have drifted after apply unless `--force` is specified.
- **Atomic Operations & Permission Preservation:** Writes target configurations through atomic temporary replacements, preserving file modes on existing configurations.
- **Secret Isolation & Masking:** Sensitive credentials, tokens, and authorization headers are masked in all diff previews and diagnostics.
- **Zero Unrelated Overwrite:** Preserves existing unrelated settings and tables in JSON and TOML configuration files.
- **No Silent Permission Bypasses:** Never enables `--dangerously-skip-permissions` or unrestricted sandbox bypasses without explicit user policy intent.
- **Isolated Testing:** Integration and unit tests run in hermetic, disposable fixture directories.

---

## Howl Ecosystem

HowlAlign is standalone-first and does not require HowlPlane, HowlForge, or other Howl components to function. Within the broader ecosystem:
- **Howl:** System installation and lifecycle management.
- **HowlPlane:** Engineering orchestration, routing, verification, and workflow governance.
- **HowlForge:** Workforce roles and runtime selection contracts.
- **Howl Provider Core:** Controlled inference transport and execution metadata.
- **HowlAlign:** Native coding assistant configuration and policy alignment.

---

## License

MIT License. Copyright (c) 2026 howlcipher.
