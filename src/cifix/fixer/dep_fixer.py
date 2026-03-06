"""Phase 4: Dependency fixer — detect ModuleNotFoundError, map to PyPI, edit config files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Common import names that differ from their PyPI package name.
# Key: the module name used in `import X`, Value: the PyPI package name.
IMPORT_TO_PYPI: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "attr": "attrs",
    "dotenv": "python-dotenv",
    "gi": "PyGObject",
    "serial": "pyserial",
    "usb": "pyusb",
    "wx": "wxPython",
    "Crypto": "pycryptodome",
    "jwt": "PyJWT",
    "lxml": "lxml",
    "dateutil": "python-dateutil",
    "jose": "python-jose",
    "magic": "python-magic",
    "multipart": "python-multipart",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "xlrd": "xlrd",
    "openpyxl": "openpyxl",
    "redis": "redis",
    "bson": "pymongo",
    "gridfs": "pymongo",
    "pymongo": "pymongo",
    "psycopg2": "psycopg2-binary",
    "MySQLdb": "mysqlclient",
    "mysql": "mysql-connector-python",
    "google": "google-api-python-client",
    "nacl": "PyNaCl",
    "socks": "PySocks",
}

# Regex to extract module name from "ModuleNotFoundError: No module named 'foo'"
# or "ImportError: No module named 'foo.bar'"
_MODULE_RE = re.compile(
    r"(?:ModuleNotFoundError|ImportError):\s+No module named\s+'([^']+)'",
    re.IGNORECASE,
)


@dataclass
class DepFixResult:
    """Outcome of a dependency fix attempt."""
    missing_modules: list[str] = field(default_factory=list)
    mapped_packages: dict[str, str] = field(default_factory=dict)  # module -> pypi
    added_to_requirements: list[str] = field(default_factory=list)
    added_to_pyproject: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_fixes(self) -> bool:
        return bool(self.added_to_requirements or self.added_to_pyproject)

    def to_dict(self) -> dict:
        return {
            "missing_modules": self.missing_modules,
            "mapped_packages": self.mapped_packages,
            "added_to_requirements": self.added_to_requirements,
            "added_to_pyproject": self.added_to_pyproject,
            "errors": self.errors,
        }


def extract_missing_modules(classified_errors) -> list[str]:
    """Extract module names from import_error classified errors.

    Looks at match_text and source_lines for ModuleNotFoundError/ImportError patterns.
    """
    modules: list[str] = []
    seen: set[str] = set()

    for err in classified_errors:
        if err.error_type != "import_error":
            continue

        # Search match_text first, then source_lines
        texts = [err.match_text] + (err.source_lines or [])
        for text in texts:
            m = _MODULE_RE.search(text)
            if m:
                # Take the top-level package (e.g. 'foo' from 'foo.bar.baz')
                module = m.group(1).split(".")[0]
                if module not in seen:
                    seen.add(module)
                    modules.append(module)
                break

    return modules


def map_module_to_pypi(module_name: str) -> str:
    """Map a Python import name to its PyPI package name.

    Uses the known mapping table, falling back to the module name itself.
    """
    return IMPORT_TO_PYPI.get(module_name, module_name)


def _parse_existing_packages(text: str) -> set[str]:
    """Extract normalized package names from requirements.txt or dependency lines."""
    packages: set[str] = set()
    for line in text.splitlines():
        line = line.strip().strip(",").strip('"').strip("'")
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Strip version specifiers: "requests>=2.31" -> "requests"
        name = re.split(r"[><=!~;\[]", line)[0].strip()
        if name:
            packages.add(name.lower())
    return packages


def add_to_requirements_txt(
    repo_path: Path, packages: list[str], dry_run: bool = False
) -> list[str]:
    """Append missing packages to requirements.txt. Returns list of packages added."""
    req_path = repo_path / "requirements.txt"
    if not req_path.exists():
        return []

    content = req_path.read_text(encoding="utf-8")
    existing = _parse_existing_packages(content)

    to_add = [p for p in packages if p.lower() not in existing]
    if not to_add:
        return []

    if not dry_run:
        # Ensure file ends with newline before appending
        if content and not content.endswith("\n"):
            content += "\n"
        content += "\n".join(to_add) + "\n"
        req_path.write_text(content, encoding="utf-8")

    return to_add


def add_to_pyproject_toml(
    repo_path: Path, packages: list[str], dry_run: bool = False
) -> list[str]:
    """Add missing packages to pyproject.toml [project.dependencies]. Returns list added."""
    toml_path = repo_path / "pyproject.toml"
    if not toml_path.exists():
        return []

    content = toml_path.read_text(encoding="utf-8")

    # Find the dependencies array in [project] section
    dep_match = re.search(
        r"^(dependencies\s*=\s*\[)(.*?)(^\])",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not dep_match:
        return []

    dep_block = dep_match.group(2)
    existing = _parse_existing_packages(dep_block)

    to_add = [p for p in packages if p.lower() not in existing]
    if not to_add:
        return []

    if not dry_run:
        # Build new entries and insert before the closing bracket
        new_entries = "".join(f'    "{pkg}",\n' for pkg in to_add)
        closing_bracket_pos = dep_match.end(2)
        content = content[:closing_bracket_pos] + new_entries + content[closing_bracket_pos:]
        toml_path.write_text(content, encoding="utf-8")

    return to_add


class DepFixer:
    """Detects missing dependencies from CI errors and adds them to project config."""

    def __init__(self, repo_path: str | Path, dry_run: bool = False):
        self.repo_path = Path(repo_path).resolve()
        self.dry_run = dry_run
        if not self.repo_path.is_dir():
            raise FileNotFoundError(f"Repo path not found: {self.repo_path}")

    def fix(self, classified_errors) -> DepFixResult:
        """Extract missing modules from errors and add them to dependency files."""
        result = DepFixResult()

        modules = extract_missing_modules(classified_errors)
        result.missing_modules = modules

        if not modules:
            return result

        # Map each module to its PyPI package name
        packages = []
        for mod in modules:
            pypi = map_module_to_pypi(mod)
            result.mapped_packages[mod] = pypi
            packages.append(pypi)

        # Try adding to requirements.txt
        try:
            added = add_to_requirements_txt(self.repo_path, packages, self.dry_run)
            result.added_to_requirements = added
        except OSError as exc:
            result.errors.append(f"requirements.txt: {exc}")

        # Try adding to pyproject.toml
        try:
            added = add_to_pyproject_toml(self.repo_path, packages, self.dry_run)
            result.added_to_pyproject = added
        except OSError as exc:
            result.errors.append(f"pyproject.toml: {exc}")

        return result


def format_dep_results(result: DepFixResult, dry_run: bool = False) -> str:
    """Render dependency fix results as human-readable output."""
    lines: list[str] = []
    mode = "DRY RUN" if dry_run else "APPLIED"
    lines.append(f"── cifix dep fixer ({mode}) ──\n")

    if not result.missing_modules:
        lines.append("  No missing dependencies detected.")
        return "\n".join(lines)

    lines.append(f"  Missing modules: {', '.join(result.missing_modules)}")
    lines.append("  Mapped packages:")
    for mod, pypi in result.mapped_packages.items():
        marker = " (mapped)" if mod != pypi else ""
        lines.append(f"    {mod} → {pypi}{marker}")

    if result.added_to_requirements:
        lines.append(f"\n  Added to requirements.txt: {', '.join(result.added_to_requirements)}")
    if result.added_to_pyproject:
        lines.append(f"  Added to pyproject.toml:    {', '.join(result.added_to_pyproject)}")

    if not result.has_fixes:
        lines.append("\n  Packages already present in dependency files (no changes needed).")

    if result.errors:
        lines.append("\n  Errors:")
        for e in result.errors:
            lines.append(f"    {e}")

    lines.append("")
    return "\n".join(lines)
