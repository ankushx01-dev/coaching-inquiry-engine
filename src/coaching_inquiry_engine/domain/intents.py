"""Greeting and help intent detection without external dependencies."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Intent = Literal["greeting", "help"]

_GREETINGS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hii",
        "namaste",
        "namaskar",
        "good morning",
        "good evening",
        "\u0928\u092e\u0938\u094d\u0924\u0947",
        "\u0928\u092e\u0938\u094d\u0915\u093e\u0930",
        "\u0938\u0941\u092a\u094d\u0930\u092d\u093e\u0924",
        "\u0936\u0941\u092d \u0938\u0902\u0927\u094d\u092f\u093e",
        "kaise ho",
        "kya haal",
        "ram ram",
    }
)
_HELP_REQUESTS = frozenset(
    {
        "help",
        "help me",
        "i need help",
        "what can you do",
        "how can you help",
        "madad",
        "madad karo",
        "mujhe madad chahiye",
        "help chahiye",
        "sahayata",
        "\u092e\u0926\u0926",
        "\u092e\u0926\u0926 \u0915\u0930\u0947\u0902",
        "\u092e\u0941\u091d\u0947 \u092e\u0926\u0926 \u091a\u093e\u0939\u093f\u090f",
        "\u0938\u0939\u093e\u092f\u0924\u093e",
    }
)


def detect_intent(text: str) -> Intent | None:
    normalized = _strip_punctuation_and_symbols(text)
    if normalized in _GREETINGS:
        return "greeting"
    if normalized in _HELP_REQUESTS:
        return "help"
    return None


def _strip_punctuation_and_symbols(text: str) -> str:
    kept = [
        character
        for character in text.casefold()
        if not unicodedata.category(character).startswith(("P", "S"))
    ]
    return re.sub(r"\s+", " ", "".join(kept)).strip()
