# Provider Compatibility Matrix

This document summarizes native capability translations, evaluated versions, and known runtime limitations for supported coding assistants.

---

## 1. Claude Code (Anthropic CLI)

- **Target Evaluated Version:** `2.1.300`
- **Configuration Files:**
  - Global: `~/.claude/settings.json`
  - Project: `.claude/settings.json`
  - Guidelines: `CLAUDE.md`, `.claude/rules/*.md`
  - Subagents: `.claude/agents/<name>.md`
- **Supported Capabilities:**
  - Model selection via `"model"` alias (`opusplan`, `opus`, `sonnet`, `haiku`) or canonical ID.
  - Thinking effort levels via `"modelSettings.<model>.effortLevel"` (`low`, `medium`, `high`, `xhigh`).
  - Native custom subagents in Markdown with YAML frontmatter specifying allowed/disallowed tools and permission modes.
  - Dynamic mode routing via `opusplan` (Opus in Plan mode, Sonnet in Implementation mode).
  - Fine-grained permission rules (`allow`, `deny`, `ask`).
- **Unsupported / Restricted Behaviors:**
  - `bypassPermissionsMode` cannot be enabled from repository-resident settings files (blocked by Claude Code security boundary).
  - Automatic dynamic model switching outside `opusplan` is not supported without runtime CLI flags.
  - Noninteractive sessions (`-p`) silently drop interactive permission prompts unless `--permission-mode acceptEdits` or `--permission-prompts none` is explicitly provided.

---

## 2. OpenAI Codex CLI

- **Target Evaluated Version:** `0.162.1`
- **Configuration Files:**
  - Global: `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`)
  - Project: `.codex/config.toml`
  - Guidelines: `AGENTS.md` (root and hierarchical subdirectories)
  - Subagents: `[agents.<name>]` pointing to `.codex/agents/<name>.toml`
- **Supported Capabilities:**
  - Model selection via `model = "<model_slug>"` (`gpt-6.1-sol`, `gpt-6-astra`, `gpt-5.6-luna`, `o3`).
  - Six-tier reasoning effort: `model_reasoning_effort` (`low`, `medium`, `high`, `xhigh`, `max`, `ultra`).
  - Plan mode reasoning: `plan_mode_reasoning_effort`.
  - Subagent default models: `default_subagent_model`, `default_subagent_reasoning_effort`.
  - Sandbox modes: `sandbox_mode = "workspace-write"` (backed by Bubblewrap and Landlock on Linux).
  - Automated approvals reviewer: `approval_policy = "never"`, `approvals_reviewer = "auto_review"`.
  - Hierarchical `AGENTS.md` spec preloaded into developer context.
- **Unsupported / Restricted Behaviors:**
  - Project `.codex/config.toml` is **ignored** unless the repository path is marked as trusted in user config (`[projects."<abs_path>"] trust_level = "trusted"`). HowlAlign doctor checks and reports this requirement.
  - Automatic runtime model switching without subagents is not supported.
  - `ultra` reasoning effort is rejected by models that only support up to `max`.

---

## 3. Google Antigravity CLI (AGY)

- **Target Evaluated Version:** `1.3.6`
- **Configuration Files:**
  - Global: `~/.gemini/antigravity-cli/settings.json`, `~/.gemini/config/config.json`
  - Workspace Guidelines: `GEMINI.md`, `AGENTS.md`, `.agents/rules/*.md`
  - Workspace Skills: `.agents/skills/<name>/SKILL.md`
  - Workspace Agents: `.agents/agents/<name>/agent.md`
- **Supported Capabilities:**
  - Model selection: `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`.
  - Thinking effort levels via `--effort <low|medium|high|xhigh|max>`.
  - Execution modes: `accept-edits`, `auto` (with safety reviewer agent), `plan`.
  - Progressive skills (`SKILL.md` with YAML frontmatter + scripts/references).
  - Custom markdown agents (`agent.md` with YAML frontmatter `subagent: true`, `model`).
  - Tool permission modes: `proceed-in-sandbox`, `always-proceed`, `request-review`.
- **Unsupported / Restricted Behaviors:**
  - Rule files have a hard **24 KB (24,000 bytes)** cap per file. Files exceeding this are truncated by the CLI. HowlAlign doctor validates rule file sizes.
  - Aggregate rules budget is **20,000 tokens**. Over-budget rules are demoted to on-demand file pointers.
  - Automatic runtime model switching requires multi-agent delegation or CLI `--model` specification.
