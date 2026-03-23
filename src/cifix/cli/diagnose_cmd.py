"""CLI command: cifix diagnose — fetch logs, classify errors, and auto-fix ruff issues."""

from __future__ import annotations

import json
import sys

import click

from cifix.classifier import classify
from cifix.formatter import format_analysis, format_fix_results, format_dep_results
from cifix.github import fetch_run_logs
from cifix.fixer.ruff_fixer import RuffFixer
from cifix.fixer.dep_fixer import DepFixer


@click.command("diagnose")
@click.argument("run_id")
@click.option("--repo", "-r", required=True, help="GitHub repo (owner/repo).")
@click.option("--token", "-t", default=None, help="GitHub token (or set GITHUB_TOKEN env var).")
@click.option("--provider", "-p", default="github", help="CI provider.")
@click.option("--dry-run", is_flag=True, help="Preview fixes without modifying files.")
@click.option("--apply", "auto_apply", is_flag=True, help="Apply fixes without confirmation prompt.")
@click.option("--no-fix", is_flag=True, help="Classify only, skip auto-fix even if ruff errors found.")
@click.option("--no-verify", is_flag=True, help="Skip post-fix verification step.")
@click.option("--no-diff", is_flag=True, help="Suppress unified diff output.")
@click.option("--repo-path", default=".", type=click.Path(exists=True), help="Local repo path (default: cwd).")
@click.option("--json-output", "as_json", is_flag=True, help="Output everything as JSON.")
@click.option("--no-cache", is_flag=True, help="Bypass the local log cache.")
@click.option(
    "--llm", "llm_provider", default=None,
    type=click.Choice(["anthropic", "openai", "gemini"], case_sensitive=False),
    help="Enable LLM-assisted classification (anthropic, openai, gemini).",
)
@click.option("--explain", is_flag=True, help="Generate AI explanations for errors (requires --llm).")
@click.option("--api-key", default=None, help="API key for the LLM provider.")
def diagnose_cmd(
    run_id: str,
    repo: str,
    token: str | None,
    provider: str,
    dry_run: bool,
    auto_apply: bool,
    no_fix: bool,
    no_verify: bool,
    no_diff: bool,
    repo_path: str,
    as_json: bool,
    no_cache: bool,
    llm_provider: str | None,
    explain: bool,
    api_key: str | None,
) -> None:
    """Fetch CI logs, classify errors, and auto-fix what's possible.

    Chains the observe → plan → act → verify flow end-to-end.
    By default, prompts for confirmation before applying fixes.
    Use --apply to skip the confirmation prompt.

    \b
    Examples:
        cifix diagnose 12345 -r owner/repo
        cifix diagnose 12345 -r owner/repo --dry-run
        cifix diagnose 12345 -r owner/repo --apply     # skip confirmation
        cifix diagnose 12345 -r owner/repo --no-fix    # classify only
    """
    from cifix.cli import get_token, console

    token = get_token(token)

    # ── Phase 1: Observe ─────────────────────────────────────────────────
    if not as_json:
        with console.status("[bold blue]Fetching logs...[/bold blue]"):
            log_files = fetch_run_logs(repo, run_id, token, use_cache=not no_cache)
    else:
        log_files = fetch_run_logs(repo, run_id, token, use_cache=not no_cache)

    raw_log = "\n".join(content for _, content in log_files)

    # ── Phase 2: Plan (classify) ─────────────────────────────────────────
    if not as_json:
        with console.status("[bold blue]Classifying errors...[/bold blue]"):
            result = classify(raw_log, provider=provider)
    else:
        result = classify(raw_log, provider=provider)

    # ── Phase 2.5: LLM Review (optional) ────────────────────────────────
    if llm_provider:
        _run_llm_review(result, llm_provider, api_key, explain, as_json)

    if not as_json:
        console.print(format_analysis(result))

    # Extract ruff-fixable file paths from classified errors
    ruff_targets = _extract_ruff_targets(result)
    has_ruff_errors = len(ruff_targets) > 0

    if not has_ruff_errors:
        if as_json:
            click.echo(json.dumps({
                "classification": result.to_dict(),
                "ruff_fixable": False,
                "fix_results": None,
            }, indent=2))
        else:
            console.print("[dim]No ruff-fixable errors detected.[/dim]")
        # Still check for dependency fixes even without ruff errors
        _run_dep_fix(result, repo_path, dry_run, as_json)
        return

    if not as_json:
        console.print(
            f"\n[bold]Found ruff issues in {len(ruff_targets)} file(s):[/bold] "
            f"{', '.join(ruff_targets)}"
        )

    if no_fix:
        if not as_json:
            console.print("[yellow]Skipping auto-fix (--no-fix).[/yellow]")
        if as_json:
            click.echo(json.dumps({
                "classification": result.to_dict(),
                "ruff_fixable": True,
                "ruff_targets": ruff_targets,
                "fix_results": None,
            }, indent=2))
        return

    # ── Confirmation prompt (unless --apply or --dry-run) ─────────────────
    if not dry_run and not auto_apply and not as_json:
        if not click.confirm("Apply fixes?", default=True):
            console.print("[yellow]Aborted.[/yellow]")
            return

    # ── Phase 3: Act (fix) ───────────────────────────────────────────────
    if not as_json:
        mode = "Previewing" if dry_run else "Applying"
        with console.status(f"[bold blue]{mode} ruff fixes...[/bold blue]"):
            try:
                fixer = RuffFixer(repo_path, dry_run=dry_run)
            except (FileNotFoundError, EnvironmentError) as exc:
                console.print(f"[bold red]Error:[/bold red] {exc}")
                sys.exit(1)
            fix_results = fixer.fix_all(targets=ruff_targets)
    else:
        try:
            fixer = RuffFixer(repo_path, dry_run=dry_run)
        except (FileNotFoundError, EnvironmentError) as exc:
            click.secho(f"Error: {exc}", fg="red", err=True)
            sys.exit(1)
        fix_results = fixer.fix_all(targets=ruff_targets)

    # ── Phase 3.5: Verify ────────────────────────────────────────────────
    verify = None
    if not no_verify and not dry_run:
        if not as_json:
            with console.status("[bold blue]Verifying fixes...[/bold blue]"):
                verify = fixer.verify(targets=ruff_targets)
        else:
            verify = fixer.verify(targets=ruff_targets)

    # ── Output ───────────────────────────────────────────────────────────
    if as_json:
        payload = {
            "classification": result.to_dict(),
            "ruff_fixable": True,
            "ruff_targets": ruff_targets,
            "dry_run": dry_run,
            "fix_results": [
                {
                    "tool": r.tool,
                    "files_changed": r.files_changed,
                    "ok": r.ok,
                }
                for r in fix_results
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
        console.print(format_fix_results(
            fix_results,
            verify=verify,
            show_diff=not no_diff,
            dry_run=dry_run,
        ))

    # ── Phase 4: Dependency fixes ──────────────────────────────────────
    _run_dep_fix(result, repo_path, dry_run, as_json)

    # Exit 1 if issues remain after fix
    if verify and not verify.all_clean:
        sys.exit(1)


def _run_llm_review(
    result, llm_name: str, api_key: str | None, explain: bool, as_json: bool,
) -> None:
    """Run LLM-assisted review and optional explanation generation."""
    from cifix.cli import console

    try:
        from cifix.llm_provider import get_provider
        from cifix.llm_advisor import LLMAdvisor, recompute_verdict
    except ImportError as exc:
        console.print(f"[bold red]LLM support unavailable:[/bold red] {exc}")
        return

    try:
        provider = get_provider(llm_name, api_key=api_key)
    except (ImportError, ValueError) as exc:
        console.print(f"[bold red]LLM error:[/bold red] {exc}")
        return

    advisor = LLMAdvisor(provider)

    # Review low-confidence errors
    review_candidates = sum(1 for e in result.errors if e.needs_llm_review)
    if review_candidates:
        if not as_json:
            with console.status(
                f"[bold blue]Sending {review_candidates} error(s) to {provider.name}...[/bold blue]"
            ):
                review_result = advisor.review_errors(result.errors)
            recompute_verdict(result)
            if review_result.reviewed_count:
                console.print(
                    f"  [green]Reclassified {review_result.reviewed_count} error(s).[/green]"
                )
        else:
            review_result = advisor.review_errors(result.errors)
            recompute_verdict(result)

    # Explain errors
    if explain:
        if not as_json:
            with console.status(
                f"[bold blue]Generating explanations via {provider.name}...[/bold blue]"
            ):
                explain_result = advisor.explain_errors(result.errors)
            if explain_result.explained_count:
                console.print(
                    f"  [green]Added {explain_result.explained_count} explanation(s).[/green]"
                )
        else:
            advisor.explain_errors(result.errors)


def _run_dep_fix(result, repo_path: str, dry_run: bool, as_json: bool) -> None:
    """Run dependency fixer on classified import errors."""
    from cifix.cli import console

    try:
        fixer = DepFixer(repo_path, dry_run=dry_run)
    except FileNotFoundError as exc:
        if not as_json:
            console.print(f"[yellow]Dep fix skipped:[/yellow] {exc}")
        return

    dep_result = fixer.fix(result.errors)

    if not dep_result.missing_modules:
        return

    if as_json:
        click.echo(json.dumps({"dep_fix": dep_result.to_dict()}, indent=2))
    else:
        console.print(format_dep_results(dep_result, dry_run=dry_run))


def _extract_ruff_targets(result) -> list[str]:
    """Pull unique file paths from classified errors that ruff can fix."""
    import re

    ruff_patterns = {"ruff_format", "ruff_check", "ruff_lint", "ruff"}
    targets: set[str] = set()

    for err in result.errors:
        pattern_name = getattr(err, "pattern_name", "") or ""
        tool = getattr(err, "tool", "") or ""

        is_ruff = (
            pattern_name.lower() in ruff_patterns
            or "ruff" in pattern_name.lower()
            or "ruff" in tool.lower()
        )
        if not is_ruff:
            continue

        # Try structured file_path first
        file_path = getattr(err, "file_path", None)
        if file_path:
            targets.add(file_path)
            continue

        # Fall back to parsing "path/to/file.py:line:col: EXXXX" from the matched line
        line = getattr(err, "line", "") or getattr(err, "matched_text", "") or ""
        m = re.match(r"^([^\s:]+\.py):\d+", line)
        if m:
            targets.add(m.group(1))

    return sorted(targets)
