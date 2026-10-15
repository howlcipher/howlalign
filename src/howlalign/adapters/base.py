"""Base provider adapter interface and shared helpers."""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path

from howlalign.core.models import (
    ConfigChange,
    DiagnosticItem,
    Policy,
    ProviderInfo,
    ProviderType,
)

FINGERPRINT_PATTERN_MD = re.compile(r"^\s*managed_fingerprint:\s*([0-9a-fA-F]+)", re.MULTILINE)
FINGERPRINT_PATTERN_TOML = re.compile(
    r'^\s*#?\s*managed_fingerprint\s*=\s*["\']([0-9a-fA-F]+)["\']', re.MULTILINE
)
FINGERPRINT_LINE_REGEX = re.compile(r"^\s*(?:#|<!--)?\s*managed_fingerprint\b.*$", re.IGNORECASE)
MARKER_LINE_REGEX = re.compile(r"^\s*(?:#|<!--)?\s*managed[ _-]by\b", re.IGNORECASE)


def safe_read_text(path: Path) -> str | None:
    """Read text file if present, returning None if missing."""
    return path.read_text(encoding="utf-8") if path.is_file() else None


def compute_managed_fingerprint(text: str) -> str:
    """Compute stable canonical SHA-256 fingerprint of managed document content.

    Preserves all leading/trailing whitespace, indentation, blank lines, and line ordering.
    Normalizes line endings (CRLF -> LF) and excludes only the designated HowlAlign
    fingerprint metadata line within the header block (lines 0..30).
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    filtered: list[str] = []
    fingerprint_removed = False

    for idx, line in enumerate(lines):
        if not fingerprint_removed and idx < 30 and FINGERPRINT_LINE_REGEX.match(line):
            fingerprint_removed = True
            continue
        filtered.append(line)

    canonical = "\n".join(filtered)
    if normalized.endswith("\n") and (not canonical or not canonical.endswith("\n")):
        canonical += "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _compute_legacy_v013_fingerprint(text: str) -> str:
    """Compute fingerprint using legacy v0.1.3 line-stripping algorithm."""
    lines = [line.strip() for line in text.splitlines() if not FINGERPRINT_LINE_REGEX.match(line)]
    core_content = "\n".join(lines)
    return hashlib.sha256(core_content.encode("utf-8")).hexdigest()[:16]


def has_whitespace_modifications(content: str, format_type: str = "md") -> bool:
    """Detect non-canonical or human-modified whitespace in a managed file.

    Evaluates trailing whitespace, multiple consecutive blank lines, end-of-file newline,
    and format-specific indentation invariants.
    """
    lines = content.splitlines()
    # 1. Any trailing spaces or tabs on any line
    if any(line != line.rstrip(" \t") for line in lines):
        return True

    # 2. Multiple consecutive blank lines (normalized \n\n\n)
    if re.search(r"\n{3,}", content.replace("\r\n", "\n")):
        return True

    # 3. Must end with exactly one newline if not empty
    if not content.endswith("\n") or content.endswith("\n\n"):
        return True

    if format_type.lower() == "toml":
        # In generated TOML, all top-level key-values and comments start at column 0
        for line in lines:
            if not line:
                continue
            if line.startswith(" ") or line.startswith("\t"):
                return True
        return False

    # For Markdown (Claude agent, AGY agent, AGY skill)
    in_frontmatter = False
    in_list = False
    for idx, line in enumerate(lines):
        if idx == 0 and line == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line == "---":
                in_frontmatter = False
                in_list = False
                continue
            if line.startswith("  - "):
                in_list = True
                continue
            if in_list and (line.startswith(" ") or line.startswith("\t")):
                # Indentation not matching canonical 2-space list item
                return True
            if line.startswith("  ") and not line.startswith("   "):
                # Description folding or 2-space block
                continue
            if line.startswith(" ") or line.startswith("\t"):
                # Unexpected indentation on key in frontmatter
                return True
            in_list = False
    return False


def embed_managed_fingerprint(content: str, format_type: str = "md") -> str:
    """Compute and embed canonical managed_fingerprint into content header.

    Computes fingerprint over content excluding any fingerprint metadata lines,
    then embeds the canonical fingerprint line directly under the managed_by marker.
    """
    fp = compute_managed_fingerprint(content)
    is_toml = format_type.lower() == "toml"
    fp_line = f'# managed_fingerprint = "{fp}"' if is_toml else f"managed_fingerprint: {fp}"

    lines = content.splitlines()
    replaced = False
    new_lines: list[str] = []

    # 1. If fingerprint line already exists in header, replace it
    for idx, line in enumerate(lines):
        if not replaced and idx < 30 and FINGERPRINT_LINE_REGEX.match(line):
            new_lines.append(fp_line)
            replaced = True
        else:
            new_lines.append(line)

    if replaced:
        result = "\n".join(new_lines)
        if content.endswith("\n") and not result.endswith("\n"):
            result += "\n"
        return result

    # 2. Otherwise insert directly after managed_by marker
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if not inserted and MARKER_LINE_REGEX.match(line):
            new_lines.append(fp_line)
            inserted = True

    if not inserted:
        # Fallback: if markdown with frontmatter, insert after opening ---
        if not is_toml and lines and lines[0].strip() == "---":
            new_lines = [lines[0], fp_line] + lines[1:]
        else:
            new_lines.insert(0, fp_line)

    result = "\n".join(new_lines)
    if content.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def extract_managed_fingerprint(content: str | None, format_type: str = "md") -> str | None:
    """Extract recorded managed_fingerprint from file header if present."""
    if not content:
        return None
    header = "\n".join(content.splitlines()[:25])
    pattern = FINGERPRINT_PATTERN_TOML if format_type.lower() == "toml" else FINGERPRINT_PATTERN_MD
    m = pattern.search(header)
    return m.group(1) if m else None


def _matches_legacy_v012_fingerprint(
    content: str, recorded_fp: str, format_type: str = "md"
) -> bool:
    """Verify if content matches the legacy v0.1.2 fingerprint computation.

    v0.1.2 computed fingerprints over partial bodies rather than full header-bearing files:
    - TOML: role body excluding comment lines
    - AGY skill: markdown body following frontmatter excluding comment markers
    - Claude/AGY agent: frontmatter fields combined with markdown body
    """
    if format_type.lower() == "toml":
        body_lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
        body_str = "\n".join(body_lines)
        candidates = [body_str, body_str + "\n"]
        for c in candidates:
            if (
                compute_managed_fingerprint(c) == recorded_fp
                or _compute_legacy_v013_fingerprint(c) == recorded_fp
            ):
                return True
        return False

    parts = content.split("---", 2)
    if len(parts) < 3:
        return False

    fm_lines = [line for line in parts[1].splitlines() if not line.strip().startswith("managed_")]
    body_lines = [line for line in parts[2].splitlines() if not line.strip().startswith("<!--")]

    # Candidate 1: AGY skill format (body only)
    skill_body = "\n".join(body_lines).strip()
    # Candidate 2: Claude agent or AGY agent format (frontmatter fields + body)
    combined_1 = "\n".join(fm_lines).strip() + "\n\n" + "\n".join(body_lines).strip()
    combined_2 = "\n".join(fm_lines).strip() + "\n" + "\n".join(body_lines).strip()

    for candidate in [skill_body, combined_1, combined_2]:
        if (
            compute_managed_fingerprint(candidate) == recorded_fp
            or _compute_legacy_v013_fingerprint(candidate) == recorded_fp
        ):
            return True

    return False


def has_user_modifications(content: str | None, format_type: str = "md") -> bool:
    """Check if a managed file has user modifications by comparing content with recorded fingerprint.

    Follows a strict conservative hierarchy:
    1. Canonical v0.1.4+: Exact document hash excluding only the header fingerprint line.
    2. Legacy v0.1.3: Matches v0.1.3 fingerprint AND has zero whitespace modifications.
    3. Legacy v0.1.2: Matches v0.1.2 partial-body fingerprint AND has zero whitespace modifications.
    4. Otherwise: Treated as modified/conflict (fails closed to preserve user edits).
    """
    if not content:
        return False
    fp = extract_managed_fingerprint(content, format_type=format_type)
    if not fp:
        # Fail-closed: missing fingerprint in an existing file indicates modification or corruption
        return True

    # 1. Canonical v0.1.4 fingerprint match
    current_fp = compute_managed_fingerprint(content)
    if current_fp == fp:
        return False

    # 2. Check legacy v0.1.3 fingerprint with conservative whitespace verification
    if _compute_legacy_v013_fingerprint(content) == fp:
        if has_whitespace_modifications(content, format_type=format_type):
            # Human whitespace modification detected! Fail closed.
            return True
        # Untouched v0.1.3 artifact: safely eligible for migration to canonical v0.1.4
        return False

    # 3. Check legacy v0.1.2 fingerprint with conservative whitespace verification
    if _matches_legacy_v012_fingerprint(content, fp, format_type=format_type):
        if has_whitespace_modifications(content, format_type=format_type):
            return True
        return False

    return True


def is_file_managed_by_howlalign(content: str | None, format_type: str = "md") -> bool:
    """Determine if an existing configuration/agent file is managed by HowlAlign.

    Inspects the file header (first 20 lines) to avoid false matches on incidental text.
    If the file does not exist, it is considered eligible for creation (managed=True).
    If it exists and contains the provenance marker in the header, it is managed.
    If it exists and lacks the marker in the header, it is user-authored and must NOT be overwritten.
    """
    if content is None:
        return True
    header_text = "\n".join(content.splitlines()[:20]).lower()
    if format_type.lower() == "toml":
        return (
            'managed_by = "howlalign"' in header_text
            or "managed_by: howlalign" in header_text
            or "# managed by howlalign" in header_text
        )
    return (
        "managed_by: howlalign" in header_text
        or 'managed_by = "howlalign"' in header_text
        or "<!-- managed_by: howlalign -->" in header_text
    )


class BaseAdapter(ABC):
    """Abstract base class for assistant provider configuration adapters."""

    def __init__(
        self,
        workspace_dir: Path | None = None,
        home_dir: Path | None = None,
    ) -> None:
        self.workspace = (workspace_dir or Path.cwd()).resolve()
        self.home = (home_dir or Path.home()).resolve()

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the target provider type."""
        ...

    @abstractmethod
    def generate_changes(
        self,
        policy: Policy,
        is_global: bool = False,
    ) -> list[ConfigChange]:
        """Generate the proposed native configuration changes for this provider."""
        ...

    @abstractmethod
    def check_health(
        self,
        policy: Policy,
        info: ProviderInfo,
        is_global: bool = False,
    ) -> list[DiagnosticItem]:
        """Run provider-specific health and compatibility diagnostics."""
        ...
