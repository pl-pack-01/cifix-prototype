"""LLM advisor — uses an LLM provider to review ambiguous errors and generate explanations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from cifix.classifier import ClassifiedError, AnalysisResult
from cifix.llm_provider import LLMProvider
from cifix.patterns import ErrorCategory, ErrorSeverity

logger = logging.getLogger(__name__)

MAX_ERRORS_PER_CALL = 10

_REVIEW_SYSTEM = """\
You are an expert CI/CD engineer. You will receive CI log errors that could not \
be confidently classified by a regex-based classifier. For each error, determine:

1. category: "infrastructure" (pipeline/environment problem) or "code" (problem in the code being built/tested)
2. error_type: a short snake_case label (e.g. "missing_dependency", "flaky_test")
3. confidence: 0.0-1.0 how confident you are in the classification
4. suggestion: one-sentence actionable fix suggestion

Respond with ONLY a JSON array, one object per error. Example:
[{"category": "code", "error_type": "missing_dependency", "confidence": 0.85, "suggestion": "Add requests to requirements.txt."}]
"""

_EXPLAIN_SYSTEM = """\
You are a helpful CI/CD assistant. For each classified CI error, write a brief \
plain-English explanation (1-3 sentences) that a developer can quickly understand. \
Cover: what went wrong, the likely cause, and what to do about it.

Respond with ONLY a JSON array of strings, one explanation per error. Example:
["The test failed because...", "The Docker build could not find..."]
"""


@dataclass
class LLMAdvisorResult:
    """Outcome of an LLM advisory pass."""
    reviewed_count: int = 0
    explained_count: int = 0
    provider_name: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "reviewed_count": self.reviewed_count,
            "explained_count": self.explained_count,
            "provider_name": self.provider_name,
            "errors": self.errors,
        }


class LLMAdvisor:
    """Uses an LLM provider to review low-confidence errors and add explanations."""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def review_errors(self, errors: list[ClassifiedError]) -> LLMAdvisorResult:
        """Re-classify errors where needs_llm_review is True.

        Updates the errors in-place with new category, confidence, etc.
        Returns metadata about the review.
        """
        result = LLMAdvisorResult(provider_name=self.provider.name)
        to_review = [e for e in errors if e.needs_llm_review]

        if not to_review:
            return result

        # Cap per-call to control cost
        batch = to_review[:MAX_ERRORS_PER_CALL]

        user_msg = self._build_review_prompt(batch)
        try:
            raw = self.provider.complete(_REVIEW_SYSTEM, user_msg)
            reviews = self._parse_json_array(raw)
        except Exception as exc:
            logger.warning("LLM review failed: %s", exc)
            result.errors.append(str(exc))
            return result

        for err, review in zip(batch, reviews):
            if not isinstance(review, dict):
                continue
            cat = review.get("category", "")
            if cat == "infrastructure":
                err.category = ErrorCategory.INFRASTRUCTURE
            elif cat == "code":
                err.category = ErrorCategory.CODE
            err.error_type = review.get("error_type", err.error_type)
            err.confidence = float(review.get("confidence", err.confidence))
            err.suggestion = review.get("suggestion", err.suggestion)
            err.needs_llm_review = False
            result.reviewed_count += 1

        return result

    def explain_errors(self, errors: list[ClassifiedError]) -> LLMAdvisorResult:
        """Generate plain-English explanations for errors. Updates errors in-place."""
        result = LLMAdvisorResult(provider_name=self.provider.name)

        if not errors:
            return result

        batch = errors[:MAX_ERRORS_PER_CALL]
        user_msg = self._build_explain_prompt(batch)

        try:
            raw = self.provider.complete(_EXPLAIN_SYSTEM, user_msg)
            explanations = self._parse_json_array(raw)
        except Exception as exc:
            logger.warning("LLM explain failed: %s", exc)
            result.errors.append(str(exc))
            return result

        for err, explanation in zip(batch, explanations):
            if isinstance(explanation, str):
                err.explanation = explanation
                result.explained_count += 1

        return result

    # -- Prompt builders ------------------------------------------------------

    @staticmethod
    def _build_review_prompt(errors: list[ClassifiedError]) -> str:
        items = []
        for i, e in enumerate(errors, 1):
            items.append(
                f"{i}. [{e.category.value}] error_type={e.error_type} "
                f"confidence={e.confidence:.2f}\n"
                f"   Summary: {e.summary}\n"
                f"   Step: {e.step_name}\n"
                f"   Context: {' | '.join(e.source_lines[:3])}"
            )
        return "Classify these CI errors:\n\n" + "\n\n".join(items)

    @staticmethod
    def _build_explain_prompt(errors: list[ClassifiedError]) -> str:
        items = []
        for i, e in enumerate(errors, 1):
            items.append(
                f"{i}. [{e.category.value}/{e.severity.value}] {e.error_type}: {e.summary}"
            )
        return "Explain these CI errors:\n\n" + "\n".join(items)

    @staticmethod
    def _parse_json_array(raw: str) -> list:
        """Extract a JSON array from LLM output, tolerating markdown fences."""
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        # Try to find a JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse LLM response as JSON array")
        return []


def recompute_verdict(result: AnalysisResult) -> None:
    """Recompute verdict and counts after LLM reclassification. Mutates in place."""
    infra = sum(1 for e in result.errors if e.category == ErrorCategory.INFRASTRUCTURE)
    code = sum(1 for e in result.errors if e.category == ErrorCategory.CODE)
    low_conf = sum(1 for e in result.errors if e.needs_llm_review)
    unknown = sum(1 for e in result.errors if e.category == ErrorCategory.UNKNOWN)

    result.infra_count = infra
    result.code_count = code
    result.low_confidence_count = low_conf
    result.unknown_count = unknown

    if infra and code:
        result.verdict = "both"
    elif infra:
        result.verdict = "infrastructure"
    elif code:
        result.verdict = "code"
    else:
        result.verdict = "clean"
