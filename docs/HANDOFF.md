# HowlAlign Session Handoff & Mission Tracker

## Mission Objective
Build, harden, verify, and maintain **HowlAlign**, an open-source, provider-agnostic AI coding assistant configuration and alignment tool. HowlAlign translates unified engineering workflow policies into native configurations across:
1. Claude Code (Anthropic CLI)
2. OpenAI Codex CLI
3. Google Antigravity CLI (AGY)

---

## Milestone Status: v0.1.1 Security Hardened & Verified
- **Repository**: `https://github.com/howlcipher/howlalign`
- **Local Path**: `/run/media/system/tallgeese/dev/howlalign`
- **Current Branch**: `main`
- **Version**: `0.1.1` (bumped in `pyproject.toml` and `src/howlalign/__init__.py`)
- **Verification Status**: 37/37 unit and integration tests passing; ruff format and lint clean.
- **Critical Isolation**: Zero real user AI assistant configurations (`~/.claude`, `~/.codex`, `~/.gemini`) modified. All tests run in isolated `tmp_path` disposable environments.

---

## v0.1.1 Hardening & Architecture Deliverables

1. **Dedicated User-Private Backups & Restrictive Permissions**:
   - Backups moved out of source repositories into `$XDG_STATE_HOME/howlalign/backups/<workspace_hash>/<timestamp>/` (defaulting to `~/.local/state/howlalign/backups/`).
   - Backup directories created with `0o700` (user-only read/write/traverse).
   - Backup files and `manifest.json` written with `0o600` (user-only read/write).
   - Accidental Git commits of configuration backups are completely eliminated.

2. **Restore Safety & Drift Conflict Detection**:
   - Manifest pre-validation verifies entry schema, file existence, and strict confinement within the backup directory (preventing path traversal).
   - Target drift detection computes current file SHA-256 against post-apply state. If drifted, restore refuses to overwrite unless `--force` is explicitly provided.
   - Reverts file creations safely without arbitrary unlinking.

3. **User Provenance & Custom Agent Preservation**:
   - Files lacking `managed_by: howlalign` (Markdown) or `managed_by = "howlalign"` (TOML) are recognized as user-authored.
   - Identified as `is_user_owned_conflict = True` and preserved untouched across Claude, Codex, and AGY adapters.
   - Differ and Doctor emit prominent warnings when user-authored files are protected.

4. **Fail-Closed Configuration Safety**:
   - Existing assistant configuration parsing (JSON / TOML) fails closed: raises domain-specific `ConfigurationParseError` rather than resetting data to `{}` or clobbering user configurations.

5. **Secret Masking in Diffs & Output**:
   - Differ unified diff generator masks sensitive credentials, API keys, tokens, and authorization headers (`sk-...`, Bearer tokens, passwords).
   - Doctor diagnostics scan and mask credentials before emitting output.

6. **Provider Adapter Hardening & Specialization**:
   - **Claude**: Dynamically resolves fast model (`claude-haiku-4`) for support roles (`search`, `docs`) instead of hardcoding `inherit`. Conservative permission mapping (`ON_REQUEST` -> `"default"`).
   - **Codex**: Uses portable relative paths (`.codex/agents/<name>.toml`) in project configs. Generates `sandbox_mode = "read-only"` for read-only agents.
   - **AGY**: Comprehensive rule file size budget checking across `GEMINI.md`, `AGENTS.md`, and `.agents/rules/*.md` against the 24 KB per-file ceiling.

7. **Unified Scope Management**:
   - Added `--global` and `--scope [project|global|all]` flags consistently across `check`, `diff`, `apply`, and `doctor`.
   - Engine and Doctor support multi-scope aggregation.

8. **Domain Exception Hierarchy (`howlalign.core.exceptions`)**:
   - `HowlAlignError`, `ConfigurationError`, `PolicyNotFoundError`, `PolicyValidationError`, `PolicySyntaxError`, `ConfigurationParseError`, `SafetyViolationError`, `PathTraversalError`, `UnsafeSymlinkError`, `RestoreConflictError`, `AtomicWriteError`, `ConcurrentModificationError`.

---

## Test & Quality Verification Results
- **Pytest**: `37 passed in 2.14s` across 7 test modules.
- **Ruff Lint**: `ruff check .` -> `All checks passed!`
- **Ruff Format**: `ruff format --check .` -> `27 files already formatted`

---

## Next Steps
- Commit verified v0.1.1 milestone to local `main` branch.
- Push to GitHub remote (`origin/main`).
- Verify CI run on GitHub Actions.
- Present engineering mission report.
