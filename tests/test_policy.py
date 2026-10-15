"""Tests for policy schema, serialization, loading, and validation."""

from pathlib import Path

import pytest

from howlalign.core.models import (
    ApprovalPolicy,
    EffortLevel,
    ProviderType,
    RoleClass,
    SandboxMode,
)
from howlalign.core.policy import (
    DEFAULT_POLICY_VERSION,
    discover_policy_file,
    get_default_policy,
    init_policy_file,
    load_policy_file,
    load_policy_from_dict,
    serialize_policy_toml,
)


def test_default_policy_structure():
    policy = get_default_policy()
    assert policy.schema_version == DEFAULT_POLICY_VERSION
    assert ProviderType.CLAUDE in policy.enabled_providers
    assert ProviderType.CODEX in policy.enabled_providers
    assert ProviderType.AGY in policy.enabled_providers

    assert RoleClass.PLANNING in policy.roles
    assert RoleClass.IMPLEMENTATION in policy.roles
    assert RoleClass.SUPPORT in policy.roles

    assert "search" in policy.agents
    assert "tests" in policy.agents
    assert "docs" in policy.agents

    assert policy.agents["search"].read_only is True
    assert policy.agents["docs"].read_only is True
    assert policy.agents["tests"].read_only is False

    assert policy.permissions.allow_dangerous_bypass is False
    assert policy.permissions.ask_approval == ApprovalPolicy.ON_REQUEST
    assert policy.permissions.sandbox == SandboxMode.WORKSPACE_WRITE


def test_policy_toml_roundtrip(tmp_path: Path):
    policy = get_default_policy()
    toml_str = serialize_policy_toml(policy)

    policy_file = tmp_path / "howlalign.toml"
    policy_file.write_text(toml_str, encoding="utf-8")

    loaded = load_policy_file(policy_file)
    assert loaded.schema_version == policy.schema_version
    assert loaded.enabled_providers == policy.enabled_providers
    assert (
        loaded.roles[RoleClass.PLANNING].claude_model
        == policy.roles[RoleClass.PLANNING].claude_model
    )
    assert loaded.roles[RoleClass.PLANNING].effort == EffortLevel.HIGH
    assert loaded.permissions.allow_dangerous_bypass is False
    assert loaded.permissions.sandbox == SandboxMode.WORKSPACE_WRITE


def test_policy_validation_errors():
    # Missing schema_version
    with pytest.raises(ValueError, match="missing required field 'schema_version'"):
        load_policy_from_dict({})

    # Unsupported schema_version
    with pytest.raises(ValueError, match="Unsupported policy schema_version"):
        load_policy_from_dict({"schema_version": "99.0.0"})


def test_init_policy_file(tmp_path: Path):
    target = tmp_path / "project" / "howlalign.toml"
    created = init_policy_file(path=target)
    assert created.is_file()
    assert target.is_file()

    # Re-init without force should raise FileExistsError
    with pytest.raises(FileExistsError):
        init_policy_file(path=target, force=False)

    # Re-init with force should succeed
    recreated = init_policy_file(path=target, force=True)
    assert recreated == target


def test_discover_policy_file(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert discover_policy_file() is None

    pfile = tmp_path / "howlalign.toml"
    pfile.write_text('schema_version = "0.1.0"\n', encoding="utf-8")
    assert discover_policy_file() == pfile

    custom = tmp_path / "custom.toml"
    custom.write_text('schema_version = "0.1.0"\n', encoding="utf-8")
    assert discover_policy_file(str(custom)) == custom.resolve()
