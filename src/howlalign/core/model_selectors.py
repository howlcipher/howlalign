"""Resolve ``latest:<family>`` model selectors against each CLI's live model list.

A selector names a model family rather than a version, so a policy keeps tracking
the newest release. Exact model IDs are never touched. A selector that cannot be
resolved raises an error: HowlAlign does not substitute a different model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from howlalign.core.discovery import discover_agy_models
from howlalign.core.exceptions import ModelResolutionError
from howlalign.core.models import ProviderType

LATEST_PREFIX = "latest:"

# Claude Code resolves these aliases to the newest model itself, so the alias is
# what gets written and no model list is needed.
CLAUDE_ALIASES = frozenset({"opus", "sonnet", "haiku"})

_MODEL_ID_PATTERNS = {
    ProviderType.CODEX: re.compile(r"^gpt-(\d+(?:\.\d+)*)-([a-z][a-z0-9-]*)$"),
    ProviderType.AGY: re.compile(r"^gemini-(\d+(?:\.\d+)*)-([a-z][a-z0-9-]*)$"),
}


def is_latest_selector(value: str) -> bool:
    """Return True when a policy model value is a ``latest:<family>`` selector."""
    return value.startswith(LATEST_PREFIX)


def resolve_latest(provider: ProviderType, selector: str, available: Iterable[str]) -> str:
    """Return the newest available model for a selector, or raise if there is none."""
    family = selector[len(LATEST_PREFIX) :].strip().lower()
    if not family:
        raise ModelResolutionError(f"Model selector '{selector}' does not name a family.")

    if provider == ProviderType.CLAUDE:
        if family in CLAUDE_ALIASES:
            return family
        raise ModelResolutionError(
            f"Claude model selector '{selector}' is not supported. "
            f"Use one of {sorted(CLAUDE_ALIASES)} or pin an exact model ID."
        )

    candidates: list[tuple[tuple[int, ...], str]] = []
    pattern = _MODEL_ID_PATTERNS[provider]
    for model_id in available:
        match = pattern.match(model_id)
        if match and match.group(2) == family:
            version = tuple(int(part) for part in match.group(1).split("."))
            candidates.append((version, model_id))

    if not candidates:
        raise ModelResolutionError(
            f"No {provider.value} model matches '{selector}'. HowlAlign will not substitute "
            f"another model. Check that the {provider.value} CLI is installed and signed in, "
            "pin an exact model ID, or remove the provider from the enabled list."
        )
    return max(candidates)[1]


def discover_models(provider: ProviderType, home_dir: Path) -> list[str]:
    """List the models a provider's CLI currently offers, or [] if it cannot say."""
    if provider == ProviderType.CODEX:
        return _read_codex_model_cache(home_dir / ".codex" / "models_cache.json")
    if provider == ProviderType.AGY:
        return discover_agy_models()
    return []


def _read_codex_model_cache(cache_path: Path) -> list[str]:
    """Read the user-visible model IDs from the cache the Codex CLI keeps current."""
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        return [
            model["slug"]
            for model in cache.get("models", [])
            if model.get("visibility") == "list" and isinstance(model.get("slug"), str)
        ]
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return []
