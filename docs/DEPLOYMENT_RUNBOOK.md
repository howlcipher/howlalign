# HowlAlign v0.1.5 Operator Deployment Runbook

## Controlled Read-Only Evaluation on Host Environment (Bazzite / Linux)

This runbook guides operators through an authorized, controlled evaluation of HowlAlign v0.1.5 against real installed coding assistants (**Claude Code**, **OpenAI Codex CLI**, and **Google Antigravity CLI / AGY**).

> [!IMPORTANT]
> **Safety Guarantee**: Steps 1 through 8 are **strictly read-only**. They do NOT modify `~/.claude`, `~/.codex`, `~/.gemini`, or `~/.config/howlalign`. Do NOT run `howlalign apply` on real user configurations without explicit authorization and manual pre-adoption backups.

---

## 1. Install HowlAlign in an Isolated Virtual Environment

Install HowlAlign in a clean, dedicated Python virtual environment to avoid interfering with system packages:

```bash
# Navigate to the repository workspace
cd /path/to/howlalign

# Create and activate an isolated virtual environment (Python 3.11+)
python3 -m venv .venv-eval
source .venv-eval/bin/activate

# Install HowlAlign in editable mode
pip install -e .

# Confirm installed version
howlalign --version
# Expected: howlalign, version 0.1.5
```

---

## 2. Check Installed Assistant Providers

Discover detected CLI executables, active versions, and default configuration paths:

```bash
howlalign check --scope all
```

**What to verify in output**:
- **Claude Code**: Shows detected executable (`claude`), evaluated version (e.g. `2.1.301`), and paths (`~/.claude/settings.json`).
- **OpenAI Codex CLI**: Shows detected executable (`codex`), evaluated version (e.g. `0.162.1`), and paths (`~/.codex/config.toml`).
- **Google Antigravity CLI (AGY)**: Shows detected executable (`agy`), evaluated version (e.g. `1.3.6` / `1.4.0`), and global paths (`~/.gemini/antigravity-cli/settings.json`).

---

## 3. Initialize or Review Global Policy

Inspect or initialize the declarative policy without touching provider settings:

```bash
# Review an existing global policy (if configured)
cat ~/.config/howlalign/howlalign.toml 2>/dev/null || echo "No global policy created yet."

# Dry-run review default policy structure in project workspace
howlalign init --help
```

> [!NOTE]
> HowlAlign respects the policy discovery order: `--config <path>` $\rightarrow$ `./howlalign.toml` $\rightarrow$ `./.howlalign.toml` $\rightarrow$ `~/.config/howlalign/howlalign.toml` $\rightarrow$ internal defaults.

---

## 4. Inspect Effective Policy Matrix (`howlalign explain`)

Audit the fully resolved configuration matrix per provider and role, confirming independent reasoning effort and permission resolution:

```bash
# Print formatted effective matrix
howlalign explain --scope all

# Inspect a specific provider
howlalign explain --provider agy

# Output machine-readable JSON for automated verification
howlalign explain --json
```

**What to verify in output**:
- Check that each role displays independent models and effort levels per provider.
- Verify source attribution (e.g. `roles.implementation.provider_effort.codex` vs fallback `roles.implementation.effort`).
- Confirm provider-specific approval and sandbox settings (`ask_approval`, `sandbox`, `allow_dangerous_bypass`).

---

## 5. Inspect Current Configuration Drift

Check for configuration differences between the desired policy and the actual state on disk across all scopes:

```bash
# Inspect global user-level configuration drift (read-only)
howlalign check --scope global

# Inspect project repository drift (read-only)
howlalign check --scope project

# Inspect combined aggregate drift
howlalign check --scope all
```

- If files on disk match the policy, `0 drift` is reported.
- If differences exist, HowlAlign lists candidate files that would be updated upon application.

---

## 6. Preview Exact Unified Diffs & Security Alerts

Examine the exact unified diffs HowlAlign proposes applying. Sensitive tokens, API keys, and authorization headers are automatically masked:

```bash
# Preview global configuration diffs
howlalign diff --scope global

# Preview project repository diffs
howlalign diff --scope project
```

**What to review in diff previews**:
- **Permission Widening Alerts**: If proposed changes weaken security boundaries (e.g. `approval_policy = "never"`, `toolPermission = "always-proceed"`, `sandbox_mode = "danger-full-access"`), verify the `[SECURITY ALERT]` header is prominently displayed.
- Confirm that existing custom tables in `config.toml` or unrelated keys in `settings.json` are preserved.
- Verify model identifiers (`opusplan`, `gpt-6.1-sol`, `Gemini 3.8 Flash (High)`).
- Confirm thinking effort levels per provider.
- Notice that secret tokens appear as `****[REDACTED]****`.

---

## 7. Identify Conflicting Custom Agents

HowlAlign detects and protects user-authored custom agents from accidental overwrite:

```bash
# Run diagnostics to discover conflicting or user-modified agents
howlalign doctor --scope all
```

**Conflict Detection Rules**:
1. **User-authored files** (lacking `# managed_by = "howlalign"` or YAML frontmatter `managed_by: howlalign`) are detected as conflicts and are **NEVER overwritten**.
2. **User-modified managed files** (where stored cryptographic fingerprint diverges from current file content) are preserved as conflicts and require manual review.
3. **Untouched managed files** (matching canonical v0.1.4/v0.1.5 fingerprint or verified legacy baseline) are safely updateable.

---

## 8. Examine Permission Changes & Diagnostics

Run security, sandbox mode, and rule budget health checks:

```bash
howlalign doctor --scope global
```

**Key health checks evaluated**:
- **Effective Provider Permissions**: Reports effective approval, sandbox, and dangerous bypass authorization per enabled provider.
- **Permission Escalation Warnings**: Warns if dangerous execution modes are active without explicit policy authorization.
- **Codex TOML Comments Notice**: Alerts operator if `~/.codex/config.toml` contains human comments that will not be preserved upon rewrite.
- **Codex CLI Project Trust**: Verifies if workspace path is registered as trusted in `~/.codex/config.toml` (`[projects."<path>"] trust_level = "trusted"`).
- **AGY Rule Size Cap**: Verifies rule files (`GEMINI.md`, `AGENTS.md`) do not exceed the 24,000 bytes (24 KB) hard limit.
- **Leaked Secrets**: Scans target files for unredacted authorization headers, API tokens, or private keys.
- **Obsolete Settings**: Identifies legacy keys (such as `planningModel` or invalid subagent keys) and advises on remediation.

---

## 9. Create a Manual Snapshot Before Adoption

Before authorizing any real configuration changes, create an independent manual snapshot of your active assistant configurations:

```bash
# Create an operator manual snapshot directory
SNAPSHOT_DIR=~/howlalign_pre_adoption_snapshot_$(date +%Y%m%d_%H%M%S)
mkdir -p "$SNAPSHOT_DIR"

# Snapshot real configuration directories (if they exist)
[ -d ~/.claude ] && cp -r ~/.claude "$SNAPSHOT_DIR/claude_backup"
[ -d ~/.codex ] && cp -r ~/.codex "$SNAPSHOT_DIR/codex_backup"
[ -d ~/.gemini ] && cp -r ~/.gemini "$SNAPSHOT_DIR/gemini_backup"

echo "Manual snapshot successfully created at: $SNAPSHOT_DIR"
```

---

## 10. Apply Configuration (One Provider at a Time)

When explicitly authorized, apply changes selectively and review backups:

```bash
# 1. Preview changes one final time
howlalign diff --scope global

# 2. Apply interactively (prompts before making filesystem changes)
howlalign apply --scope global

# Note: HowlAlign automatically creates an isolated backup in:
# $XDG_STATE_HOME/howlalign/backups/<workspace_key>/<timestamp>/
```

---

## 11. Safe Restore from Backup

If unexpected behavior occurs, revert immediately using HowlAlign's built-in restore engine:

```bash
# List available backups
ls -la ~/.local/state/howlalign/backups/

# Restore from a timestamped backup directory
howlalign restore ~/.local/state/howlalign/backups/<workspace_key>/<timestamp>/


# If target files drifted after apply, force restore with explicit authorization:
howlalign restore ~/.local/state/howlalign/backups/<workspace_key>/<timestamp>/ --force
```

**Integrity Verification Guarantees**:
- Backups verify SHA-256 integrity before restoring (`--force` never bypasses backup corruption checks).
- Reverted files are verified against pre-apply checksums.
