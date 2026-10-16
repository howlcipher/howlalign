# Developer Guide

## 1. Local Setup

HowlAlign requires Python 3.11+.

```bash
# Create local virtual environment
uv venv .venv
source .venv/bin/activate

# Install development dependencies and editable package
uv pip install -e ".[dev]"
```

## 2. Running Verification

```bash
# Run complete test suite
pytest -v

# Run Ruff linter and formatting checks
ruff check .
ruff format --check .

# Automatically apply safe formatting fixes
ruff format .
ruff check --fix .

# Verify policy resolution matrix
howlalign explain --scope all
```

## 3. Testing Isolation Boundaries

When developing HowlAlign, **never modify real user AI configuration files**.

All tests run under hermetic isolation:
- An autouse fixture in `tests/conftest.py` sets disposable `HOME`, `XDG_STATE_HOME`, and `HOWLALIGN_BACKUP_DIR` pointing to temporary paths for every test run, guaranteeing zero host configuration or state contamination.
- Filesystem operations use pytest's `tmp_path` fixture.
- Components (`ProviderDiscovery`, `AlignmentEngine`, `Doctor`, `ConfigWriter`) accept `home_dir`, `workspace_dir`, and `env` parameters for hermetic dependency injection.
- CLI commands are invoked with `CliRunner.isolated_filesystem()`.

## 4. Provider Independence & Policy Engine Verification

When modifying role models or permissions:
- Verify that changing effort or permissions for one provider (e.g. Codex) does NOT alter the generated configuration or effective settings for other providers (e.g. Claude or AGY).
- Maintain centralized resolution methods on `Policy` in `src/howlalign/core/models.py`.
- Ensure `tests/test_v015_policy_engine.py` and `tests/test_dogfood_lifecycle.py` pass cleanly.

## 5. Adding a New Provider Adapter

To implement an adapter for an additional AI assistant:

1. Add the new provider identifier to `ProviderType` in `howlalign/core/models.py`.
2. Implement a new adapter class inheriting from `BaseAdapter` in `howlalign/adapters/<name>.py`:
   - Implement `provider_type`.
   - Implement `generate_changes(policy, is_global) -> list[ConfigChange]`.
   - Implement `check_health(policy, info, is_global) -> list[DiagnosticItem]`.
3. Add provider discovery in `howlalign/core/discovery.py`.
4. Register the new adapter in `howlalign/core/engine.py` and `howlalign/core/doctor.py`.
5. Add test coverage in `tests/test_adapters.py`.

## 6. Security & Verification Checklist

Before committing changes:
- Verify that `ConfigWriter` performs SHA-256 fingerprint checks before atomic file replacement.
- Confirm that timestamped backups and rollback restore cleanly.
- Confirm that permission escalations trigger `[SECURITY ALERT]` banners in unified diff previews.
- Confirm zero secrets or tokens are logged or included in test fixtures.
- Verify 100% of the pytest test suite passes.

