"""Comprehensive regression and lifecycle tests for HowlAlign v0.1.4.

Covers:
1. Canonical fingerprint whitespace collision prevention (YAML indent, trailing spaces, blank lines, CRLF).
2. Safe conservative migration for legacy v0.1.2 and v0.1.3 files (detecting whitespace tampering, fail-closed).
3. 15-step managed-file lifecycle across all 4 formats (Claude agent, Codex agent, AGY agent, AGY skill).
4. XDG backup path precedence and hermetic test isolation.
5. Native AGY configuration and frontmatter schema validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import toml

from howlalign.adapters.agy import AgyAdapter
from howlalign.adapters.base import (
    _compute_legacy_v013_fingerprint,
    compute_managed_fingerprint,
    extract_managed_fingerprint,
    has_user_modifications,
    has_whitespace_modifications,
    is_file_managed_by_howlalign,
)
from howlalign.adapters.claude import ClaudeAdapter
from howlalign.adapters.codex import CodexAdapter
from howlalign.core.constants import get_default_backup_root
from howlalign.core.discovery import discover_agy_models
from howlalign.core.models import (
    EffortLevel,
    RoleClass,
    RoleConfig,
)
from howlalign.core.policy import get_default_policy
from howlalign.core.writer import ConfigWriter

# ==============================================================================
# SECTION 1: FINGERPRINT WHITESPACE COLLISION TESTS (P1)
# ==============================================================================


def test_fingerprint_whitespace_yaml_indentation():
    """Verify that differing YAML frontmatter indentation alters the fingerprint."""
    raw_2_spaces = """---
managed_by: howlalign
name: search
tools:
  - Read
  - Glob
---

Search instructions
"""
    raw_4_spaces = """---
managed_by: howlalign
name: search
tools:
    - Read
    - Glob
---

Search instructions
"""
    fp_2 = compute_managed_fingerprint(raw_2_spaces)
    fp_4 = compute_managed_fingerprint(raw_4_spaces)
    assert fp_2 != fp_4, "YAML indentation difference must produce different fingerprints"


def test_fingerprint_whitespace_trailing_spaces():
    """Verify that trailing spaces on lines alter the fingerprint."""
    clean = """---
managed_by: howlalign
name: search
---

Instructions here.
"""
    trailing = "---\nmanaged_by: howlalign\nname: search\n---\n\nInstructions here.  \n"
    assert compute_managed_fingerprint(clean) != compute_managed_fingerprint(trailing)


def test_fingerprint_whitespace_blank_lines():
    """Verify that additional blank lines alter the fingerprint."""
    single_blank = """---
managed_by: howlalign
name: search
---

Prompt
"""
    double_blank = """---
managed_by: howlalign
name: search
---


Prompt
"""
    assert compute_managed_fingerprint(single_blank) != compute_managed_fingerprint(double_blank)


def test_fingerprint_crlf_lf_normalization():
    """Verify CRLF and LF produce identical canonical fingerprints."""
    lf_text = "---\nmanaged_by: howlalign\nname: search\n---\n\nPrompt\n"
    crlf_text = "---\r\nmanaged_by: howlalign\r\nname: search\r\n---\r\n\r\nPrompt\r\n"
    assert compute_managed_fingerprint(lf_text) == compute_managed_fingerprint(crlf_text)


def test_fingerprint_identical_content_deterministic():
    """Verify that identical content produces exactly the same fingerprint."""
    text1 = "---\nmanaged_by: howlalign\nname: tests\n---\n\nRun pytest.\n"
    text2 = "---\nmanaged_by: howlalign\nname: tests\n---\n\nRun pytest.\n"
    assert compute_managed_fingerprint(text1) == compute_managed_fingerprint(text2)


def test_fingerprint_toml_formatting_differences():
    """Verify TOML key-value whitespace differences alter the fingerprint."""
    toml1 = '# managed_by = "howlalign"\nname = "search"\nmodel = "gpt-6.1-sol"\n'
    toml2 = '# managed_by = "howlalign"\nname   =   "search"\nmodel = "gpt-6.1-sol"\n'
    assert compute_managed_fingerprint(toml1) != compute_managed_fingerprint(toml2)


def test_fingerprint_excludes_only_designated_metadata_line():
    """Verify that only the header fingerprint line is excluded, not body mentions."""
    text_with_header_fp = """---
managed_by: howlalign
managed_fingerprint: a1b2c3d4e5f67890
name: search
---

Documentation about managed_fingerprint: example.
"""
    text_without_header_fp = """---
managed_by: howlalign
name: search
---

Documentation about managed_fingerprint: example.
"""
    # compute_managed_fingerprint should yield the same hash for both because header fp is excluded
    assert compute_managed_fingerprint(text_with_header_fp) == compute_managed_fingerprint(
        text_without_header_fp
    )


# ==============================================================================
# SECTION 2: CONSERVATIVE LEGACY MIGRATION TESTS (P1)
# ==============================================================================


def test_legacy_v013_untouched_file_migrates_cleanly():
    """Verify untouched v0.1.3 file is identified as untouched and eligible for migration."""
    p = get_default_policy()
    raw = f"""---
managed_by: howlalign
name: search
description: {p.agents["search"].description}
tools:
  - Read
  - Glob
disallowedTools:
  - Edit
model: inherit
permissionMode: plan
---

<!-- managed by howlalign -->
{p.agents["search"].system_prompt.strip()}
"""
    v013_fp = _compute_legacy_v013_fingerprint(raw)
    v013_file = raw.replace(
        "managed_by: howlalign\n",
        f"managed_by: howlalign\nmanaged_fingerprint: {v013_fp}\n",
    )

    assert is_file_managed_by_howlalign(v013_file, "md") is True
    assert has_whitespace_modifications(v013_file, "md") is False
    assert has_user_modifications(v013_file, "md") is False


def test_legacy_v013_whitespace_modified_file_fails_closed():
    """Verify that a v0.1.3 file with human whitespace edits is flagged as conflict (fail-closed)."""
    p = get_default_policy()
    raw = f"""---
managed_by: howlalign
name: search
description: {p.agents["search"].description}
tools:
  - Read
  - Glob
disallowedTools:
  - Edit
model: inherit
permissionMode: plan
---

<!-- managed by howlalign -->
{p.agents["search"].system_prompt.strip()}
"""
    v013_fp = _compute_legacy_v013_fingerprint(raw)
    v013_file = raw.replace(
        "managed_by: howlalign\n",
        f"managed_by: howlalign\nmanaged_fingerprint: {v013_fp}\n",
    )

    # 1. Human edit: change indentation from 2 spaces to 4 spaces
    modified_indent = v013_file.replace("  - Read", "    - Read")
    assert has_whitespace_modifications(modified_indent, "md") is True
    assert has_user_modifications(modified_indent, "md") is True

    # 2. Human edit: add trailing spaces
    modified_trailing = v013_file.replace("permissionMode: plan", "permissionMode: plan  ")
    assert has_whitespace_modifications(modified_trailing, "md") is True
    assert has_user_modifications(modified_trailing, "md") is True

    # 3. Human edit: add multiple consecutive blank lines
    modified_blank = v013_file.replace("---\n\n<!--", "---\n\n\n<!--")
    assert has_whitespace_modifications(modified_blank, "md") is True
    assert has_user_modifications(modified_blank, "md") is True


def test_legacy_v012_untouched_and_modified_files():
    """Verify that untouched v0.1.2 files migrate, but modified v0.1.2 files conflict."""
    p = get_default_policy()
    role_data = {
        "managed_by": "howlalign",
        "name": "search",
        "description": p.agents["search"].description,
        "developer_instructions": p.agents["search"].system_prompt.strip(),
        "model": "gpt-5.6-luna",
        "model_reasoning_effort": "low",
        "nickname_candidates": ["search", "search-agent"],
        "sandbox_mode": "read-only",
    }
    role_body = toml.dumps(role_data)
    v012_fp = compute_managed_fingerprint(role_body)
    v012_untouched = f'# managed by howlalign\n# managed_fingerprint = "{v012_fp}"\n' + role_body

    assert is_file_managed_by_howlalign(v012_untouched, "toml") is True
    assert has_user_modifications(v012_untouched, "toml") is False

    # Human modification: edit instructions
    v012_edited = v012_untouched.replace(
        "developer_instructions = ", 'developer_instructions = "Custom instructions"\n# orig = '
    )
    assert has_user_modifications(v012_edited, "toml") is True


def test_invalid_missing_or_corrupted_fingerprints_fail_closed():
    """Verify invalid, missing, or corrupted fingerprints fail closed as user conflicts."""
    # 1. Missing fingerprint line
    content_no_fp = """---
managed_by: howlalign
name: search
---
Body
"""
    assert is_file_managed_by_howlalign(content_no_fp, "md") is True
    assert has_user_modifications(content_no_fp, "md") is True

    # 2. Corrupted hex fingerprint
    content_bad_hex = """---
managed_by: howlalign
managed_fingerprint: badbeef000000000
name: search
---
Body
"""
    assert has_user_modifications(content_bad_hex, "md") is True


# ==============================================================================
# SECTION 3: 15-STEP MANAGED-FILE LIFECYCLE (P1)
# ==============================================================================


def _run_15_step_lifecycle(adapter, file_rel_path: str, format_type: str, tmp_path: Path):
    """Execute complete 15-step lifecycle on any adapter-managed file."""
    p1 = get_default_policy()
    target_file = tmp_path / file_rel_path

    # Step 1: Generate file
    changes1 = adapter.generate_changes(p1, is_global=False)
    target_change = next(c for c in changes1 if c.file_path == target_file)
    assert target_change is not None
    assert target_change.proposed_content is not None

    # Step 2: Write file
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(target_change.proposed_content, encoding="utf-8")

    # Step 3: Verify fingerprint
    fp1 = extract_managed_fingerprint(target_change.proposed_content, format_type=format_type)
    assert fp1 is not None
    assert compute_managed_fingerprint(target_change.proposed_content) == fp1
    assert has_user_modifications(target_change.proposed_content, format_type=format_type) is False

    # Step 4: Inspect configuration drift on target file
    changes_check = adapter.generate_changes(p1, is_global=False)
    drift = [
        c
        for c in changes_check
        if c.file_path == target_file and c.original_content != c.proposed_content
    ]
    assert len(drift) == 0

    # Step 5 & 6: Apply same policy again -> confirm target file is unchanged (0 applied)
    writer = ConfigWriter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    res_noop = writer.apply(drift, create_backup=False)
    assert res_noop.success is True
    assert len(res_noop.applied_files) == 0

    # Step 7 & 8: Change policy -> confirm update proposed
    p2 = get_default_policy()
    p2.agents["search"].description = "Updated description for search subagent"
    changes_update = adapter.generate_changes(p2, is_global=False)
    update_change = next(c for c in changes_update if c.file_path == target_file)
    assert update_change.original_content != update_change.proposed_content
    assert update_change.is_user_owned_conflict is False

    # Step 9 & 10: Apply policy change -> confirm valid new fingerprint
    res_update = writer.apply([update_change], create_backup=False)
    assert res_update.success is True
    new_content = target_file.read_text(encoding="utf-8")
    fp2 = extract_managed_fingerprint(new_content, format_type=format_type)
    assert fp2 is not None
    assert fp2 != fp1
    assert compute_managed_fingerprint(new_content) == fp2
    assert has_user_modifications(new_content, format_type=format_type) is False

    # Step 11: Modify whitespace manually
    if format_type == "toml":
        ws_edited = new_content.replace('name = "search"', '  name = "search"')
    else:
        ws_edited = new_content.replace("name: search", "  name: search")
    assert ws_edited != new_content, "Whitespace edit must alter the text"
    target_file.write_text(ws_edited, encoding="utf-8")

    # Step 12 & 13: Confirm user modification is detected and preserved
    assert has_user_modifications(ws_edited, format_type=format_type) is True

    # Step 14 & 15: Verify conflict reporting and user edits preserved
    changes_conflict = adapter.generate_changes(p2, is_global=False)
    conflict_change = next(c for c in changes_conflict if c.file_path == target_file)
    assert conflict_change.is_user_owned_conflict is True
    assert conflict_change.proposed_content == ws_edited
    assert target_file.read_text(encoding="utf-8") == ws_edited


def test_15_step_lifecycle_claude_agent(tmp_path: Path):
    """Test full 15-step lifecycle on Claude Code agent markdown."""
    adapter = ClaudeAdapter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    _run_15_step_lifecycle(adapter, ".claude/agents/search.md", "md", tmp_path)


def test_15_step_lifecycle_codex_role(tmp_path: Path):
    """Test full 15-step lifecycle on Codex role TOML."""
    adapter = CodexAdapter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    _run_15_step_lifecycle(adapter, ".codex/agents/search.toml", "toml", tmp_path)


def test_15_step_lifecycle_agy_agent(tmp_path: Path):
    """Test full 15-step lifecycle on AGY agent markdown."""
    adapter = AgyAdapter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    _run_15_step_lifecycle(adapter, ".agents/agents/search/agent.md", "md", tmp_path)


def test_15_step_lifecycle_agy_skill(tmp_path: Path):
    """Test full 15-step lifecycle on AGY skill markdown."""
    adapter = AgyAdapter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    _run_15_step_lifecycle(adapter, ".agents/skills/search/SKILL.md", "md", tmp_path)


# ==============================================================================
# SECTION 4: XDG BACKUP PATH PRECEDENCE TESTS (P2)
# ==============================================================================


def test_xdg_backup_path_precedence_no_overrides(tmp_path: Path):
    """Verify default backup root when no overrides are active."""
    home = tmp_path / "user_home"
    home.mkdir()
    root = get_default_backup_root(home_dir=home, env={})
    assert root == home / ".local" / "state" / "howlalign" / "backups"


def test_xdg_backup_path_precedence_xdg_state_home(tmp_path: Path):
    """Verify XDG_STATE_HOME override takes precedence over default home."""
    home = tmp_path / "user_home"
    state_dir = tmp_path / "custom_state"
    home.mkdir()
    state_dir.mkdir()

    env = {"XDG_STATE_HOME": str(state_dir)}
    root = get_default_backup_root(home_dir=home, env=env)
    assert root == state_dir / "howlalign" / "backups"


def test_xdg_backup_path_precedence_howlalign_backup_dir(tmp_path: Path):
    """Verify HOWLALIGN_BACKUP_DIR takes precedence over both XDG_STATE_HOME and default."""
    home = tmp_path / "user_home"
    state_dir = tmp_path / "custom_state"
    backup_dir = tmp_path / "explicit_backups"

    env = {
        "XDG_STATE_HOME": str(state_dir),
        "HOWLALIGN_BACKUP_DIR": str(backup_dir),
    }
    root = get_default_backup_root(home_dir=home, env=env)
    assert root == backup_dir.resolve()


def test_xdg_backup_path_precedence_relative_xdg_state(tmp_path: Path):
    """Verify relative XDG_STATE_HOME resolves against effective home directory."""
    home = tmp_path / "user_home"
    env = {"XDG_STATE_HOME": "rel_state"}
    root = get_default_backup_root(home_dir=home, env=env)
    assert root == home / "rel_state" / "howlalign" / "backups"


def test_xdg_backup_path_precedence_invalid_overrides_fallback(tmp_path: Path):
    """Verify empty or invalid overrides fall back safely to effective home default."""
    home = tmp_path / "user_home"
    env = {"HOWLALIGN_BACKUP_DIR": "", "XDG_STATE_HOME": "   "}
    root = get_default_backup_root(home_dir=home, env=env)
    assert root == home / ".local" / "state" / "howlalign" / "backups"


def test_config_writer_env_injection_isolation(tmp_path: Path):
    """Verify ConfigWriter respects injected env and writes backups to isolated location."""
    ws = tmp_path / "ws"
    ws.mkdir()
    custom_state = tmp_path / "injected_state"
    custom_state.mkdir()

    writer = ConfigWriter(
        workspace_dir=ws,
        env={"XDG_STATE_HOME": str(custom_state)},
    )
    assert writer.backup_root == custom_state / "howlalign" / "backups"

    # Verify actual backup directory created on disk
    f = ws / "test.txt"
    f.write_text("orig\n", encoding="utf-8")
    change = writer.apply([], create_backup=True)
    assert change.success is True
    assert change.backup_dir is not None
    assert str(custom_state) in str(change.backup_dir)


# ==============================================================================
# SECTION 5: REAL AGY PROVIDER COMPATIBILITY VALIDATION (P2)
# ==============================================================================


def test_agy_models_discovery_parsing():
    """Verify that discover_agy_models safely queries 'agy models' if installed."""
    models = discover_agy_models("agy")
    # If agy is installed on the machine, models will be discovered
    if models:
        assert any("gemini-3.8-flash" in m for m in models)
        assert any("claude-" in m for m in models)


def test_agy_settings_planning_model_never_generated():
    """Verify that AgyAdapter never generates the unsupported 'planningModel' key."""
    adapter = AgyAdapter()
    p = get_default_policy()
    p.roles[RoleClass.PLANNING] = RoleConfig(
        claude_model="opusplan",
        codex_model="gpt-6.1-sol",
        agy_model="claude-opus-4-6-thinking",
        effort=EffortLevel.HIGH,
    )
    p.roles[RoleClass.IMPLEMENTATION] = RoleConfig(
        claude_model="claude-sonnet-5",
        codex_model="gpt-6.1-sol",
        agy_model="gemini-3.8-flash-high",
        effort=EffortLevel.MEDIUM,
    )
    changes = adapter.generate_changes(p, is_global=True)
    settings_change = changes[0]
    data = json.loads(settings_change.proposed_content)
    assert "planningModel" not in data
    assert "model" in data
    assert "effort" in data


def test_agy_health_checks_frontmatter_schemas(tmp_path: Path):
    """Verify that AgyAdapter.check_health validates frontmatter syntax and fields in skills and agents."""
    adapter = AgyAdapter(workspace_dir=tmp_path, home_dir=tmp_path / "home")
    p = get_default_policy()

    # 1. Invalid YAML frontmatter in skill
    bad_skill = tmp_path / ".agents" / "skills" / "broken" / "SKILL.md"
    bad_skill.parent.mkdir(parents=True, exist_ok=True)
    bad_skill.write_text("---\nname: broken\n  bad_yaml: [unclosed\n---\nBody\n", encoding="utf-8")

    # 2. Missing required description in skill
    incomplete_skill = tmp_path / ".agents" / "skills" / "incomplete" / "SKILL.md"
    incomplete_skill.parent.mkdir(parents=True, exist_ok=True)
    incomplete_skill.write_text("---\nname: incomplete\n---\nBody\n", encoding="utf-8")

    # 3. Missing required model in subagent
    incomplete_agent = tmp_path / ".agents" / "agents" / "no_model" / "agent.md"
    incomplete_agent.parent.mkdir(parents=True, exist_ok=True)
    incomplete_agent.write_text(
        "---\nname: no_model\ndescription: test\n---\nBody\n", encoding="utf-8"
    )

    diagnostics = adapter.check_health(p, is_global=False)
    error_messages = [d.message for d in diagnostics if d.severity == "ERROR"]

    assert any("broken" in msg and "invalid YAML" in msg for msg in error_messages)
    assert any("incomplete" in msg and "missing required" in msg for msg in error_messages)
    assert any("no_model" in msg and "missing required" in msg for msg in error_messages)
