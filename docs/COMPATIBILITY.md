# Provider Compatibility Matrix

This document provides a comprehensive capability classification, evaluated versions, runtime validation status, and known behavioral constraints for AI coding assistant providers supported by HowlAlign v0.1.5.

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
| Independent role effort (`provider_effort`) | **Schema / Doc Verified** | Maps planning, implementation, and support roles independently to `"modelSettings.<model>.effortLevel"` (`low`, `medium`, `high`, `xhigh`). |
| Dynamic mode routing (`opusplan`) | **Schema / Doc Verified** | Uses Opus during Plan Mode and Sonnet during Implementation Mode. |
| Provider-specific permissions (`permissions.providers.claude`) | **Schema / Doc Verified** | Controls `"defaultMode"` (`acceptEdits` when `never`, else `default`) and granular tool permissions. |
| Specialized Subagents (`.claude/agents/*.md`) | **Runtime Verified** | Markdown agent format with YAML frontmatter specifying `name`, `description`, `tools`, and `permissionMode`. |
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
| Implementation reasoning effort (`model_reasoning_effort`) | **Runtime Verified** | Resolved independently from `roles.implementation.provider_effort.codex`. Values: `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. |
| Plan mode reasoning effort (`plan_mode_reasoning_effort`) | **Runtime Verified** | Resolved independently from `roles.planning.provider_effort.codex` in `config.toml`. |
| Agent role files (`.codex/agents/*.toml`) | **Runtime Verified** | Subagents resolve their own model and effort independently from support role or specific agent overrides. |
| Provider-specific permissions (`permissions.providers.codex`) | **Runtime Verified** | Maps `ask_approval` directly to `approval_policy` (`never`, `on-request`, `always`) and `sandbox` to `sandbox_mode` (`danger-full-access`, `workspace-write`, `read-only`). |
| Project Trust Boundary (`[projects."<path>"]`) | **Runtime Verified** | Project `.codex/config.toml` is ignored unless explicitly trusted in global config (`trust_level = "trusted"`). |
| Linux Sandbox mode (`sandbox_mode = "workspace-write"`) | **Runtime Verified** | Uses Bubblewrap & Landlock isolation. |
| Top-level comments provenance (`# managed_by = "howlalign"`) | **Runtime Verified** | Comment-based tagging preserved without corrupting TOML deserializer. |
| TOML comment preservation caveat | **Documented Constraint** | Standard python `toml` parser preserves all semantic data keys and tables (`[projects]`, `[features]`) but discards inline human comments on serialization. Doctor inspects existing `config.toml` for comments and emits an informational diagnostic prior to apply. |
| Global `default_subagent_model` in `config.toml` | **Unsupported** | Codex CLI deserializer rejects this in `config.toml` under `--strict-config`. Subagent models are configured per agent role TOML. |
| Global `default_subagent_reasoning_effort` in `config.toml` | **Unsupported** | Codex CLI deserializer rejects this in `config.toml` under `--strict-config`. Subagent effort is configured per agent role TOML. |
| Data table `managed_by = "howlalign"` in role TOMLs | **Unsupported** | Causes deserializer failure (`unknown field managed_by`). Formatted as header comment. |

---

## 3. Google Antigravity CLI (AGY)

- **Target Evaluated Version:** `1.3.6` / `1.4.0`
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
| Model selection (`Gemini 3.8 Flash (High)`, `claude-*`) | **Runtime Verified** | Preserves exact model strings across planning, implementation, and support roles. |
| Independent effort levels (`settings.json` `"effort"`) | **Runtime Verified** | Resolved independently from `roles.implementation.provider_effort.agy` (`low`, `medium`, `high`, `xhigh`, `max`). |
| Provider-specific permissions (`permissions.providers.agy`) | **Runtime Verified** | Maps `ask_approval = "never"` to `toolPermission = "always-proceed"`, `on-request` to `request-review`, and `sandbox = "workspace-write"` to `proceed-in-sandbox`. Configures `allowNonWorkspaceAccess = true` on `danger-full-access`. |
| Progressive skills (`.agents/skills/<name>/SKILL.md`) | **Runtime Verified** | YAML frontmatter (`name`, `description`) + markdown instructions. Validated via `check_health()`. |
| Custom subagents (`.agents/agents/<name>/agent.md`) | **Runtime Verified** | YAML frontmatter (`subagent: true`, `model`, `tools`) + instructions. Validated via `check_health()`. |
| Rule file size cap (24 KB per file) | **Runtime Verified** | Files over 24,000 bytes are truncated by AGY CLI; enforced by `howlalign doctor`. |
| Aggregate rules token budget (20,000 tokens) | **Schema / Doc Verified** | Excess rules demoted to file references. |
| Fabricated `planningModel` in `settings.json` | **Unsupported** | Not recognized by AGY schema. Flagged by `howlalign doctor` and omitted. |

---

## 4. Summary of Hardening & Architectural Guarantees in v0.1.5

1. **Independent Reasoning Effort per Provider & Role**:
   HowlAlign v0.1.5 resolves reasoning effort independently for each provider and role via `[roles.<role>.provider_effort]`. Changing Codex implementation effort to `low` does not alter Claude's or AGY's effort levels.
2. **Independent Security & Autonomy Boundaries**:
   `[permissions.providers.<provider>]` allows granular, provider-scoped autonomy (e.g. `approval_policy = "never"` and `sandbox_mode = "danger-full-access"` on Codex for unrestricted local development) while preserving conservative defaults on other providers.
3. **Permission Escalation Safeguards**:
   `Differ` scans proposed configurations and injects high-visibility `[SECURITY ALERT]` notices if an edit widens permissions or removes sandbox constraints. `Doctor` warns when dangerous bypasses are configured.
4. **Transparent Inspection (`howlalign explain`)**:
   Operators can audit the fully resolved effective configuration matrix and source attribution for every setting before applying changes.
5. **Codex TOML Comment Awareness**:
   Doctor detects human comments in `~/.codex/config.toml` and emits informational notices explaining serialization behavior.

