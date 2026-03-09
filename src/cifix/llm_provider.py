"""LLM provider abstraction — supports Anthropic, OpenAI, and Gemini."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for LLM providers. Each implements a simple complete() method."""

    @abstractmethod
    def complete(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt and return the LLM's text response."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Run: pip install cifix[anthropic]"
            )
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._key:
            raise ValueError(
                "Anthropic API key required. Pass --api-key or set ANTHROPIC_API_KEY."
            )
        self._client = anthropic.Anthropic(api_key=self._key)
        self._model = model

    @property
    def name(self) -> str:
        return "Anthropic"

    def complete(self, system_prompt: str, user_message: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o"):
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package not installed. Run: pip install cifix[openai]"
            )
        self._key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._key:
            raise ValueError(
                "OpenAI API key required. Pass --api-key or set OPENAI_API_KEY."
            )
        self._client = openai.OpenAI(api_key=self._key)
        self._model = model

    @property
    def name(self) -> str:
        return "OpenAI"

    def complete(self, system_prompt: str, user_message: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, model: str = "gemini-2.0-flash"):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package not installed. Run: pip install cifix[gemini]"
            )
        self._key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._key:
            raise ValueError(
                "Gemini API key required. Pass --api-key or set GEMINI_API_KEY."
            )
        genai.configure(api_key=self._key)
        self._model = genai.GenerativeModel(
            model_name=model,
            system_instruction=None,  # set per-call
        )
        self._genai = genai

    @property
    def name(self) -> str:
        return "Gemini"

    def complete(self, system_prompt: str, user_message: str) -> str:
        # Gemini uses system_instruction on the model; recreate with the prompt
        model = self._genai.GenerativeModel(
            model_name=self._model.model_name,
            system_instruction=system_prompt,
        )
        response = model.generate_content(user_message)
        return response.text


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def get_provider(name: str, api_key: str | None = None) -> LLMProvider:
    """Instantiate an LLM provider by name.

    Args:
        name: One of "anthropic", "openai", "gemini".
        api_key: Optional API key override.

    Returns:
        An initialized LLMProvider instance.
    """
    cls = PROVIDERS.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{name}'. Choose from: {', '.join(PROVIDERS)}"
        )
    return cls(api_key=api_key)
