"""cifix CLI - CI failure analyzer."""

import json
import os
import click

from rich.console import Console

console = Console()


def get_token(token):
    """Resolve GitHub token from option or environment."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise click.ClickException(
            "GitHub token required. Pass --token or set GITHUB_TOKEN env var."
        )
    return token


@click.group()
@click.version_option(package_name="cifix")
def cli():
    """cifix - CI failure analyzer."""
    pass


@cli.command()
@click.argument("run_id")
@click.option("--repo", "-r", required=True, help="GitHub repo (owner/repo).")
@click.option("--token", "-t", default=None, help="GitHub token (or set GITHUB_TOKEN env var).")
@click.option("--no-cache", is_flag=True, help="Bypass the local log cache.")
def logs(run_id, repo, token, no_cache):
    """Fetch and display logs for a CI run."""
    from rich.panel import Panel
    from cifix.github import fetch_run_logs

    token = get_token(token)

    with console.status(f"[bold blue]Fetching logs for run {run_id}...[/bold blue]"):
        log_files = fetch_run_logs(repo, run_id, token, use_cache=not no_cache)

    for filename, content in log_files:
        console.print(Panel(content, title=f"[bold]{filename}[/bold]", border_style="blue"))


@cli.command("classify")
@click.argument("run_id")
@click.option("--repo", "-r", required=True, help="GitHub repo (owner/repo).")
@click.option("--token", "-t", default=None, help="GitHub token (or set GITHUB_TOKEN env var).")
@click.option(
    "--provider", "-p",
    default="github",
    help="CI provider (github, gitlab, jenkins).",
)
@click.option(
    "--output", "-o",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
@click.option(
    "--category", "-c",
    type=click.Choice(["all", "infra", "code"]),
    default="all",
    help="Filter by error category.",
)
@click.option(
    "--severity", "-s",
    type=click.Choice(["all", "fatal", "error", "warning"]),
    default="all",
    help="Minimum severity to show.",
)
@click.option("--no-cache", is_flag=True, help="Bypass the local log cache.")
def classify_cmd(run_id, repo, token, provider, output, category, severity, no_cache):
    """Classify errors in a CI run's logs."""
    from cifix.classifier import classify
    from cifix.formatter import format_analysis
    from cifix.github import fetch_run_logs
    from cifix.patterns import ErrorCategory, ErrorSeverity

    token = get_token(token)

    with console.status("[bold blue]Fetching logs...[/bold blue]"):
        log_files = fetch_run_logs(repo, run_id, token, use_cache=not no_cache)

    raw_log = "\n".join(content for _, content in log_files)

    with console.status("[bold blue]Classifying errors...[/bold blue]"):
        result = classify(raw_log, provider=provider)

    # Apply filters
    if category != "all":
        cat_filter = ErrorCategory.INFRASTRUCTURE if category == "infra" else ErrorCategory.CODE
        result.errors = [e for e in result.errors if e.category == cat_filter]

    if severity != "all":
        sev_map = {"fatal": 0, "error": 1, "warning": 2}
        min_sev = sev_map[severity]
        sev_rank = {ErrorSeverity.FATAL: 0, ErrorSeverity.ERROR: 1, ErrorSeverity.WARNING: 2}
        result.errors = [e for e in result.errors if sev_rank[e.severity] <= min_sev]

    # Output
    if output == "json":
        console.print_json(json.dumps(result.to_dict(), indent=2))
    else:
        console.print(format_analysis(result))

from cifix.cli.fix_cmd import fix_cmd
from cifix.cli.diagnose_cmd import diagnose_cmd

cli.add_command(fix_cmd)
cli.add_command(diagnose_cmd)
