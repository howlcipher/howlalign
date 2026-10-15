"""Unified diff calculation and change set analysis."""

from __future__ import annotations

import difflib
from pathlib import Path

from howlalign.core.models import ConfigChange, DiffResult


def generate_unified_diff(
    original_text: str | None,
    proposed_text: str,
    file_path: Path,
) -> str:
    """Generate exact unified diff between original and proposed content."""
    old_lines = original_text.splitlines(keepends=True) if original_text is not None else []
    new_lines = proposed_text.splitlines(keepends=True)

    fromfile = f"a/{file_path.name}" if original_text is not None else "/dev/null"
    tofile = f"b/{file_path.name}"

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=fromfile,
        tofile=tofile,
    )
    return "".join(diff)


class Differ:
    """Computes unified diffs and drift summaries across proposed changes."""

    @staticmethod
    def compute_diff(changes: list[ConfigChange]) -> DiffResult:
        """Compute unified diffs for a list of configuration changes."""
        diff_chunks: list[str] = []
        summary_lines: list[str] = []

        changed_count = 0
        created_count = 0

        for change in changes:
            # Check if there is actual difference
            if change.original_content == change.proposed_content:
                continue

            changed_count += 1
            if change.is_creation or change.original_content is None:
                created_count += 1
                summary_lines.append(f"CREATE: {change.file_path} ({change.description})")
            else:
                summary_lines.append(f"MODIFY: {change.file_path} ({change.description})")

            chunk = generate_unified_diff(
                original_text=change.original_content,
                proposed_text=change.proposed_content,
                file_path=change.file_path,
            )
            if chunk:
                diff_chunks.append(f"# File: {change.file_path} [{change.provider.value}]\n{chunk}")

        summary = f"{changed_count} file(s) to align ({created_count} new, {changed_count - created_count} modified)."
        if summary_lines:
            summary = summary + "\n" + "\n".join(f"  - {line}" for line in summary_lines)

        return DiffResult(
            changes=changes,
            unified_diff="\n\n".join(diff_chunks),
            summary=summary,
        )
