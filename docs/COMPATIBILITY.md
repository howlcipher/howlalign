# Provider Compatibility Matrix

This document provides a comprehensive capability classification, evaluated versions, runtime validation status, and known behavioral constraints for AI coding assistant providers supported by HowlAlign v0.1.4.

---

## Evaluation Standard & Status Classifications

Each native capability is classified under one of four rigorous standards:
- **Runtime Verified**: Verified against the actual installed provider CLI executable (`claude`, `codex`, `agy`) in an isolated, disposable environment.
- **Schema / Documentation Verified**: Verified against official provider documentation, CLI help menus, or local schema definitions where read-only CLI commands are available.
- **Not Verified**: Plausible capability based on provider ecosystem patterns, but unverified due to lack of local schema or read-only CLI flags.
- **Unsupported**: Explicitly rejected by the provider CLI (e.g. unknown TOML fields, CLI configuration deserializer errors, or forbidden security bypasses), and removed or guarded by HowlAlign.

---

## 1. Claude Code (Anthropic CLI)

- **Target Evaluated Version:** `2.1.301`
- **Installed Status:** Installed (`/home/howlcipher/.local/bin/claude`)
- **Validation Command:** `claude doctor`, `claude --help`
- **Configuration Locations:**
  - Global: `~/.claude/settings.json`
  - Project: `.claude/settings.json`
  - Guidelines: `CLAUDE.md`, `.claude/rules/*.md`
  - Specialized Subagents: `.claude/agents/<name>.md`

### Capability Classification

| Capability | Status | Notes |
| :--- | :--- | :--- |
| Model selection (`opusplan`, canonical IDs) | **Runtime Verified** | Validated via `settings.json` `"model"` property and CLI execution. |
| Thinking effort levels (`effortLevel`) | **Schema / Doc Verified** | Set via `"modelSettings.<model>.effortLevel"` (`low`, `medium`, `high`, `xhigh`). |
| Specialized Subagents (`.claude/agents/*.md`) | **Runtime Verified** | Markdown agent format with YAML frontmatter specifying `name`, `description`, `tools`, and `permissionMode`. |
| Dynamic mode routing (`opusplan`) | **Schema / Doc Verified** | Uses Opus during Plan Mode and Sonnet during Implementation Mode. |
| Granular permissions (`allow`, `deny`, `ask`) | **Schema / Doc Verified** | Specified under `"permissions"` key in `settings.json`. |
| Project-level `CLAUDE.md` guidelines | **Runtime Verified** | Automatically loaded into context during session startup. |
| `bypassPermissionsMode` in repository config | **Unsupported** | Blocked by Claude Code security boundary. Repository-level config cannot bypass permissions. |
| Interactive prompts in noninteractive mode (`-p`) | **Unsupported** | Silently fails unless `--permission-mode acceptEdits` or `--permission-prompts none` is supplied. |

---

## 2. OpenAI Codex CLI

- **Target Evaluated Version:** `0.162.1`
- **Installed Status:** Installed (`/home/howlcipher/.local/bin/codex`)
- **Validation Command:** `codex --strict-config doctor`, `codex --help`
- **Configuration Locations:**
  - Global: `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`)
  - Project: `.codex/config.toml`
  - Guidelines: `AGENTS.md` (root and directory hierarchy)
  - Specialized Subagents: `[agents.<name>]` pointing to `.codex/agents/<name>.toml`

### Capability Classification

| Capability | Status | Notes |
| :--- | :--- | :--- |
| Model selection (`gpt-6.1-sol`, `gpt-6-astra`, `o3`) | **Runtime Verified** | Validated via `config.toml` `model = "..."`. |
| Six-tier reasoning effort (`model_reasoning_effort`) | **Runtime Verified** | Values: `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. |
| Plan mode reasoning effort (`plan_mode_reasoning_effort`) | **Runtime Verified** | Configured in `config.toml`. |
| Agent role files (`.codex/agents/*.toml`) | **Runtime Verified** | Roles define `description`, `developer_instructions`, `model`, and `model_reasoning_effort`. |
| Project Trust Boundary (`[projects."<path>"]`) | **Runtime Verified** | Project `.codex/config.toml` is ignored unless explicitly trusted in global config (`trust_level = "trusted"`). |
| Linux Sandbox mode (`sandbox_mode = "workspace-write"`) | **Runtime Verified** | Uses Bubblewrap & Landlock isolation. |
| Top-level comments provenance (`# managed_by = "howlalign"`) | **Runtime Verified** | Comment-based tagging preserved without corrupting TOML deserializer. |
| Global `default_subagent_model` in `config.toml` | **Unsupported** | Codex CLI deserializer rejects this in `config.toml` under `--strict-config`. Removed in v0.1.3; subagent models are configured per agent role TOML. |
| Global `default_subagent_reasoning_effort` in `config.toml` | **Unsupported** | Codex CLI deserializer rejects this in `config.toml` under `--strict-config`. Removed in v0.1.3; subagent effort is configured per agent role TOML. |
| Data table `managed_by = "howlalign"` in role TOMLs | **Unsupported** | Causes deserializer failure (`unknown field managed_by`). Removed from table data and stored as header comment in v0.1.3. |

---

## 3. Google Antigravity CLI (AGY)

- **Target Evaluated Version:** `1.3.6`
- **Installed Status:** Installed (`/home/howlcipher/.local/bin/agy`)
- **Validation Command:** `agy models`, `agy doctor`, `agy --help`
- **Configuration Locations:**
  - Global: `~/.gemini/antigravity-cli/settings.json`, `~/.gemini/config/config.json`
  - Workspace Guidelines: `GEMINI.md`, `AGENTS.md`, `.agents/rules/*.md`
  - Workspace Skills: `.agents/skills/<name>/SKILL.md`
  - Workspace Agents: `.agents/agents/<name>/agent.md`

### Capability Classification

| Capability | Status | Notes |
| :--- | :--- | :--- |
| Model discovery (`agy models`) | **Runtime Verified** | Discovers active models directly from CLI registry (`discover_agy_models()`). |
| Model selection (`gemini-3.8-flash-*`, `claude-*`) | **Runtime Verified** | Verified active model registry via `agy models`. |
| Thinking effort levels (`effort` / `--effort`) | **Runtime Verified** | Validated via `settings.json` (`low`, `medium`, `high`, `xhigh`, `max`). |
| Progressive skills (`.agents/skills/<name>/SKILL.md`) | **Runtime Verified** | YAML frontmatter (`name`, `description`) + markdown instructions. Validated via `check_health()`. |
| Custom subagents (`.agents/agents/<name>/agent.md`) | **Runtime Verified** | YAML frontmatter (`subagent: true`, `model`, `tools`) + instructions. Validated via `check_health()`. |
| Workspace directory discovery | **Runtime Verified** | Discovers `.agents/skills` and `.agents/agents` in workspace root. |
| Execution modes (`accept-edits`, `auto`, `plan`) | **Schema / Doc Verified** | Supported via runtime CLI flags and settings. |
| Rule file size cap (24 KB per file) | **Runtime Verified** | Files over 24,000 bytes are truncated by AGY CLI; enforced by `howlalign doctor`. |
| Aggregate rules token budget (20,000 tokens) | **Schema / Doc Verified** | Excess rules demoted to file references. |
| Fabricated `planningModel` in `settings.json` | **Unsupported** | Not recognized by AGY schema. Flagged by `howlalign doctor` and removed. |

---

## Summary of Unsupported Setting Removals & Hardening in v0.1.3 & v0.1.4

1. **Codex CLI `default_subagent_*` keys in `config.toml`**:
   Removed from `src/howlalign/adapters/codex.py`. Codex CLI 0.162.1 config parser emits strict configuration warnings for `default_subagent_model` and `default_subagent_reasoning_effort`. Subagent models and reasoning efforts are set within each specific `.codex/agents/<name>.toml`.
2. **Codex CLI `managed_by` key in agent role TOML data tables**:
   Codex deserializes agent role files directly into an internal Rust struct with `deny_unknown_fields`. Emitting `managed_by = "howlalign"` inside the TOML data table caused Codex to log `Ignoring malformed agent role definition: failed to deserialize agent role file ... unknown field managed_by`. HowlAlign formats provenance and fingerprint metadata as top-level comments (`# managed_by = "howlalign"`, `# howlalign: fingerprint = ...`).
3. **AGY `planningModel` in `settings.json`**:
   AGY only parses `"model"` and `"effort"` from `settings.json`.
4. **AGY Model Discovery and Frontmatter Validation in v0.1.4**:
   `howlalign.core.discovery.discover_agy_models()` actively queries the live AGY model registry. `AgyAdapter.check_health()` validates frontmatter structure and mandatory fields (`name`, `description`, `model`) for all workspace skills and agents.
5. **Whitespace Preservation in Managed-File Provenance in v0.1.4**:
   `compute_managed_fingerprint()` hashes exact canonical document bytes (excluding self-referential header tags), preventing invisible whitespace or indentation alterations. Legacy files are migrated with strict whitespace anomaly checks.
