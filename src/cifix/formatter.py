"""
Human-readable output formatting for classification results using Rich.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax

from cifix.classifier import AnalysisResult
from cifix.patterns import ErrorCategory


_VERDICT_STYLE = {
    "infrastructure": ("bold yellow", "⚡ Pipeline/infrastructure issue — not your code."),
    "code":           ("bold cyan", "🔧 Code issue — the pipeline itself is fine."),
    "both":           ("bold red", "⚠️  Both infrastructure AND code issues detected."),
    "clean":          ("bold green", "✅ No errors detected."),
}

_SEV_STYLE = {
    "fatal":   ("bold red", "FATAL"),
    "error":   ("red", "ERROR"),
    "warning": ("yellow", "WARN"),
}

_CAT_STYLE = {
    ErrorCategory.INFRASTRUCTURE: "yellow",
    ErrorCategory.CODE: "cyan",
    ErrorCategory.UNKNOWN: "dim",
}


def _make_console(file=None) -> Console:
    """Create a Console writing to a StringIO for capture."""
    return Console(file=file, highlight=False, width=100)


def format_analysis(result: AnalysisResult) -> str:
    """Format an AnalysisResult into a rich terminal report."""
    buf = StringIO()
    console = _make_console(file=buf)

    # Verdict panel
    style, msg = _VERDICT_STYLE.get(result.verdict, ("", ""))
    subtitle = f"{result.infra_count} infra · {result.code_count} code issue(s)"
    if result.low_confidence_count:
        subtitle += f" · {result.low_confidence_count} low-confidence"

    console.print()
    console.print(Panel(
        Text(msg, style=style),
        title="[bold]CI Error Analysis[/bold]",
        subtitle=subtitle,
        border_style="blue",
        padding=(1, 2),
    ))

    if not result.errors:
        return buf.getvalue()

    # Group errors by category
    groups = [
        ("Infrastructure", ErrorCategory.INFRASTRUCTURE),
        ("Code", ErrorCategory.CODE),
        ("Unknown", ErrorCategory.UNKNOWN),
    ]

    for title, cat in groups:
        errors = [e for e in result.errors if e.category == cat]
        if not errors:
            continue

        cat_color = _CAT_STYLE[cat]
        table = Table(
            title=f"[bold {cat_color}]{title} ({len(errors)})[/bold {cat_color}]",
            show_header=True,
            header_style=f"bold {cat_color}",
            border_style="dim",
            show_lines=True,
            expand=True,
            title_justify="left",
            padding=(0, 1),
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Sev", width=5, justify="center")
        table.add_column("Type", style="bold", width=20)
        table.add_column("Summary", ratio=2)
        table.add_column("Conf", width=5, justify="right")

        for i, e in enumerate(errors, 1):
            sev_style, sev_label = _SEV_STYLE.get(e.severity.value, ("dim", "?"))
            conf_pct = int(e.confidence * 100)
            conf_style = "green" if conf_pct >= 70 else "red"
            ai_tag = " [magenta]\\[AI][/magenta]" if e.explanation else ""

            table.add_row(
                str(i),
                f"[{sev_style}]{sev_label}[/{sev_style}]",
                e.error_type,
                f"{e.summary}{ai_tag}",
                f"[{conf_style}]{conf_pct}%[/{conf_style}]",
            )

        console.print(table)

        # Print details (step, suggestion, context, explanation) below the table
        for i, e in enumerate(errors, 1):
            details = []
            if e.step_name:
                details.append(f"[dim]Step:[/dim] {e.step_name}")
            details.append(f"[dim]Fix:[/dim]  {e.suggestion}")
            if e.explanation:
                details.append(f"[dim]AI:[/dim]   {e.explanation}")

            detail_text = "\n".join(details)

            if e.source_lines:
                context = "\n".join(sl.rstrip() for sl in e.source_lines)
                detail_text += f"\n[dim]Context:[/dim]\n{context}"

            console.print(Panel(
                detail_text,
                title=f"[dim]#{i} {e.error_type}[/dim]",
                border_style="dim",
                padding=(0, 1),
                expand=True,
            ))

        console.print()

    return buf.getvalue()


def format_fix_results(
    results,
    verify=None,
    show_diff: bool = True,
    dry_run: bool = False,
) -> str:
    """Render ruff fix results with Rich formatting."""
    buf = StringIO()
    console = _make_console(file=buf)

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]APPLIED[/green]"
    console.print()
    console.print(f"[bold]── Ruff Fixer ({mode}) ──[/bold]")
    console.print()

    total_changed = 0
    for res in results:
        changed = res.files_changed
        total_changed += changed
        icon = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
        console.print(f"  {icon} [bold]{res.tool}[/bold]: {changed} file(s) modified")
        if res.stderr:
            for line in res.stderr.splitlines()[:5]:
                console.print(f"    [dim]{line}[/dim]")

        if show_diff:
            for c in res.changes:
                diff = c.unified_diff()
                if diff:
                    console.print()
                    console.print(Syntax(diff, "diff", theme="monokai", line_numbers=False))

    console.print(f"\n  [bold]Total files changed: {total_changed}[/bold]")

    if verify:
        console.print()
        console.print("[bold]── Verification ──[/bold]")
        fmt_icon = "[green]✓[/green]" if verify.format_clean else "[red]✗[/red]"
        chk_icon = "[green]✓[/green]" if verify.check_clean else "[red]✗[/red]"
        console.print(f"  {fmt_icon} ruff format --check")
        console.print(f"  {chk_icon} ruff check")
        if verify.remaining_issues:
            console.print(f"\n  [yellow]Remaining issues:[/yellow]\n{verify.remaining_issues}")

    console.print()
    return buf.getvalue()


def format_dep_results(result, dry_run: bool = False) -> str:
    """Render dependency fix results with Rich formatting."""
    buf = StringIO()
    console = _make_console(file=buf)

    mode = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]APPLIED[/green]"
    console.print()
    console.print(f"[bold]── Dep Fixer ({mode}) ──[/bold]")
    console.print()

    if not result.missing_modules:
        console.print("  [dim]No missing dependencies detected.[/dim]")
        return buf.getvalue()

    console.print(f"  [bold]Missing modules:[/bold] {', '.join(result.missing_modules)}")

    # Mapping table
    table = Table(show_header=True, header_style="bold", border_style="dim", padding=(0, 1))
    table.add_column("Module", style="cyan")
    table.add_column("→", style="dim", width=2)
    table.add_column("PyPI Package", style="green")
    table.add_column("", width=8)

    for mod, pypi in result.mapped_packages.items():
        mapped = "[dim](mapped)[/dim]" if mod != pypi else ""
        table.add_row(mod, "→", pypi, mapped)
    console.print(table)

    # Show skipped stdlib modules
    skipped = getattr(result, "skipped_stdlib", [])
    if skipped:
        console.print(f"  [dim]Skipped stdlib modules: {', '.join(skipped)}[/dim]")

    if result.added_to_requirements:
        console.print(
            f"  [green]Added to requirements.txt:[/green] "
            f"{', '.join(result.added_to_requirements)}"
        )
    if result.added_to_pyproject:
        console.print(
            f"  [green]Added to pyproject.toml (PEP 621):[/green] "
            f"{', '.join(result.added_to_pyproject)}"
        )
    added_poetry = getattr(result, "added_to_poetry", [])
    if added_poetry:
        console.print(
            f"  [green]Added to pyproject.toml (Poetry):[/green] "
            f"{', '.join(added_poetry)}"
        )

    if not result.has_fixes:
        console.print(
            "\n  [dim]Packages already present in dependency files (no changes needed).[/dim]"
        )

    if result.errors:
        console.print("\n  [red]Errors:[/red]")
        for e in result.errors:
            console.print(f"    [red]• {e}[/red]")

    console.print()
    return buf.getvalue()
