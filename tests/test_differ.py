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
