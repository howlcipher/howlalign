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
```

## 3. Testing Isolation Boundaries

When developing HowlAlign, **never modify real user AI configuration files**.

All tests must run against isolated fixtures:
- Use pytest's `tmp_path` fixture for filesystem operations.
- Explicitly pass `home_dir` and `workspace_dir` to `ProviderDiscovery`, `AlignmentEngine`, `Doctor`, and `ConfigWriter`.
- Use `CliRunner.isolated_filesystem()` for testing CLI commands.

## 4. Adding a New Provider Adapter

To implement an adapter for an additional AI assistant:

1. Add the new provider identifier to `ProviderType` in `howlalign/core/models.py`.
2. Implement a new adapter class inheriting from `BaseAdapter` in `howlalign/adapters/<name>.py`:
   - Implement `provider_type`.
   - Implement `generate_changes(policy, is_global) -> list[ConfigChange]`.
   - Implement `check_health(policy, info, is_global) -> list[DiagnosticItem]`.
3. Add provider discovery in `howlalign/core/discovery.py`.
4. Register the new adapter in `howlalign/core/engine.py` and `howlalign/core/doctor.py`.
5. Add test coverage in `tests/test_adapters.py`.

## 5. Security & Verification Checklist

Before committing changes:
- Verify that `ConfigWriter` performs SHA-256 fingerprint checks before atomic file replacement.
- Confirm that timestamped backups and rollback restore cleanly.
- Confirm zero secrets or tokens are logged or included in test fixtures.
- Verify 100% of the pytest test suite passes.
