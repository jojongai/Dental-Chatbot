"""
Gemini LLM client (google-genai SDK).

Usage
-----
Simple one-shot generation::

    from llm.gemini import generate

    reply = generate("Explain what a dental cleaning involves.")
    print(reply)

Multi-turn chat (shared history)::

    from llm.gemini import GeminiChat

    chat = GeminiChat()
    print(chat.send("What are your opening hours?"))
    print(chat.send("Do you accept Sun Life insurance?"))

Accessing the raw client (for advanced use, e.g. streaming)::

    from llm.gemini import get_client

Configuration (via .env or environment variables)
--------------------------------------------------
GEMINI_API_KEY          Required. Your Google AI Studio API key.
GEMINI_MODEL            Optional. Defaults to gemini-2.5-flash.
GEMINI_THINKING_BUDGET  Optional int. 0 = no thinking mode (default).
                        > 0 enables extended thinking for complex reasoning.
"""

from __future__ import annotations

import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

# Ensure apps/api is on sys.path so this file can be run directly.
_API_ROOT = Path(__file__).resolve().parent.parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# ruff: noqa: E402  (path manipulation must precede these imports)
from google import genai  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client initialisation — one client per process
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a configured Gemini Client. Initialised lazily on first call."""
    api_key = os.environ.get("GEMINI_API_KEY") or get_settings().gemini_api_key
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Add it to your .env file and save it.")
    return genai.Client(api_key=api_key)


def _model_name() -> str:
    return get_settings().gemini_model


def _thinking_config(budget: int) -> genai_types.ThinkingConfig | None:
    if budget > 0:
        return genai_types.ThinkingConfig(thinking_budget=budget)
    return None


# ---------------------------------------------------------------------------
# Simple one-shot helper
# ---------------------------------------------------------------------------


def generate(prompt: str, *, thinking_budget: int | None = None) -> str:
    """
    Send a single prompt and return the response text.

    Example::

        from llm.gemini import generate
        reply = generate("What does a dental cleaning involve?")
    """
    client = get_client()
    settings = get_settings()
    budget = thinking_budget if thinking_budget is not None else settings.gemini_thinking_budget

    config = None
    if budget > 0:
        config = genai_types.GenerateContentConfig(thinking_config=_thinking_config(budget))

    response = client.models.generate_content(
        model=_model_name(),
        contents=prompt,
        config=config,
    )
    return response.text


# ---------------------------------------------------------------------------
# Multi-turn chat wrapper
# ---------------------------------------------------------------------------


class GeminiChat:
    """
    Stateful multi-turn conversation backed by Gemini's chat interface.

    History is kept in memory for the lifetime of this object.

    Example::

        chat = GeminiChat(system_prompt="You are a helpful dental receptionist.")
        print(chat.send("What are your hours?"))
        print(chat.send("Do you accept Blue Cross?"))
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        thinking_budget: int | None = None,
    ) -> None:
        settings = get_settings()
        self._client = get_client()
        self._model = _model_name()
        budget = thinking_budget if thinking_budget is not None else settings.gemini_thinking_budget

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            thinking_config=_thinking_config(budget) if budget > 0 else None,
        )
        self._chat = self._client.chats.create(
            model=self._model,
            config=config,
        )

    def send(self, message: str) -> str:
        """Send a user message and return the model's text reply."""
        response = self._chat.send_message(message)
        return response.text

    @property
    def history(self) -> list:
        """Raw conversation history."""
        return self._chat.get_history()


# ---------------------------------------------------------------------------
# Smoke test — run directly to verify the connection:
#   uv run python llm/gemini.py          (from apps/api/)
#   python apps/api/llm/gemini.py        (from repo root)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Single-turn generation ===")
    print(generate("Explain what a dental cleaning involves in one sentence."))

    print("\n=== Chat ===")
    chat = GeminiChat(system_prompt="You are a friendly dental receptionist at Bright Smile Dental.")
    print("User: What are your opening hours?")
    print("Bot :", chat.send("What are your opening hours?"))
