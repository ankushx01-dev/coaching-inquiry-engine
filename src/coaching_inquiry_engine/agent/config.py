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
        "off_topic_redirect": "Please return to the enrolment questions.",
        "escalated": "A counsellor will continue this conversation.",
        "nurture": "We will follow up when the timing is a better fit.",
        "out_of_scope": "That option is not in the current offering.",
        "booking_confirmed": "The selected slot {label} is confirmed.",
        "offer_expired": "That slot offer has expired. Fresh options will follow.",
        "slot_taken": "That slot is no longer available. Fresh options will follow.",
        "slot_invalid": "That slot cannot be booked. Fresh options will follow.",
        "offers_refreshed": "Please choose one of the updated slot options.",
        "ask_stage": "Which stage of preparation are you in?",
        "ask_target": "Which course or exam target interests you?",
        "ask_timeline": "When are you planning to start?",
        "ask_contact": "What is the best contact number or email?",
        "llm_fallback": "I cannot respond right now. Please try again later.",
        "distress_support": (
            "Support is available. Please reach out to the helpline at "
            "{helpline_number}."
        ),
        "minor_guardian": (
            "A parent or guardian must be linked for enrolment. Please "
            "share your guardian's contact details."
        ),
        "scam_warning": (
            "For your security, our institute never requests sensitive "
            "credentials, passwords, or payment transfers in chat."
        ),
        "fee_dispute_handoff": (
            "A senior accounts officer will contact you directly to "
            "resolve this fee inquiry."
        ),
        "human_handoff": "Connecting you with a human counsellor right away.",
        "injection_decline": (
            "I can only assist with coaching and course inquiries for "
            "the institute."
        ),
        "consent_stopped": "You have unsubscribed. We will send no further messages.",
        "greeting_welcome": (
            "Hello! I can help with {display_name} courses and UPSC preparation. "
            "What would you like to know?"
        ),
        "help_menu": (
            "You can ask about courses, fees, batch timings, demo classes, or "
            "UPSC preparation, or request a counsellor."
        ),
        "knowledge_not_found": (
            "I do not have verified information for that yet. "
            "The team will confirm it for you."
        ),
        "knowledge_stale": (
            "That information may have changed. The team will confirm it for you."
        ),
        "course_info_pending": (
            "I do not have verified course details for that exam yet. "
            "The team will confirm them for you."
        ),
        "prediction_declined": (
            "No one can predict exam results. A counsellor can explain "
            "your preparation options."
        ),
        "eligibility_ask_age": (
            "Which age band applies to you? Please choose an option below."
        ),
        "eligibility_ask_qualification": (
            "What is your highest qualification? Please choose an option below."
        ),
        "eligibility_pending": (
            "I do not have verified eligibility information for this exam yet. "
            "The team will confirm it. Please check the official notice: "
            "{official_url}"
        ),
        "category_menu_intro": "Choose an exam category to see available exams.",
        "exam_menu_intro": "Choose an exam from this category.",
        "exam_selected": "Thanks. Choose an option below for this exam.",
        "ask_name": "What name should I use when we speak with you?",
    }
)

TEXT_REVIEW_STATUS: Mapping[str, str] = MappingProxyType(
    {key: "TO_APPROVE" for key in CONVERSATION_TEXTS}
)
