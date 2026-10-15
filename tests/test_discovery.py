"""Tests for provider discovery and capability resolution."""

from pathlib import Path

from howlalign.core.discovery import (
    ProviderDiscovery,
    extract_version_semver,
)
from howlalign.core.models import ProviderType


def test_extract_version_semver():
    assert extract_version_semver("2.1.300 (Claude Code)") == "2.1.300"
    assert extract_version_semver("codex-cli 0.162.1") == "0.162.1"
    assert extract_version_semver("1.3.6") == "1.3.6"
    assert extract_version_semver("1.3.6-beta.1") == "1.3.6-beta.1"
    assert extract_version_semver(None) is None
    assert extract_version_semver("") is None


def test_provider_discovery_isolated(tmp_path: Path):
    mock_home = tmp_path / "home"
    mock_workspace = tmp_path / "workspace"
    mock_home.mkdir()
    mock_workspace.mkdir()

    discovery = ProviderDiscovery(home_dir=mock_home, workspace_dir=mock_workspace)
    results = discovery.discover_all()

    assert ProviderType.CLAUDE in results
    assert ProviderType.CODEX in results
    assert ProviderType.AGY in results

    # Verify capabilities structure
    for prov, info in results.items():
        assert len(info.capabilities) > 0
        assert len(info.unsupported_features) > 0
