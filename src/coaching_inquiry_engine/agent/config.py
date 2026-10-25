"""Conversation policy values and fixed message keys. Not UPSC facts."""

from collections.abc import Mapping
from types import MappingProxyType

IDLE_CLOSE_MINUTES = 1440
FOLLOW_UP_AFTER_MINUTES = 1440
OFF_TOPIC_LIMIT = 3
REPEATED_QUESTION_LIMIT = 2

HELPLINE_PLACEHOLDER = "{helpline_number}"

CONVERSATION_TEXTS: Mapping[str, str] = MappingProxyType(
    {
        "off_topic_redirect": (
            "[TO_APPROVE] Please return to the enrolment questions."
        ),
        "escalated": "[TO_APPROVE] A counsellor will continue this conversation.",
        "nurture": "[TO_APPROVE] We will follow up when the timing is a better fit.",
        "out_of_scope": "[TO_APPROVE] That option is not in the current offering.",
        "booking_confirmed": (
            "[TO_APPROVE] The selected slot {label} is confirmed."
        ),
        "offer_expired": (
            "[TO_APPROVE] That slot offer has expired. Fresh options will follow."
        ),
        "slot_taken": (
            "[TO_APPROVE] That slot is no longer available. Fresh options will follow."
        ),
        "slot_invalid": (
            "[TO_APPROVE] That slot cannot be booked. Fresh options will follow."
        ),
        "offers_refreshed": (
            "[TO_APPROVE] Please choose one of the updated slot options."
        ),
        "distress_support": (
            "[TO_APPROVE] Support is available. Please reach out to the helpline at "
            "{helpline_number}."
        ),
        "minor_guardian": (
            "[TO_APPROVE] A parent or guardian must be linked for enrolment. Please "
            "share your guardian's contact details."
        ),
        "scam_warning": (
            "[TO_APPROVE] For your security, our institute never requests sensitive "
            "credentials, passwords, or payment transfers in chat."
        ),
        "fee_dispute_handoff": (
            "[TO_APPROVE] A senior accounts officer will contact you directly to "
            "resolve this fee inquiry."
        ),
        "human_handoff": (
            "[TO_APPROVE] Connecting you with a human counsellor right away."
        ),
        "injection_decline": (
            "[TO_APPROVE] I can only assist with coaching and course inquiries for "
            "the institute."
        ),
        "consent_stopped": (
            "[TO_APPROVE] You have unsubscribed. We will send no further messages."
        ),
    }
)
