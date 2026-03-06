"""Tests for cifix diagnose command."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from cifix.cli import cli
from cifix.cli.diagnose_cmd import _extract_ruff_targets


# -- _extract_ruff_targets -------------------------------------------------

class TestExtractRuffTargets:
    def _make_err(self, pattern_name="", tool="", file_path=None, line=""):
        return SimpleNamespace(
            pattern_name=pattern_name,
            tool=tool,
            file_path=file_path,
            line=line,
            matched_text=line,
        )

    def test_extracts_from_file_path(self):
        result = SimpleNamespace(errors=[
            self._make_err(pattern_name="ruff_check", file_path="src/app.py"),
        ])
        assert _extract_ruff_targets(result) == ["src/app.py"]

    def test_extracts_from_line_pattern(self):
        result = SimpleNamespace(errors=[
            self._make_err(
                pattern_name="ruff_lint",
                line="src/utils.py:12:1: E501 Line too long",
            ),
        ])
        assert _extract_ruff_targets(result) == ["src/utils.py"]

    def test_deduplicates(self):
        result = SimpleNamespace(errors=[
            self._make_err(pattern_name="ruff_check", file_path="src/app.py"),
            self._make_err(pattern_name="ruff_lint", line="src/app.py:5:1: E302"),
        ])
        assert _extract_ruff_targets(result) == ["src/app.py"]

    def test_ignores_non_ruff(self):
        result = SimpleNamespace(errors=[
            self._make_err(pattern_name="pytest_failure", file_path="tests/test_foo.py"),
        ])
        assert _extract_ruff_targets(result) == []

    def test_empty_errors(self):
        result = SimpleNamespace(errors=[])
        assert _extract_ruff_targets(result) == []

    def test_handles_missing_attrs(self):
        """Errors without file_path or line attrs shouldn't crash."""
        err = SimpleNamespace(pattern_name="ruff_check", tool="")
        result = SimpleNamespace(errors=[err])
        assert _extract_ruff_targets(result) == []


# -- CLI integration -------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_classify_result():
    """A classification result with one ruff error."""
    err = SimpleNamespace(
        pattern_name="ruff_check",
        tool="ruff",
        file_path="src/app.py",
        line="src/app.py:1:1: E501",
        matched_text="src/app.py:1:1: E501",
        error_type="lint_violation",
        category=SimpleNamespace(value="code"),
        severity=SimpleNamespace(value="error"),
    )
    return SimpleNamespace(
        errors=[err],
        to_dict=lambda: {"errors": [{"pattern": "ruff_check", "file": "src/app.py"}]},
    )


@pytest.fixture
def mock_classify_no_ruff():
    """A classification result with no ruff errors."""
    err = SimpleNamespace(
        pattern_name="pytest_failure",
        tool="pytest",
        file_path="tests/test_foo.py",
        line="",
        matched_text="",
        error_type="test_failure",
        category=SimpleNamespace(value="code"),
        severity=SimpleNamespace(value="error"),
    )
    return SimpleNamespace(
        errors=[err],
        to_dict=lambda: {"errors": [{"pattern": "pytest_failure"}]},
    )


class TestDiagnoseNoRuff:
    @patch("cifix.cli.diagnose_cmd.fetch_run_logs", return_value=[("log.txt", "some log")])
    @patch("cifix.cli.diagnose_cmd.classify")
    @patch("cifix.cli.diagnose_cmd.format_analysis", return_value="Analysis output")
    def test_exits_cleanly_no_ruff(self, _fmt, mock_cls, _logs, runner, mock_classify_no_ruff):
        mock_cls.return_value = mock_classify_no_ruff
        result = runner.invoke(cli, [
            "diagnose", "123", "-r", "owner/repo", "-t", "fake-token",
        ])
        assert result.exit_code == 0
        assert "No ruff-fixable errors" in result.output


class TestDiagnoseNoFix:
    @patch("cifix.cli.diagnose_cmd.fetch_run_logs", return_value=[("log.txt", "some log")])
    @patch("cifix.cli.diagnose_cmd.classify")
    @patch("cifix.cli.diagnose_cmd.format_analysis", return_value="Analysis output")
    def test_no_fix_flag(self, _fmt, mock_cls, _logs, runner, mock_classify_result):
        mock_cls.return_value = mock_classify_result
        result = runner.invoke(cli, [
            "diagnose", "123", "-r", "owner/repo", "-t", "fake-token", "--no-fix",
        ])
        assert result.exit_code == 0
        assert "Skipping auto-fix" in result.output


class TestDiagnoseDryRun:
    @patch("cifix.cli.diagnose_cmd.fetch_run_logs", return_value=[("log.txt", "some log")])
    @patch("cifix.cli.diagnose_cmd.classify")
    @patch("cifix.cli.diagnose_cmd.format_analysis", return_value="Analysis output")
    @patch("cifix.cli.diagnose_cmd.RuffFixer")
    def test_dry_run(self, mock_fixer_cls, _fmt, mock_cls, _logs, runner, mock_classify_result, tmp_path):
        mock_cls.return_value = mock_classify_result

        mock_fixer = MagicMock()
        mock_fixer.fix_all.return_value = [
            SimpleNamespace(tool="ruff format", files_changed=1, ok=True, changes=[], stderr=""),
            SimpleNamespace(tool="ruff check --fix", files_changed=0, ok=True, changes=[], stderr=""),
        ]
        mock_fixer_cls.return_value = mock_fixer

        result = runner.invoke(cli, [
            "diagnose", "123", "-r", "owner/repo", "-t", "fake-token",
            "--dry-run", "--repo-path", str(tmp_path),
        ])
        assert result.exit_code == 0
        assert "Previewing" in result.output
        mock_fixer_cls.assert_called_once_with(str(tmp_path), dry_run=True)


class TestDiagnoseJson:
    @patch("cifix.cli.diagnose_cmd.fetch_run_logs", return_value=[("log.txt", "some log")])
    @patch("cifix.cli.diagnose_cmd.classify")
    @patch("cifix.cli.diagnose_cmd.format_analysis", return_value="")
    def test_json_no_ruff(self, _fmt, mock_cls, _logs, runner, mock_classify_no_ruff):
        mock_cls.return_value = mock_classify_no_ruff
        result = runner.invoke(cli, [
            "diagnose", "123", "-r", "owner/repo", "-t", "fake-token", "--json-output",
        ])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ruff_fixable"] is False