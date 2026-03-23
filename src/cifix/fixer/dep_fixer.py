"""Phase 4: Dependency fixer — detect ModuleNotFoundError, map to PyPI, edit config files."""

from __future__ import annotations

import re
import sys
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

# Standard library modules — skip these from dependency fixing.
# Built from sys.stdlib_module_names (3.10+) with fallback for older Pythons.
if sys.version_info >= (3, 10):
    _STDLIB_MODULES: frozenset[str] = sys.stdlib_module_names
else:
    # Manually maintained subset for 3.9
    _STDLIB_MODULES = frozenset({
        "abc", "aifc", "argparse", "ast", "asynchat", "asyncio", "asyncore",
        "atexit", "base64", "bdb", "binascii", "binhex", "bisect", "builtins",
        "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
        "codecs", "codeop", "collections", "colorsys", "compileall", "concurrent",
        "configparser", "contextlib", "contextvars", "copy", "copyreg", "cProfile",
        "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime", "dbm",
        "decimal", "difflib", "dis", "distutils", "doctest", "email",
        "encodings", "enum", "errno", "faulthandler", "fcntl", "filecmp",
        "fileinput", "fnmatch", "fractions", "ftplib", "functools", "gc",
        "getopt", "getpass", "gettext", "glob", "graphlib", "grp", "gzip",
        "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
        "imghdr", "imp", "importlib", "inspect", "io", "ipaddress",
        "itertools", "json", "keyword", "lib2to3", "linecache", "locale",
        "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
        "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc",
        "nis", "nntplib", "numbers", "operator", "optparse", "os",
        "ossaudiodev", "pathlib", "pdb", "pickle", "pickletools", "pipes",
        "pkgutil", "platform", "plistlib", "poplib", "posix", "posixpath",
        "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
        "pyclbr", "pydoc", "queue", "quopri", "random", "re", "readline",
        "reprlib", "resource", "rlcompleter", "runpy", "sched", "secrets",
        "select", "selectors", "shelve", "shlex", "shutil", "signal",
        "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
        "spwd", "sqlite3", "ssl", "stat", "statistics", "string",
        "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
        "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
        "termios", "test", "textwrap", "threading", "time", "timeit",
        "tkinter", "token", "tokenize", "trace", "traceback", "tracemalloc",
        "tty", "turtle", "turtledemo", "types", "typing", "unicodedata",
        "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave",
        "weakref", "webbrowser", "winreg", "winsound", "wsgiref",
        "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
        "_thread",
    })


def is_stdlib(module_name: str) -> bool:
    """Return True if the module is part of the Python standard library."""
    return module_name in _STDLIB_MODULES


@dataclass
class DepFixResult:
    """Outcome of a dependency fix attempt."""
    missing_modules: list[str] = field(default_factory=list)
    skipped_stdlib: list[str] = field(default_factory=list)
    mapped_packages: dict[str, str] = field(default_factory=dict)  # module -> pypi
    added_to_requirements: list[str] = field(default_factory=list)
    added_to_pyproject: list[str] = field(default_factory=list)
    added_to_poetry: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_fixes(self) -> bool:
        return bool(self.added_to_requirements or self.added_to_pyproject or self.added_to_poetry)

    def to_dict(self) -> dict:
        return {
            "missing_modules": self.missing_modules,
            "skipped_stdlib": self.skipped_stdlib,
            "mapped_packages": self.mapped_packages,
            "added_to_requirements": self.added_to_requirements,
            "added_to_pyproject": self.added_to_pyproject,
            "added_to_poetry": self.added_to_poetry,
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
    """Add missing packages to pyproject.toml [project.dependencies] (PEP 621). Returns list added."""
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


def add_to_poetry_pyproject(
    repo_path: Path, packages: list[str], dry_run: bool = False
) -> list[str]:
    """Add missing packages to pyproject.toml [tool.poetry.dependencies] (Poetry). Returns list added."""
    toml_path = repo_path / "pyproject.toml"
    if not toml_path.exists():
        return []

    content = toml_path.read_text(encoding="utf-8")

    # Check if this is a Poetry project
    if "[tool.poetry.dependencies]" not in content:
        return []

    # Find the [tool.poetry.dependencies] section
    section_match = re.search(
        r"(\[tool\.poetry\.dependencies\]\s*\n)(.*?)(?=\n\[|\Z)",
        content,
        re.DOTALL,
    )
    if not section_match:
        return []

    dep_block = section_match.group(2)

    # Parse existing poetry deps (format: package = "^1.0" or package = {version = "..."})
    existing: set[str] = set()
    for line in dep_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^(\S+)\s*=', line)
        if m:
            existing.add(m.group(1).lower())

    to_add = [p for p in packages if p.lower() not in existing]
    if not to_add:
        return []

    if not dry_run:
        # Insert new entries at end of section
        new_entries = "".join(f'{pkg} = "*"\n' for pkg in to_add)
        insert_pos = section_match.end(2)
        # Ensure there's a newline before our entries
        if content[insert_pos - 1:insert_pos] != "\n":
            new_entries = "\n" + new_entries
        content = content[:insert_pos] + new_entries + content[insert_pos:]
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

        if not modules:
            return result

        # Filter out stdlib modules
        filtered = []
        for mod in modules:
            if is_stdlib(mod):
                result.skipped_stdlib.append(mod)
            else:
                filtered.append(mod)

        result.missing_modules = filtered

        if not filtered:
            return result

        # Map each module to its PyPI package name
        packages = []
        for mod in filtered:
            pypi = map_module_to_pypi(mod)
            result.mapped_packages[mod] = pypi
            packages.append(pypi)

        # Try adding to requirements.txt
        try:
            added = add_to_requirements_txt(self.repo_path, packages, self.dry_run)
            result.added_to_requirements = added
        except OSError as exc:
            result.errors.append(f"requirements.txt: {exc}")

        # Try adding to pyproject.toml (PEP 621)
        try:
            added = add_to_pyproject_toml(self.repo_path, packages, self.dry_run)
            result.added_to_pyproject = added
        except OSError as exc:
            result.errors.append(f"pyproject.toml (PEP 621): {exc}")

        # Try adding to pyproject.toml (Poetry)
        try:
            added = add_to_poetry_pyproject(self.repo_path, packages, self.dry_run)
            result.added_to_poetry = added
        except OSError as exc:
            result.errors.append(f"pyproject.toml (Poetry): {exc}")

        return result
