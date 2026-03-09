"""Tests for LLM advisor — uses mocked providers to avoid real API calls."""

from __future__ import annotations

import json

import pytest

from cifix.classifier import ClassifiedError, AnalysisResult
from cifix.llm_advisor import LLMAdvisor, recompute_verdict
from cifix.llm_provider import LLMProvider
from cifix.patterns import ErrorCategory, ErrorSeverity


# -- Mock provider ---------------------------------------------------------

class MockProvider(LLMProvider):
    """A fake LLM provider that returns canned responses."""

    def __init__(self, response: str = "[]"):
        self._response = response
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return "MockLLM"

    def complete(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((system_prompt, user_message))
        return self._response


class FailingProvider(LLMProvider):
    """A provider that always raises."""

    @property
    def name(self) -> str:
        return "FailingLLM"

    def complete(self, system_prompt: str, user_message: str) -> str:
        raise RuntimeError("API is down")


# -- Helpers ---------------------------------------------------------------

def _make_error(
    category=ErrorCategory.UNKNOWN,
    error_type="unmatched_error",
    summary="something failed",
    confidence=0.2,
    needs_llm_review=True,
) -> ClassifiedError:
    return ClassifiedError(
        category=category,
        error_type=error_type,
        summary=summary,
        severity=ErrorSeverity.WARNING,
        source_lines=["line before", "something failed", "line after"],
        step_name="Run tests",
        suggestion="Unknown error.",
        match_text="something failed",
        confidence=confidence,
        needs_llm_review=needs_llm_review,
    )


# -- review_errors ---------------------------------------------------------

class TestReviewErrors:
    def test_reviews_low_confidence_errors(self):
        response = json.dumps([{
            "category": "code",
            "error_type": "missing_dependency",
            "confidence": 0.85,
            "suggestion": "Add flask to requirements.txt.",
        }])
        provider = MockProvider(response)
        advisor = LLMAdvisor(provider)

        err = _make_error()
        result = advisor.review_errors([err])

        assert result.reviewed_count == 1
        assert err.category == ErrorCategory.CODE
        assert err.error_type == "missing_dependency"
        assert err.confidence == 0.85
        assert err.needs_llm_review is False

    def test_skips_high_confidence(self):
        provider = MockProvider("[]")
        advisor = LLMAdvisor(provider)

        err = _make_error(
            category=ErrorCategory.CODE,
            confidence=0.95,
            needs_llm_review=False,
        )
        result = advisor.review_errors([err])

        assert result.reviewed_count == 0
        assert len(provider.calls) == 0  # no API call made

    def test_handles_infra_reclassification(self):
        response = json.dumps([{
            "category": "infrastructure",
            "error_type": "runner_oom",
            "confidence": 0.90,
            "suggestion": "Increase runner memory.",
        }])
        provider = MockProvider(response)
        advisor = LLMAdvisor(provider)

        err = _make_error()
        advisor.review_errors([err])

        assert err.category == ErrorCategory.INFRASTRUCTURE

    def test_graceful_degradation_on_failure(self):
        provider = FailingProvider()
        advisor = LLMAdvisor(provider)

        err = _make_error()
        original_category = err.category
        result = advisor.review_errors([err])

        # Error unchanged, advisory result reports the failure
        assert err.category == original_category
        assert result.reviewed_count == 0
        assert len(result.errors) == 1
        assert "API is down" in result.errors[0]

    def test_handles_malformed_response(self):
        provider = MockProvider("this is not json at all")
        advisor = LLMAdvisor(provider)

        err = _make_error()
        result = advisor.review_errors([err])

        assert result.reviewed_count == 0

    def test_handles_markdown_fenced_response(self):
        inner = json.dumps([{
            "category": "code",
            "error_type": "test_failure",
            "confidence": 0.80,
            "suggestion": "Fix the test.",
        }])
        response = f"```json\n{inner}\n```"
        provider = MockProvider(response)
        advisor = LLMAdvisor(provider)

        err = _make_error()
        result = advisor.review_errors([err])

        assert result.reviewed_count == 1
        assert err.error_type == "test_failure"

    def test_empty_error_list(self):
        provider = MockProvider("[]")
        advisor = LLMAdvisor(provider)

        result = advisor.review_errors([])
        assert result.reviewed_count == 0
        assert len(provider.calls) == 0


# -- explain_errors --------------------------------------------------------

class TestExplainErrors:
    def test_generates_explanations(self):
        response = json.dumps([
            "The test failed because the assertion expected 42 but got 41.",
        ])
        provider = MockProvider(response)
        advisor = LLMAdvisor(provider)

        err = _make_error(needs_llm_review=False)
        result = advisor.explain_errors([err])

        assert result.explained_count == 1
        assert "42" in err.explanation

    def test_graceful_degradation(self):
        provider = FailingProvider()
        advisor = LLMAdvisor(provider)

        err = _make_error()
        result = advisor.explain_errors([err])

        assert result.explained_count == 0
        assert err.explanation == ""

    def test_empty_list(self):
        provider = MockProvider("[]")
        advisor = LLMAdvisor(provider)

        result = advisor.explain_errors([])
        assert result.explained_count == 0


# -- recompute_verdict -----------------------------------------------------

class TestRecomputeVerdict:
    def test_recomputes_after_reclassification(self):
        errors = [
            _make_error(category=ErrorCategory.INFRASTRUCTURE, needs_llm_review=False),
            _make_error(category=ErrorCategory.CODE, needs_llm_review=False),
        ]
        result = AnalysisResult(errors=errors, verdict="clean")

        recompute_verdict(result)

        assert result.verdict == "both"
        assert result.infra_count == 1
        assert result.code_count == 1

    def test_clean_when_only_unknown(self):
        errors = [_make_error(category=ErrorCategory.UNKNOWN)]
        result = AnalysisResult(errors=errors, verdict="code")

        recompute_verdict(result)

        assert result.verdict == "clean"
        assert result.unknown_count == 1
