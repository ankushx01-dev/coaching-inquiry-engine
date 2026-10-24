"""Conversation policy values and fixed message keys. Not UPSC facts."""

from collections.abc import Mapping
from types import MappingProxyType

IDLE_CLOSE_MINUTES = 1440
FOLLOW_UP_AFTER_MINUTES = 1440
OFF_TOPIC_LIMIT = 3
REPEATED_QUESTION_LIMIT = 2

CONVERSATION_TEXTS: Mapping[str, str] = MappingProxyType(
    {
        "off_topic_redirect": (
            "[TO_APPROVE] Please return to the enrolment questions."
        ),
        "escalated": "[TO_APPROVE] A counsellor will continue this conversation.",
        "nurture": "[TO_APPROVE] We will follow up when the timing is a better fit.",
        "out_of_scope": "[TO_APPROVE] That option is not in the current offering.",
        "booking_confirmed": "[TO_APPROVE] The selected slot is confirmed.",
    }
)
