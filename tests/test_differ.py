"""Tests for diff calculation and change set analysis."""

from pathlib import Path

from howlalign.core.differ import Differ, generate_unified_diff
from howlalign.core.models import ConfigChange, ProviderType


def test_generate_unified_diff(tmp_path: Path):
    target = tmp_path / "sample.txt"
    diff = generate_unified_diff(
        original_text="line1\nline2\n",
        proposed_text="line1\nline2_modified\nline3\n",
        file_path=target,
    )
    assert "-line2" in diff
    assert "+line2_modified" in diff
    assert "+line3" in diff


def test_differ_summary_and_empty(tmp_path: Path):
    target1 = tmp_path / "file1.txt"
    target2 = tmp_path / "file2.txt"

    changes = [
        ConfigChange(
            file_path=target1,
            original_content="same\n",
            proposed_content="same\n",
            description="No change",
            provider=ProviderType.CLAUDE,
        ),
        ConfigChange(
            file_path=target2,
            original_content=None,
            proposed_content="new content\n",
            description="New file",
            provider=ProviderType.CODEX,
            is_creation=True,
        ),
    ]

    res = Differ.compute_diff(changes)
    assert "1 file(s) to align (1 new, 0 modified)" in res.summary
    assert "CREATE" in res.summary
    assert "+new content" in res.unified_diff


def test_differ_masks_secrets_in_diff(tmp_path: Path):
    target = tmp_path / "secret_config.toml"
    raw_secret = "sk-live-secret-super-confidential-token-12345"

    changes = [
        ConfigChange(
            file_path=target,
            original_content=f'api_key = "{raw_secret}"\n',
            proposed_content='api_key = "sk-live-updated-token-99999"\n',
            description="Update secret token",
            provider=ProviderType.CODEX,
        )
    ]

    res = Differ.compute_diff(changes, mask_secrets=True)
    assert raw_secret not in res.unified_diff
    assert "sk-live-updated-token-99999" not in res.unified_diff
    assert "SECURITY NOTICE" in res.unified_diff
    assert "****" in res.unified_diff


def test_differ_conflict_detection_notice(tmp_path: Path):
    target = tmp_path / "custom_agent.md"
    changes = [
        ConfigChange(
            file_path=target,
            original_content="# User Custom Agent\n",
            proposed_content="# User Custom Agent\n",
            description="User-authored custom agent preserved.",
            provider=ProviderType.CLAUDE,
            is_user_owned_conflict=True,
        )
    ]

    res = Differ.compute_diff(changes)
    assert res.has_conflicts is True
    assert "User-authored agent files detected and protected from overwrite" in res.summary
