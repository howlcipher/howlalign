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

# Restore to an authorized cross-mount workspace
howlalign restore ~/.local/state/howlalign/backups/<backup_folder> --workspace /path/to/target/repo
```

### 6. Explain Effective Policy Matrix

Inspect the fully resolved effective configuration matrix per provider and role, including exact source attribution and permission settings:

```bash
# Print formatted effective matrix
howlalign explain

# Inspect a specific provider
howlalign explain --provider agy

# Output machine-readable JSON
howlalign explain --json
```

### 7. Diagnostics

Run configuration, rule budget, security diagnostics, and permission widening alerts:

```bash
howlalign doctor
howlalign doctor --scope all
```

---

## Provider-Specific Policy Engine (v0.1.5)

HowlAlign v0.1.5 enables fine-grained, independent control of reasoning effort and permission boundaries across providers without cross-provider coupling:

```toml
schema_version = "0.1.5"

[providers]
enabled = ["agy"]

[roles.planning]
claude_model = "claude-opus-5"
codex_model = "gpt-6.1-sol"
agy_model = "Gemini 3.8 Flash (High)"
effort = "high"

[roles.planning.provider_effort]
claude = "high"
codex = "high"
agy = "high"

[roles.implementation]
claude_model = "claude-sonnet-5"
codex_model = "gpt-6.1-sol"
agy_model = "Gemini 3.8 Flash (High)"
effort = "medium"

[roles.implementation.provider_effort]
claude = "medium"
codex = "low"
agy = "high"

[roles.support]
claude_model = "claude-haiku-4"
codex_model = "gpt-5.6-luna"
agy_model = "Gemini 3.8 Flash (High)"
effort = "low"

[roles.support.provider_effort]
claude = "low"
codex = "low"
agy = "high"

[permissions]
ask_approval = "on-request"
sandbox = "workspace-write"
allow_dangerous_bypass = false

[permissions.providers.agy]
ask_approval = "never"
sandbox = "danger-full-access"
allow_dangerous_bypass = true

[permissions.providers.codex]
ask_approval = "never"
sandbox = "danger-full-access"
allow_dangerous_bypass = true

[permissions.providers.claude]
ask_approval = "on-request"
sandbox = "workspace-write"
```

---

## Security Guarantees

HowlAlign operates under strict configuration safety rules:
- **Backup Integrity Verification:** Computes SHA-256 checksums before restore and matches against original pre-apply hashes; rejects corrupted or tampered backups fail-closed (`--force` never bypasses backup integrity).
- **Target Drift Detection:** Restore operations refuse to overwrite target files that have drifted or been deleted after apply unless `--force` is specified.
- **Cross-Mount Authorization:** Requires explicit `--workspace` / `-w` authorization to restore files outside the current working tree, preventing path-traversal attacks via malicious manifests.
- **Truthful Rollback Reporting:** Accurately reports rollback outcomes (`SUCCEEDED`, `PARTIAL`, `FAILED`) and tracks un-reverted files rather than claiming success unconditionally.
- **User Provenance Protection & Canonical Fingerprinting:** Tags managed files with cryptographic fingerprints (`# howlalign: fingerprint = ...` or YAML `fingerprint: ...`) computed via a unified whitespace-preserving canonical contract; detects indentation, blank line, and trailing space alterations. Provides safe, conservative migration for legacy v0.1.2 and v0.1.3 files, verifying hash and whitespace integrity before allowing updates and failing closed on ambiguity.
- **Fail-Closed Configuration & Policy Safety:** Halts with explicit domain exceptions (`ConfigurationParseError`, `PolicyValidationError`) rather than resetting or corrupting malformed configurations.
- **Dedicated Private Backups & XDG Precedence:** Backups are stored in user-private state locations following strict precedence (`$HOWLALIGN_BACKUP_DIR` -> `$XDG_STATE_HOME/howlalign/backups/` -> `~/.local/state/howlalign/backups/`) with restrictive permissions (`0o700` directories, `0o600` files), preventing accidental git commits and cross-user leaks.
- **Atomic Operations & Permission Preservation:** Writes target configurations through atomic temporary replacements, preserving file modes on existing configurations.
- **Secret Isolation & Masking:** Sensitive credentials, private keys, tokens, and authorization headers are masked in all diff previews and diagnostics without double-redaction or leaking prefixes.
- **Zero Unrelated Overwrite:** Preserves existing unrelated settings and tables in JSON and TOML configuration files.
- **No Silent Permission Bypasses:** Never enables `--dangerously-skip-permissions` or unrestricted sandbox bypasses without explicit user policy intent.
- **Hermetic Testing & Deployment Runbook:** Test suites run under hermetic fixtures isolating all environment variables and filesystem operations. Controlled evaluation on real developer machines is guided by [`docs/DEPLOYMENT_RUNBOOK.md`](docs/DEPLOYMENT_RUNBOOK.md).

---

## Howl Ecosystem

HowlAlign is standalone-first and does not require HowlPlane, HowlForge, or other Howl components to function. Within the broader ecosystem:
- **Howl:** System installation and lifecycle management.
- **HowlPlane:** Engineering orchestration, routing, verification, and workflow governance.
- **HowlForge:** Workforce roles and runtime selection contracts.
- **Howl Provider Core:** Controlled inference transport and execution metadata.
- **HowlAlign:** Native coding assistant configuration and policy alignment.

HowlAlign talks to no other component at run time. One file is shared: the
project-level `AGENTS.md` HowlAlign writes for Codex and Antigravity is also a
continuity file HowlRelay reads (`howlrelay status|handoff|brief`), so the
instructions HowlAlign renders there become part of the work state HowlRelay
reports. Keep project facts that HowlRelay should see in `HANDOFF.md` or
`PROJECT_STATE.md` rather than in the managed block of `AGENTS.md`.

---

## License

MIT License. Copyright (c) 2026 howlcipher.
