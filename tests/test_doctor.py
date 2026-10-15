"""Tests for doctor diagnostics and secret safety verification."""

from pathlib import Path

from howlalign.core.doctor import Doctor, check_for_leaked_secrets


def test_check_for_leaked_secrets():
    assert len(check_for_leaked_secrets("normal_key = 'value'")) == 0
    assert len(check_for_leaked_secrets("api_key = 'sk-123456789'")) > 0
    assert len(check_for_leaked_secrets("bearer eyJhbGciOi...")) > 0


def test_doctor_diagnostics(tmp_path: Path):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()

    doctor = Doctor(workspace_dir=workspace, home_dir=home)
    items = doctor.run_diagnostics()

    assert len(items) > 0
    categories = {i.category for i in items}
    assert "CONFIGURATION" in categories
    assert "VERSION" in categories
