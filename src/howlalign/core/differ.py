"""Unified diff calculation, secret redaction, and change set analysis."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from howlalign.core.models import ConfigChange, DiffResult

# Comprehensive patterns to match sensitive values across JSON, TOML, YAML, env, and headers
SECRET_MULTILINE_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9_-]+ )?PRIVATE KEY-----",
    re.MULTILINE,
)

SECRET_QUOTED_PATTERN = re.compile(
    r'((?:api[_-]?key|access[_-]?token|secret[_-]?key|auth[_-]?token|password|client[_-]?secret|private[_-]?key|token|credential|anthropic[_-]?api[_-]?key|openai[_-]?api[_-]?key|gemini[_-]?api[_-]?key)\s*[:=]\s*["\'])(?!\*{4}\[REDACTED)([^"\']+)(["\'])',
    re.IGNORECASE,
)

SECRET_UNQUOTED_PATTERN = re.compile(
    r'((?:api[_-]?key|access[_-]?token|secret[_-]?key|auth[_-]?token|password|client[_-]?secret|private[_-]?key|token|credential|anthropic[_-]?api[_-]?key|openai[_-]?api[_-]?key|gemini[_-]?api[_-]?key)\s*[:=]\s*)(?!\*{4}\[REDACTED)([^\s#",;\'`]+)',
    re.IGNORECASE,
)

SECRET_BEARER_PATTERN = re.compile(
    r"((?:bearer|authorization\s*:\s*(?:bearer|basic)?)\s+)([a-zA-Z0-9_\-\.\+\/=]{8,})",
    re.IGNORECASE,
)

SECRET_STANDALONE_TOKEN_PATTERN = re.compile(
    r"\b(sk-[a-zA-Z0-9_\-]{15,}|gh[pousr]_[A-Za-z0-9_]{15,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
)


def redact_secrets_for_display(text: str) -> tuple[str, bool]:
    """Mask credentials and tokens in text for safe terminal/log display without revealing prefixes or suffixes."""
    redacted = False
    result = text

    # 1. Multi-line private keys
    if SECRET_MULTILINE_PATTERN.search(result):
        redacted = True
        result = SECRET_MULTILINE_PATTERN.sub("****[REDACTED PRIVATE KEY]****", result)

    # 2. Quoted assignments
    def _replace_quoted(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        prefix, _, suffix = m.group(1), m.group(2), m.group(3)
        return f"{prefix}****[REDACTED]****{suffix}"

    # 3. Unquoted assignments
    def _replace_unquoted(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        prefix = m.group(1)
        return f"{prefix}****[REDACTED]****"

    # 4. Bearer / Authorization headers
    def _replace_bearer(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        prefix = m.group(1)
        return f"{prefix}****[REDACTED]****"

    # 5. Standalone tokens
    def _replace_standalone(m: re.Match) -> str:
        nonlocal redacted
        redacted = True
        return "****[REDACTED TOKEN]****"

    result = SECRET_QUOTED_PATTERN.sub(_replace_quoted, result)
    result = SECRET_UNQUOTED_PATTERN.sub(_replace_unquoted, result)
    result = SECRET_BEARER_PATTERN.sub(_replace_bearer, result)
    result = SECRET_STANDALONE_TOKEN_PATTERN.sub(_replace_standalone, result)

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
    diff_lines = list(diff)
    if not diff_lines and original_text != proposed_text:
        diff_lines = [
            f"--- {fromfile}\n",
            f"+++ {tofile}\n",
            "@@ -1 +1 @@\n",
            "- ****[REDACTED SENSITIVE CONTENT]****\n",
            "+ ****[REDACTED SENSITIVE CONTENT (UPDATED)]****\n",
        ]
    return "".join(diff_lines)


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

        # Scan for permission widening / escalations
        security_alerts: list[str] = []
        for change in changes:
            if change.is_user_owned_conflict or change.original_content == change.proposed_content:
                continue
            orig = change.original_content or ""
            prop = change.proposed_content

            if re.search(
                r'["\']?approval_policy["\']?\s*[:=]\s*["\']never["\']', prop, re.I
            ) and not re.search(
                r'["\']?approval_policy["\']?\s*[:=]\s*["\']never["\']', orig, re.I
            ):
                security_alerts.append(
                    f"[SECURITY ALERT] Permission widening: 'approval_policy' set to 'never' in {change.file_path.name} ({change.provider.value})"
                )
            if re.search(
                r'["\']?toolPermission["\']?\s*[:=]\s*["\']always-proceed["\']', prop, re.I
            ) and not re.search(
                r'["\']?toolPermission["\']?\s*[:=]\s*["\']always-proceed["\']', orig, re.I
            ):
                security_alerts.append(
                    f"[SECURITY ALERT] Permission widening: 'toolPermission' set to 'always-proceed' in {change.file_path.name} ({change.provider.value})"
                )
            if re.search(
                r'["\']?sandbox_mode["\']?\s*[:=]\s*["\']danger-full-access["\']', prop, re.I
            ) and not re.search(
                r'["\']?sandbox_mode["\']?\s*[:=]\s*["\']danger-full-access["\']', orig, re.I
            ):
                security_alerts.append(
                    f"[SECURITY ALERT] Permission widening: 'sandbox_mode' set to 'danger-full-access' in {change.file_path.name} ({change.provider.value})"
                )
            if re.search(
                r'["\']?allowNonWorkspaceAccess["\']?\s*[:=]\s*true', prop, re.I
            ) and not re.search(r'["\']?allowNonWorkspaceAccess["\']?\s*[:=]\s*true', orig, re.I):
                security_alerts.append(
                    f"[SECURITY ALERT] Permission widening: 'allowNonWorkspaceAccess' set to true in {change.file_path.name} ({change.provider.value})"
                )
            if re.search(
                r'["\']?defaultMode["\']?\s*[:=]\s*["\']acceptEdits["\']', prop, re.I
            ) and not re.search(
                r'["\']?defaultMode["\']?\s*[:=]\s*["\']acceptEdits["\']', orig, re.I
            ):
                security_alerts.append(
                    f"[SECURITY ALERT] Autonomous edits enabled: 'defaultMode' set to 'acceptEdits' in {change.file_path.name} ({change.provider.value})"
                )

        summary = f"{changed_count} file(s) to align ({created_count} new, {changed_count - created_count} modified)."
        if security_alerts:
            summary += "\n" + "\n".join(f"  {alert}" for alert in security_alerts)
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
            unified_diff=(header_notes + "\n\n".join(diff_chunks)) if diff_chunks else "",
            summary=summary,
            has_conflicts=has_conflicts,
            has_redactions=any_redactions,
        )
