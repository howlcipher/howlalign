"""Behavior of latest:<family> model selectors."""

import json

import pytest
import toml

from howlalign.core import model_selectors
from howlalign.core.engine import AlignmentEngine
from howlalign.core.exceptions import HowlAlignError, ModelResolutionError
from howlalign.core.models import ProviderType, RoleClass
from howlalign.core.policy import get_default_policy, serialize_policy_toml

CODEX_MODELS = ["gpt-5.6-sol", "gpt-6-sol", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"]
AGY_MODELS = ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.10-flash-high"]


@pytest.mark.parametrize(
    ("provider", "selector", "available", "expected"),
    [
        (ProviderType.CODEX, "latest:sol", CODEX_MODELS, "gpt-6.1-sol"),
        (ProviderType.CODEX, "latest:terra", CODEX_MODELS, "gpt-6.1-terra"),
        (ProviderType.CODEX, "latest:luna", CODEX_MODELS, "gpt-6-luna"),
        (ProviderType.AGY, "latest:flash-medium", AGY_MODELS, "gemini-3.8-flash-medium"),
        (ProviderType.CLAUDE, "latest:sonnet", [], "sonnet"),
    ],
)
def test_selector_resolves_to_newest_in_family(provider, selector, available, expected):
    assert model_selectors.resolve_latest(provider, selector, available) == expected


def test_versions_compare_numerically_not_as_text():
    resolved = model_selectors.resolve_latest(ProviderType.AGY, "latest:flash-high", AGY_MODELS)
    assert resolved == "gemini-3.10-flash-high"


@pytest.mark.parametrize(
    ("provider", "selector", "available"),
    [
        (ProviderType.CODEX, "latest:sol", ["gpt-6-luna"]),
        (ProviderType.CODEX, "latest:sol", []),
        (ProviderType.CODEX, "latest:", CODEX_MODELS),
        (ProviderType.AGY, "latest:flash-high", ["gemini-3.8-flash-medium"]),
        (ProviderType.CLAUDE, "latest:unknown", []),
    ],
)
def test_unresolvable_selector_raises_instead_of_substituting(provider, selector, available):
    with pytest.raises(ModelResolutionError):
        model_selectors.resolve_latest(provider, selector, available)


def test_exact_model_id_is_never_rewritten(monkeypatch):
    def fail(provider, home):
        raise AssertionError("an exact model ID must not trigger discovery")

    monkeypatch.setattr(model_selectors, "discover_models", fail)
    policy = get_default_policy()
    policy.roles[RoleClass.IMPLEMENTATION].codex_model = "gpt-5.6-sol"
    assert policy.get_effective_model("codex", "implementation") == "gpt-5.6-sol"


def test_discovery_runs_once_per_provider(monkeypatch):
    calls = []

    def discover(provider, home):
        calls.append(provider)
        return ["gpt-6.1-sol"]

    monkeypatch.setattr(model_selectors, "discover_models", discover)
    policy = get_default_policy()
    policy.get_effective_model("codex", "planning")
    policy.get_effective_model("codex", "implementation")
    assert calls == [ProviderType.CODEX]


def test_codex_catalog_lists_only_user_visible_models(tmp_path):
    cache = tmp_path / ".codex" / "models_cache.json"
    cache.parent.mkdir()
    cache.write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-6.1-sol", "visibility": "list"},
                    {"slug": "gpt-7-sol", "visibility": "hide"},
                ]
            }
        )
    )
    assert model_selectors._read_codex_model_cache(cache) == ["gpt-6.1-sol"]


@pytest.mark.parametrize("content", [None, "not json", "[]", '{"models": [{}]}'])
def test_unreadable_codex_catalog_is_empty(tmp_path, content):
    cache = tmp_path / "models_cache.json"
    if content is not None:
        cache.write_text(content)
    assert model_selectors._read_codex_model_cache(cache) == []


def test_written_config_holds_the_resolved_id_not_the_selector(tmp_path):
    engine = AlignmentEngine(workspace_dir=tmp_path, home_dir=tmp_path)
    changes = engine.generate_all_changes(provider_filter="codex")
    written = next(c for c in changes if c.file_path.name == "config.toml")
    assert toml.loads(written.proposed_content)["model"] == "gpt-6.1-sol"
    assert "latest:" not in "".join(c.proposed_content for c in changes)


def _policy_with_provider(tmp_path, provider):
    policy = get_default_policy()
    policy.enabled_providers = [provider]
    path = tmp_path / "howlalign.toml"
    path.write_text(serialize_policy_toml(policy))
    return path


def test_selector_survives_a_policy_file_round_trip(tmp_path):
    path = _policy_with_provider(tmp_path, ProviderType.CODEX)
    assert 'codex_model = "latest:sol"' in path.read_text()
    engine = AlignmentEngine(config_path=path, workspace_dir=tmp_path, home_dir=tmp_path)
    assert engine.policy.get_effective_model("codex", "implementation") == "gpt-6.1-sol"


def test_installed_provider_with_no_match_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(model_selectors, "discover_models", lambda provider, home: [])
    path = _policy_with_provider(tmp_path, ProviderType.CODEX)
    engine = AlignmentEngine(config_path=path, workspace_dir=tmp_path, home_dir=tmp_path)
    monkeypatch.setattr(
        engine,
        "get_providers_info",
        lambda: {ProviderType.CODEX: type("Info", (), {"installed": True})()},
    )
    with pytest.raises(HowlAlignError, match="will not substitute"):
        engine.generate_all_changes()


def test_missing_cli_is_skipped_with_a_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(model_selectors, "discover_models", lambda provider, home: [])
    path = _policy_with_provider(tmp_path, ProviderType.CODEX)
    engine = AlignmentEngine(config_path=path, workspace_dir=tmp_path, home_dir=tmp_path)
    monkeypatch.setattr(
        engine,
        "get_providers_info",
        lambda: {ProviderType.CODEX: type("Info", (), {"installed": False})()},
    )
    assert engine.generate_all_changes() == []
    assert "Skipping codex" in capsys.readouterr().err


def test_reports_show_the_selector_when_models_cannot_be_listed(monkeypatch):
    monkeypatch.setattr(model_selectors, "discover_models", lambda provider, home: [])
    eff = get_default_policy().get_effective_provider_policy("codex")
    assert eff.roles[RoleClass.IMPLEMENTATION].model == "latest:sol"
