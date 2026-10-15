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
    """Compute stable SHA-256 fingerprint of the core content ignoring variable metadata lines."""
    lines = [line.strip() for line in text.splitlines() if not FINGERPRINT_LINE_REGEX.match(line)]
    core_content = "\n".join(lines)
    return hashlib.sha256(core_content.encode("utf-8")).hexdigest()[:16]


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

    # 1. If fingerprint line already exists, replace it
    for line in lines:
        if FINGERPRINT_LINE_REGEX.match(line):
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
        return compute_managed_fingerprint("\n".join(body_lines)) == recorded_fp

    parts = content.split("---", 2)
    if len(parts) < 3:
        return False

    fm_lines = [line for line in parts[1].splitlines() if not line.strip().startswith("managed_")]
    body_lines = [line for line in parts[2].splitlines() if not line.strip().startswith("<!--")]

    # Candidate 1: AGY skill format (body only)
    skill_body = "\n".join(body_lines).strip()
    if compute_managed_fingerprint(skill_body) == recorded_fp:
        return True

    # Candidate 2: Claude agent or AGY agent format (frontmatter fields + body)
    combined_1 = "\n".join(fm_lines).strip() + "\n\n" + "\n".join(body_lines).strip()
    if compute_managed_fingerprint(combined_1) == recorded_fp:
        return True

    combined_2 = "\n".join(fm_lines).strip() + "\n" + "\n".join(body_lines).strip()
    if compute_managed_fingerprint(combined_2) == recorded_fp:
        return True

    return False


def has_user_modifications(content: str | None, format_type: str = "md") -> bool:
    """Check if a managed file has user modifications by comparing content with recorded fingerprint."""
    if not content:
        return False
    fp = extract_managed_fingerprint(content, format_type=format_type)
    if not fp:
        return False
    current_fp = compute_managed_fingerprint(content)
    if current_fp == fp:
        return False
    # Check legacy v0.1.2 fingerprint compatibility for untouched files
    if _matches_legacy_v012_fingerprint(content, fp, format_type=format_type):
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
