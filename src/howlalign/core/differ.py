"""Unified diff calculation, secret redaction, and change set analysis."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from howlalign.core.models import ConfigChange, DiffResult

# Patterns to match sensitive key-value pairs for display masking
SECRET_VALUE_PATTERNS = [
    re.compile(
        r'((?:api[_-]?key|access[_-]?token|secret[_-]?key|auth[_-]?token|password)\s*[:=]\s*["\'])([^"\']{4,})(["\'])',
        re.IGNORECASE,
    ),
    re.compile(r"(bearer\s+)([a-zA-Z0-9_\-\.]{8,})", re.IGNORECASE),
]


def redact_secrets_for_display(text: str) -> tuple[str, bool]:
    """Mask credentials and tokens in text for safe terminal/log display."""
    redacted = False

    def _replace_kv(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        prefix, val, suffix = m.group(1), m.group(2), m.group(3)
        masked_val = val[:2] + "*" * (len(val) - 4) + val[-2:] if len(val) > 6 else "****"
        return f"{prefix}{masked_val}{suffix}"

    def _replace_bearer(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        prefix, token = m.group(1), m.group(2)
        masked_token = token[:3] + "*" * 8 + "[REDACTED]"
        return f"{prefix}{masked_token}"

    result = SECRET_VALUE_PATTERNS[0].sub(_replace_kv, text)
    result = SECRET_VALUE_PATTERNS[1].sub(_replace_bearer, result)
    return result, redacted


def generate_unified_diff(
    original_text: str | None,
    proposed_text: str,
    file_path: Path,
    relative_root: Path | None = None,
    mask_secrets: bool = True,
) -> str:
    """Generate exact unified diff, optionally masking sensitive credentials for safe display."""
    old_content = original_text or ""
    new_content = proposed_text

    if mask_secrets:
        old_content, _ = redact_secrets_for_display(old_content)
        new_content, _ = redact_secrets_for_display(new_content)

    old_lines = old_content.splitlines(keepends=True) if original_text is not None else []
    new_lines = new_content.splitlines(keepends=True)

    rel_name = file_path.name
    if relative_root:
        try:
            rel_name = str(file_path.resolve().relative_to(relative_root.resolve()))
        except ValueError:
            rel_name = str(file_path)

    fromfile = f"a/{rel_name}" if original_text is not None else "/dev/null"
    tofile = f"b/{rel_name}"

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=fromfile,
        tofile=tofile,
    )
    return "".join(diff)


class Differ:
    """Computes unified diffs, conflict warnings, and drift summaries across proposed changes."""

    @staticmethod
    def compute_diff(
        changes: list[ConfigChange],
        workspace_root: Path | None = None,
        mask_secrets: bool = True,
    ) -> DiffResult:
        """Compute unified diffs for a list of configuration changes."""
        diff_chunks: list[str] = []
        summary_lines: list[str] = []

        changed_count = 0
        created_count = 0
        has_conflicts = False
        any_redactions = False

        for change in changes:
            # Check for user-owned conflict
            if change.is_user_owned_conflict:
                has_conflicts = True
                summary_lines.append(
                    f"PRESERVED: {change.file_path} (User-authored file protected from overwrite)"
                )
                continue

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
                relative_root=workspace_root,
                mask_secrets=mask_secrets,
            )
            if mask_secrets:
                _, red_orig = redact_secrets_for_display(change.original_content or "")
                _, red_prop = redact_secrets_for_display(change.proposed_content or "")
                if red_orig or red_prop:
                    any_redactions = True

            if chunk:
                diff_chunks.append(
                    f"# Target: {change.file_path} [{change.provider.value}]\n{chunk}"
                )

        summary = f"{changed_count} file(s) to align ({created_count} new, {changed_count - created_count} modified)."
        if has_conflicts:
            summary += (
                "\n  [WARNING] User-authored agent files detected and protected from overwrite."
            )
        if summary_lines:
            summary = summary + "\n" + "\n".join(f"  - {line}" for line in summary_lines)

        header_notes = ""
        if any_redactions:
            header_notes = "[SECURITY NOTICE] Sensitive credentials detected and masked in this diff preview.\n\n"

        return DiffResult(
            changes=changes,
            unified_diff=header_notes + "\n\n".join(diff_chunks) if diff_chunks else "",
            summary=summary,
            has_conflicts=has_conflicts,
            has_redactions=any_redactions,
        )
