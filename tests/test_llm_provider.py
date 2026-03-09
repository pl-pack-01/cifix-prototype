"""Tests for LLM provider abstraction."""

from __future__ import annotations

import pytest

from cifix.llm_provider import LLMProvider, get_provider, PROVIDERS


class TestGetProvider:
    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent", api_key="fake")

    def test_known_providers_listed(self):
        assert "anthropic" in PROVIDERS
        assert "openai" in PROVIDERS
        assert "gemini" in PROVIDERS

    def test_anthropic_missing_package(self):
        """If anthropic isn't installed, get clear ImportError."""
        # This will either raise ImportError (package missing)
        # or ValueError (no API key). Both are acceptable.
        with pytest.raises((ImportError, ValueError)):
            get_provider("anthropic")

    def test_openai_missing_package(self):
        with pytest.raises((ImportError, ValueError)):
            get_provider("openai")

    def test_gemini_missing_package(self):
        with pytest.raises((ImportError, ValueError)):
            get_provider("gemini")


class TestLLMProviderInterface:
    def test_is_abstract(self):
        """LLMProvider cannot be instantiated directly."""
        with pytest.raises(TypeError):
            LLMProvider()
