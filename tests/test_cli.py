"""Tests for HowlAlign CLI commands."""

from pathlib import Path

from click.testing import CliRunner

from howlalign.cli import cli


def test_cli_version():
    runner = CliRunner()
    res = runner.invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert "howlalign" in res.output


def test_cli_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "init" in res.output
    assert "check" in res.output
    assert "diff" in res.output
    assert "apply" in res.output
    assert "doctor" in res.output
    assert "restore" in res.output


def test_cli_init_check_diff_apply_doctor_workflow(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # 1. Init
        init_res = runner.invoke(cli, ["init"])
        assert init_res.exit_code == 0
        assert "Initialized HowlAlign policy" in init_res.output
        assert Path("howlalign.toml").is_file()

        # 2. Re-init without force fails
        init_dup = runner.invoke(cli, ["init"])
        assert init_dup.exit_code == 1

        # 3. Check
        check_res = runner.invoke(cli, ["check"])
        assert check_res.exit_code == 0
        assert "HowlAlign Provider Inspection" in check_res.output

        # 4. Check JSON
        check_json = runner.invoke(cli, ["check", "--json"])
        assert check_json.exit_code == 0
        assert '"policy_schema_version": "0.1.0"' in check_json.output

        # 5. Diff
        diff_res = runner.invoke(cli, ["diff"])
        assert diff_res.exit_code == 0
        assert "=== Proposed Unified Diff" in diff_res.output

        # 6. Apply with --yes
        apply_res = runner.invoke(cli, ["apply", "--yes"])
        assert apply_res.exit_code == 0
        assert "Successfully aligned configuration" in apply_res.output

        # 7. Second check shows fully aligned (idempotency)
        check_aligned = runner.invoke(cli, ["check"])
        assert check_aligned.exit_code == 0
        assert "All enabled providers are fully aligned" in check_aligned.output

        # 8. Doctor
        doc_res = runner.invoke(cli, ["doctor"])
        assert doc_res.exit_code == 0
        assert "Doctor diagnostics completed" in doc_res.output

        # 9. Doctor JSON
        doc_json = runner.invoke(cli, ["doctor", "--json"])
        assert doc_json.exit_code == 0
        assert "CONFIGURATION" in doc_json.output


def test_cli_scope_flags(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(cli, ["init"])

        # Check with explicit scope options
        res_scope_proj = runner.invoke(cli, ["check", "--scope", "project"])
        assert res_scope_proj.exit_code == 0
        assert "Scope: project" in res_scope_proj.output

        res_scope_glob = runner.invoke(cli, ["check", "--global"])
        assert res_scope_glob.exit_code == 0
        assert "Scope: global" in res_scope_glob.output

        res_scope_all = runner.invoke(cli, ["diff", "--scope", "all"])
        assert res_scope_all.exit_code == 0
        assert "Scope: all" in res_scope_all.output


def test_cli_malformed_policy_fails_cleanly(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        bad_policy = Path("howlalign.toml")
        bad_policy.write_text("invalid = toml [ broken", encoding="utf-8")

        res = runner.invoke(cli, ["check"])
        assert res.exit_code == 1
        assert "Failed to parse" in res.output or "Error" in res.output
