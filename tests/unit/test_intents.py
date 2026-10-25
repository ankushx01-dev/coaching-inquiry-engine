"""Greeting and help intent matching across English, Hindi, and Hinglish."""

from __future__ import annotations

import pytest

from coaching_inquiry_engine.domain.intents import detect_intent


@pytest.mark.parametrize(
    "phrase",
    [
        "hi",
        "hello",
        "hey",
        "hii",
        "namaste",
        "good morning",
        "good evening",
        "नमस्ते",
        "नमस्कार",
        "सुप्रभात",
        "शुभ संध्या",
        "kaise ho",
        "kya haal",
    ],
)
def test_greetings_in_english_hindi_and_hinglish(phrase: str) -> None:
    assert detect_intent(f"{phrase}! 👋") == "greeting"


@pytest.mark.parametrize(
    "phrase",
    [
        "help",
        "help me",
        "i need help",
        "what can you do",
        "मदद",
        "मदद करें",
        "मुझे मदद चाहिए",
        "सहायता",
        "madad",
        "madad karo",
        "mujhe madad chahiye",
        "help chahiye",
    ],
)
def test_help_phrases_in_english_hindi_and_hinglish(phrase: str) -> None:
    assert detect_intent(phrase) == "help"


def test_factual_question_is_not_an_intent() -> None:
    assert detect_intent("What are the fees?") is None


def test_emoji_only_input_is_not_an_intent() -> None:
    assert detect_intent("👋🙂🙏") is None
