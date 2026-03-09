"""
Regex pattern registry for CI error classification.

To add patterns:
  - Append to INFRA_PATTERNS or CODE_PATTERNS
  - For a new CI provider, add a provider-specific list and merge it
    in register_provider_patterns()

Each entry: (compiled_regex, error_type, severity, suggestion, confidence)
"""

import re
from enum import Enum


class ErrorCategory(Enum):
    INFRASTRUCTURE = "infrastructure"
    CODE = "code"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"


# (pattern, error_type, severity, suggestion, confidence)
PatternEntry = tuple[re.Pattern, str, ErrorSeverity, str, float]


# ---------------------------------------------------------------------------
# Infrastructure patterns — pipeline/environment problems
# ---------------------------------------------------------------------------

INFRA_PATTERNS: list[PatternEntry] = [
    # ── Secrets / env vars ──
    (re.compile(r"secret\s+\S+\s+(not found|is not set|undefined)", re.I),
     "missing_secret", ErrorSeverity.FATAL,
     "Check repository/org secrets and environment configuration.", 0.95),
    (re.compile(r"env(ironment)?\s+var(iable)?\s+\S+\s+(not set|undefined|missing)", re.I),
     "missing_env_var", ErrorSeverity.FATAL,
     "Verify env vars in workflow YAML or environment settings.", 0.95),

    # ── Runner ──
    (re.compile(r"(runner\s+(is not|isn't)\s+available|no matching runner)", re.I),
     "runner_unavailable", ErrorSeverity.FATAL,
     "Check self-hosted runner status or switch to GitHub-hosted runners.", 0.95),
    (re.compile(r"##\[error\]The runner has received a shutdown signal", re.I),
     "runner_shutdown", ErrorSeverity.FATAL,
     "Runner was preempted or shut down. Retry the job.", 0.95),

    # ── Network / registry ──
    (re.compile(r"(connection timed out|ETIMEDOUT|Could not resolve host)", re.I),
     "network_timeout", ErrorSeverity.ERROR,
     "Transient network issue. Retry or check runner connectivity.", 0.85),
    (re.compile(r"(rate limit|API rate|403 rate)", re.I),
     "rate_limit", ErrorSeverity.ERROR,
     "Hit an API rate limit. Add backoff/retry or use caching.", 0.85),
    (re.compile(r"(unauthorized|401|authentication failed|login required).*?(registry|docker|ghcr|ecr)", re.I),
     "registry_auth", ErrorSeverity.FATAL,
     "Registry auth failed. Check docker login credentials/tokens.", 0.90),

    # ── Resources ──
    (re.compile(r"(no space left on device|ENOSPC)", re.I),
     "disk_full", ErrorSeverity.FATAL,
     "Runner ran out of disk. Clean workspace or use a larger runner.", 0.95),
    (re.compile(r"(out of memory|OOM|MemoryError|Cannot allocate memory)", re.I),
     "out_of_memory", ErrorSeverity.FATAL,
     "Process ran out of memory. Use a larger runner or reduce parallelism.", 0.90),
    (re.compile(r"(job timed out|exceeded the maximum|timeout of \d+)", re.I),
     "timeout", ErrorSeverity.FATAL,
     "Job exceeded time limit. Optimize steps or increase timeout.", 0.85),

    # ── Actions / permissions ──
    (re.compile(r"(action|uses).*?(not found|does not exist|deprecated|isn't accessible)", re.I),
     "action_not_found", ErrorSeverity.ERROR,
     "Referenced action is missing or deprecated. Check version/path.", 0.80),
    (re.compile(r"(permission denied|Resource not accessible by integration|403 Forbidden)", re.I),
     "permissions", ErrorSeverity.ERROR,
     "Insufficient permissions. Check GITHUB_TOKEN scopes and job permissions.", 0.80),

    # ── Cache ──
    (re.compile(r"(cache (miss|not found|restore failed)|Unable to restore cache)", re.I),
     "cache_miss", ErrorSeverity.WARNING,
     "Cache miss — first run on this key, or cache was evicted.", 0.75),

    # ── Dependencies (infra-flavored: resolution / network) ──
    (re.compile(r"(Could not find a version|No matching distribution|package .* not found)", re.I),
     "dependency_resolution", ErrorSeverity.ERROR,
     "Package not found. Check package name, version pin, and index URL.", 0.85),
    (re.compile(r"(hash mismatch|integrity check|checksum)", re.I),
     "dependency_integrity", ErrorSeverity.ERROR,
     "Package integrity check failed. Clear cache and retry.", 0.80),

    # ── Docker (infra-flavored) ──
    (re.compile(r"(failed to (fetch|pull|resolve)|manifest unknown|image not found)", re.I),
     "docker_pull_failed", ErrorSeverity.ERROR,
     "Docker image pull failed. Check image name, tag, and registry auth.", 0.85),
    (re.compile(r"COPY failed:.*?(not found|no such file)", re.I),
     "docker_copy_failed", ErrorSeverity.ERROR,
     "COPY source missing. Check .dockerignore and build context.", 0.90),

    # ── GitHub Actions specific ──
    (re.compile(r"##\[error\]Process completed with exit code \d+", re.I),
     "process_exit", ErrorSeverity.WARNING,
     "Generic step failure. Check preceding output for the real error.", 0.30),
]


# ---------------------------------------------------------------------------
# Code patterns — problems with the code being built/tested
# ---------------------------------------------------------------------------

CODE_PATTERNS: list[PatternEntry] = [
    # ── Linting (ruff, flake8, pylint) ──
    (re.compile(r"^.*?:\d+:\d+:\s+[A-Z]\d{3,4}", re.M),
     "lint_violation", ErrorSeverity.ERROR,
     "Fix the lint violation(s) or adjust ruff/linter config.", 0.90),

    # ── Type checking (mypy, pyright) ──
    (re.compile(r"^.*?:\d+:\s+error:\s+", re.M),
     "type_error", ErrorSeverity.ERROR,
     "Fix the type error reported by the type checker.", 0.85),

    # ── Pytest ──
    (re.compile(r"FAILED\s+\S+::\S+"),
     "test_failure", ErrorSeverity.ERROR,
     "One or more tests failed. Check assertion details above.", 0.95),
    (re.compile(r"(AssertionError|assert\s+.*==)", re.I),
     "assertion_error", ErrorSeverity.ERROR,
     "Test assertion failed. Compare expected vs actual values.", 0.85),
    (re.compile(r"(\d+ failed.*\d+ passed|\d+ error.*in \d+)", re.I),
     "test_summary", ErrorSeverity.WARNING,
     "See individual FAILED lines for specifics.", 0.80),

    # ── Python runtime errors ──
    (re.compile(r"Traceback \(most recent call last\):"),
     "traceback", ErrorSeverity.ERROR,
     "Unhandled exception. Check the traceback for root cause.", 0.90),
    (re.compile(r"(SyntaxError|IndentationError|TabError):\s+"),
     "syntax_error", ErrorSeverity.FATAL,
     "Fix the syntax error before pushing.", 0.95),
    (re.compile(r"(ImportError|ModuleNotFoundError):\s+(.+)", re.I),
     "import_error", ErrorSeverity.ERROR,
     "Missing import. Add dependency or fix import path.", 0.90),
    (re.compile(r"(NameError|AttributeError|TypeError|ValueError|KeyError|IndexError):\s+(.+)", re.I),
     "runtime_error", ErrorSeverity.ERROR,
     "Runtime error in application code. Check the traceback.", 0.80),

    # ── Build / compile (generic + Rust/C) ──
    (re.compile(r"error\[E\d{4}\]:", re.M),
     "compile_error", ErrorSeverity.ERROR,
     "Compilation error. Check the source file and line referenced.", 0.90),

    # ── ESLint / JS (future) ──
    (re.compile(r"^\s+\d+:\d+\s+(error|warning)\s+.+\s+\S+/\S+$", re.M),
     "eslint_violation", ErrorSeverity.ERROR,
     "Fix the ESLint violation(s) or adjust config.", 0.85),
]


# ---------------------------------------------------------------------------
# Provider extension hook
# ---------------------------------------------------------------------------

_extra_infra: list[PatternEntry] = []
_extra_code: list[PatternEntry] = []


def register_patterns(
    infra: list[PatternEntry] | None = None,
    code: list[PatternEntry] | None = None,
):
    """Register additional patterns (e.g. for GitLab CI, Jenkins)."""
    if infra:
        _extra_infra.extend(infra)
    if code:
        _extra_code.extend(code)


def get_infra_patterns() -> list[PatternEntry]:
    return INFRA_PATTERNS + _extra_infra


def get_code_patterns() -> list[PatternEntry]:
    return CODE_PATTERNS + _extra_code
