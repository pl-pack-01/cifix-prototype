"""
Human-readable output formatting for classification results.
Kept separate so it's easy to swap in Rich (Phase 6) later.
"""

from cifix.classifier import AnalysisResult
from cifix.patterns import ErrorCategory


_VERDICT_MSG = {
    "infrastructure": "⚡ VERDICT: Pipeline/infrastructure issue — not your code.",
    "code":           "🔧 VERDICT: Code issue — the pipeline itself is fine.",
    "both":           "⚠️  VERDICT: Both infrastructure AND code issues detected.",
    "clean":          "✅ No errors detected.",
}

_SEV_ICON = {
    "fatal":   "🔴",
    "error":   "🟠",
    "warning": "🟡",
}


def format_analysis(result: AnalysisResult) -> str:
    """Format an AnalysisResult into a readable terminal report."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("  CI ERROR ANALYSIS")
    lines.append("=" * 60)
    lines.append(_VERDICT_MSG.get(result.verdict, ""))
    lines.append(f"  Found {result.infra_count} infra + {result.code_count} code issue(s)")

    if result.low_confidence_count:
        lines.append(
            f"  ({result.low_confidence_count} low-confidence — "
            f"use --llm for AI-assisted review)"
        )
    lines.append("")

    infra = [e for e in result.errors if e.category == ErrorCategory.INFRASTRUCTURE]
    code = [e for e in result.errors if e.category == ErrorCategory.CODE]
    unknown = [e for e in result.errors if e.category == ErrorCategory.UNKNOWN]

    def _section(title: str, errors):
        if not errors:
            return
        lines.append(f"── {title} ({len(errors)}) {'─' * (40 - len(title))}")
        for i, e in enumerate(errors, 1):
            icon = _SEV_ICON.get(e.severity.value, "⚪")
            conf_pct = int(e.confidence * 100)
            ai_tag = " [AI]" if e.explanation else ""
            lines.append(f"  {i}. {icon} [{e.error_type}] {e.summary} [{conf_pct}%]{ai_tag}")
            if e.step_name:
                lines.append(f"     Step: {e.step_name}")
            lines.append(f"     Suggestion: {e.suggestion}")
            if e.explanation:
                lines.append(f"     Explanation: {e.explanation}")
            if e.source_lines:
                lines.append("     Context:")
                for sl in e.source_lines:
                    lines.append(f"       | {sl.rstrip()}")
            lines.append("")

    _section("INFRASTRUCTURE", infra)
    _section("CODE", code)
    _section("UNKNOWN", unknown)

    lines.append("=" * 60)
    return "\n".join(lines)
