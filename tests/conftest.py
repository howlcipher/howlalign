"""Hermetic test environment fixture for HowlAlign."""

from pathlib import Path

import pytest

# Stands in for each CLI's live model list, so defaults resolve the same on any machine.
TEST_MODEL_CATALOG = {
    "codex": ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-luna"],
    "agy": ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "claude-sonnet-4-6"],
}


@pytest.fixture(autouse=True)
def hermetic_test_environment(tmp_path_factory, monkeypatch):
    """Ensure all tests run with isolated HOME, XDG_STATE_HOME, and HOWLALIGN_BACKUP_DIR.

    Prevents tests from ever touching or reading the host user's actual configuration
    or state directories (~/.local/state, ~/.claude, ~/.codex, ~/.gemini).
    """
    test_root = tmp_path_factory.mktemp("hermetic_test_env")
    test_home = test_root / "home"
    test_home.mkdir(parents=True, exist_ok=True)
    test_state = test_home / ".local" / "state"
    test_state.mkdir(parents=True, exist_ok=True)
    test_backups = test_state / "howlalign" / "backups"
    test_backups.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(test_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(test_state))
    monkeypatch.setenv("HOWLALIGN_BACKUP_DIR", str(test_backups))
    monkeypatch.setattr(Path, "home", lambda: test_home)
    monkeypatch.setattr(
        "howlalign.core.model_selectors.discover_models",
        lambda provider, home: list(TEST_MODEL_CATALOG.get(provider.value, [])),
    )
