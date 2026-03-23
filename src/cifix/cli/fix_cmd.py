"""CLI command: cifix fix — apply ruff fixes to a local repo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from cifix.fixer.ruff_fixer import RuffFixer
from cifix.formatter import format_fix_results


@click.command("fix")
@click.argument("repo_path", default=".", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Show what would change without modifying files.")
@click.option("--no-verify", is_flag=True, help="Skip the post-fix verification step.")
@click.option("--no-diff", is_flag=True, help="Suppress unified diff output.")
@click.option("--format-only", is_flag=True, help="Run ruff format only (skip ruff check --fix).")
@click.option("--check-only", is_flag=True, help="Run ruff check --fix only (skip ruff format).")
@click.option("--target", "-t", multiple=True, help="Scope fixes to specific files or dirs (relative to repo).")
@click.option("--json-output", "as_json", is_flag=True, help="Output results as JSON.")
def fix_cmd(
    repo_path: str,
    dry_run: bool,
    no_verify: bool,
    no_diff: bool,
    format_only: bool,
    check_only: bool,
    target: tuple[str, ...],
    as_json: bool,
) -> None:
    """Apply ruff format and check fixes to a local repository.

    REPO_PATH defaults to the current directory.

    \b
    Examples:
        cifix fix                          # fix everything in cwd
        cifix fix ./my-repo --dry-run      # preview changes
        cifix fix -t src/app.py -t tests/  # scope to specific paths
        cifix fix --format-only --json-output
    """
    try:
        fixer = RuffFixer(repo_path, dry_run=dry_run)
    except (FileNotFoundError, EnvironmentError) as exc:
        click.secho(f"Error: {exc}", fg="red", err=True)
        sys.exit(1)

    targets = list(target) if target else None

    # -- Run fixes ---------------------------------------------------------
    results = []
    if not check_only:
        results.append(fixer.fix_format(targets))
    if not format_only:
        results.append(fixer.fix_check(targets))

    # -- Verify ------------------------------------------------------------
    verify = None
    if not no_verify and not dry_run:
        verify = fixer.verify(targets)

    # -- Output ------------------------------------------------------------
    if as_json:
        payload = {
            "dry_run": dry_run,
            "results": [
                {
                    "tool": r.tool,
                    "files_changed": r.files_changed,
                    "ok": r.ok,
                    "changes": [
                        {
                            "path": str(c.path),
                            "has_diff": c.has_diff,
                            **({"diff": c.unified_diff()} if not no_diff and c.has_diff else {}),
                        }
                        for c in r.changes
                    ],
                }
                for r in results
            ],
        }
        if verify:
            payload["verification"] = {
                "format_clean": verify.format_clean,
                "check_clean": verify.check_clean,
                "all_clean": verify.all_clean,
                "remaining_issues": verify.remaining_issues or None,
            }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(format_fix_results(
            results,
            verify=verify,
            show_diff=not no_diff,
            dry_run=dry_run,
        ))

    # -- Exit code: 0 if clean, 1 if issues remain ------------------------
    if verify and not verify.all_clean:
        sys.exit(1)