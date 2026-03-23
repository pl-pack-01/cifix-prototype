"""Tests for Phase 4: DepFixer."""

from __future__ import annotations

from pathlib import Path

import pytest

from cifix.classifier import ClassifiedError
from cifix.patterns import ErrorCategory, ErrorSeverity
from cifix.fixer.dep_fixer import (
    DepFixer,
    DepFixResult,
    add_to_pyproject_toml,
    add_to_requirements_txt,
    extract_missing_modules,
    map_module_to_pypi,
)
from cifix.formatter import format_dep_results


# -- Helpers ---------------------------------------------------------------

def _make_import_error(match_text: str, source_lines: list[str] | None = None) -> ClassifiedError:
    return ClassifiedError(
        category=ErrorCategory.CODE,
        error_type="import_error",
        summary=match_text[:200],
        severity=ErrorSeverity.ERROR,
        source_lines=source_lines or [],
        step_name="Run tests",
        suggestion="Missing import.",
        match_text=match_text,
    )


# -- extract_missing_modules -----------------------------------------------

class TestExtractMissingModules:
    def test_extracts_from_match_text(self):
        err = _make_import_error("ModuleNotFoundError: No module named 'yaml'")
        assert extract_missing_modules([err]) == ["yaml"]

    def test_extracts_from_source_lines(self):
        err = _make_import_error(
            "ImportError: some text",
            source_lines=["ModuleNotFoundError: No module named 'requests'"],
        )
        assert extract_missing_modules([err]) == ["requests"]

    def test_extracts_top_level_from_dotted(self):
        err = _make_import_error("ModuleNotFoundError: No module named 'PIL.Image'")
        assert extract_missing_modules([err]) == ["PIL"]

    def test_deduplicates(self):
        e1 = _make_import_error("ModuleNotFoundError: No module named 'yaml'")
        e2 = _make_import_error("ModuleNotFoundError: No module named 'yaml.loader'")
        assert extract_missing_modules([e1, e2]) == ["yaml"]

    def test_ignores_non_import_errors(self):
        err = ClassifiedError(
            category=ErrorCategory.CODE,
            error_type="test_failure",
            summary="FAILED test_foo",
            severity=ErrorSeverity.ERROR,
            match_text="ModuleNotFoundError: No module named 'foo'",
        )
        assert extract_missing_modules([err]) == []

    def test_empty_list(self):
        assert extract_missing_modules([]) == []


# -- map_module_to_pypi ----------------------------------------------------

class TestMapModuleToPyPI:
    def test_known_mapping(self):
        assert map_module_to_pypi("cv2") == "opencv-python"
        assert map_module_to_pypi("PIL") == "Pillow"
        assert map_module_to_pypi("yaml") == "PyYAML"
        assert map_module_to_pypi("sklearn") == "scikit-learn"
        assert map_module_to_pypi("bs4") == "beautifulsoup4"
        assert map_module_to_pypi("dateutil") == "python-dateutil"

    def test_unknown_falls_through(self):
        assert map_module_to_pypi("requests") == "requests"
        assert map_module_to_pypi("flask") == "flask"


# -- add_to_requirements_txt -----------------------------------------------

class TestAddToRequirementsTxt:
    def test_adds_missing_packages(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31\nclick\n", encoding="utf-8")

        added = add_to_requirements_txt(tmp_path, ["flask", "PyYAML"])
        assert added == ["flask", "PyYAML"]
        content = req.read_text()
        assert "flask" in content
        assert "PyYAML" in content

    def test_skips_existing(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31\nflask\n", encoding="utf-8")

        added = add_to_requirements_txt(tmp_path, ["flask", "PyYAML"])
        assert added == ["PyYAML"]

    def test_case_insensitive_match(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("Flask>=2.0\n", encoding="utf-8")

        added = add_to_requirements_txt(tmp_path, ["flask"])
        assert added == []

    def test_dry_run_no_change(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests\n", encoding="utf-8")

        added = add_to_requirements_txt(tmp_path, ["flask"], dry_run=True)
        assert added == ["flask"]
        assert "flask" not in req.read_text()

    def test_no_file_returns_empty(self, tmp_path):
        added = add_to_requirements_txt(tmp_path, ["flask"])
        assert added == []


# -- add_to_pyproject_toml -------------------------------------------------

class TestAddToPyprojectToml:
    def test_adds_missing_packages(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "foo"\ndependencies = [\n    "click>=8.1",\n]\n',
            encoding="utf-8",
        )

        added = add_to_pyproject_toml(tmp_path, ["flask", "PyYAML"])
        assert added == ["flask", "PyYAML"]
        content = toml.read_text()
        assert '"flask"' in content
        assert '"PyYAML"' in content

    def test_skips_existing(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\ndependencies = [\n    "click>=8.1",\n    "flask",\n]\n',
            encoding="utf-8",
        )

        added = add_to_pyproject_toml(tmp_path, ["flask", "PyYAML"])
        assert added == ["PyYAML"]

    def test_dry_run_no_change(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        original = '[project]\ndependencies = [\n    "click",\n]\n'
        toml.write_text(original, encoding="utf-8")

        added = add_to_pyproject_toml(tmp_path, ["flask"], dry_run=True)
        assert added == ["flask"]
        assert toml.read_text() == original

    def test_no_file_returns_empty(self, tmp_path):
        added = add_to_pyproject_toml(tmp_path, ["flask"])
        assert added == []

    def test_no_dependencies_section(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text('[build-system]\nrequires = ["setuptools"]\n', encoding="utf-8")

        added = add_to_pyproject_toml(tmp_path, ["flask"])
        assert added == []


# -- DepFixer integration --------------------------------------------------

class TestDepFixer:
    def test_missing_repo_path(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DepFixer(tmp_path / "nonexistent")

    def test_no_import_errors(self, tmp_path):
        fixer = DepFixer(tmp_path)
        result = fixer.fix([])
        assert result.missing_modules == []
        assert not result.has_fixes

    def test_full_pipeline(self, tmp_path):
        # Create both config files
        req = tmp_path / "requirements.txt"
        req.write_text("click\n", encoding="utf-8")
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\ndependencies = [\n    "click",\n]\n',
            encoding="utf-8",
        )

        errors = [
            _make_import_error("ModuleNotFoundError: No module named 'yaml'"),
            _make_import_error("ModuleNotFoundError: No module named 'PIL.Image'"),
        ]

        fixer = DepFixer(tmp_path)
        result = fixer.fix(errors)

        assert result.missing_modules == ["yaml", "PIL"]
        assert result.mapped_packages == {"yaml": "PyYAML", "PIL": "Pillow"}
        assert "PyYAML" in result.added_to_requirements
        assert "Pillow" in result.added_to_requirements
        assert "PyYAML" in result.added_to_pyproject
        assert "Pillow" in result.added_to_pyproject
        assert result.has_fixes

    def test_dry_run(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("click\n", encoding="utf-8")

        errors = [_make_import_error("ModuleNotFoundError: No module named 'flask'")]

        fixer = DepFixer(tmp_path, dry_run=True)
        result = fixer.fix(errors)

        assert result.added_to_requirements == ["flask"]
        assert "flask" not in req.read_text()


# -- format_dep_results ----------------------------------------------------

class TestFormatDepResults:
    def test_no_modules(self):
        out = format_dep_results(DepFixResult())
        assert "No missing dependencies" in out

    def test_with_fixes(self):
        result = DepFixResult(
            missing_modules=["yaml"],
            mapped_packages={"yaml": "PyYAML"},
            added_to_requirements=["PyYAML"],
        )
        out = format_dep_results(result)
        assert "yaml" in out
        assert "PyYAML" in out
        assert "requirements.txt" in out

    def test_dry_run_label(self):
        out = format_dep_results(DepFixResult(), dry_run=True)
        assert "DRY RUN" in out

    def test_applied_label(self):
        out = format_dep_results(DepFixResult(), dry_run=False)
        assert "APPLIED" in out
