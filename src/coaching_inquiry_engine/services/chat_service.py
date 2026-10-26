"""Chat ingress use cases. HTTP handlers delegate to this service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from coaching_inquiry_engine.domain.exam_menu import (
    ExamMenuFile,
    category_replies,
    exam_replies,
)
from coaching_inquiry_engine.domain.models import MessageDirection
from coaching_inquiry_engine.domain.quick_replies import QuickReply
from coaching_inquiry_engine.ports.chat_store import ChatStorePort, StoredChatMessage
from coaching_inquiry_engine.ports.rate_limiter import RateLimiterPort


class RateLimitExceededError(Exception):
    """The session or source IP exceeded its configured request limit."""


class UnknownQuickReplyActionError(ValueError):
    """The submitted quick-reply action is not currently available."""


@dataclass(frozen=True, slots=True)
class AcceptedChatMessage:
    accepted: bool
    message_id: UUID


class ChatMessageService:
    def __init__(
        self,
        store: ChatStorePort,
        rate_limiter: RateLimiterPort,
        quick_replies: tuple[QuickReply, ...] = (),
        *,
        exam_menu: ExamMenuFile | None = None,
        age_bands: tuple[str, ...] = (),
        qualification_options: tuple[str, ...] = (),
    ) -> None:
        self._store = store
        self._rate_limiter = rate_limiter
        self.quick_replies = quick_replies
        self.exam_menu = exam_menu
        self.age_bands = age_bands
        self.qualification_options = qualification_options

    async def submit(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str | None,
        action_id: str | None = None,
        consent_given: bool,
        ip_address: str,
    ) -> AcceptedChatMessage:
        if action_id is not None:
            action = next(
                (
                    reply
                    for reply in await self.quick_replies_for(session_id=session_id)
                    if reply.action_id == action_id
                ),
                None,
            )
            if action is None:
                raise UnknownQuickReplyActionError(action_id)
            text = action.send_text
        if text is None:
            raise ValueError("either text or action_id is required")
        if not self._rate_limiter.allow(session_id, ip_address):
            raise RateLimitExceededError
        message_id = await self._store.accept_message(
            session_id=session_id,
            client_message_id=client_message_id,
            text=text,
            consent_given=consent_given,
        )
        return AcceptedChatMessage(accepted=True, message_id=message_id)

    async def messages(self, *, session_id: str) -> list[StoredChatMessage]:
        messages = await self._store.list_messages(session_id)
        messages = [
            StoredChatMessage(
                message_id=message.message_id,
                direction=message.direction,
                text=(
                    self._legacy_action_label(message.text)
                    if message.direction is MessageDirection.inbound
                    else message.text
                ),
                received_at=message.received_at,
            )
            for message in messages
        ]
        return sorted(
            messages,
            key=lambda message: (message.received_at, message.message_id),
        )

    def _legacy_action_label(self, text: str) -> str:
        labels = {
            "course:batch_timings": "Batch timings",
            "course:fees": "Fees",
            "course:demo_class": "Demo class",
            "eligibility:check": "Check my eligibility",
            "category:more": "More",
            "category:back": "Back",
            "handoff:counsellor": "Talk to a counsellor",
        }
        if text in labels:
            return labels[text]
        if self.exam_menu is not None:
            if text.startswith("category:"):
                category_id = text.removeprefix("category:")
                category = next(
                    (
                        row
                        for row in self.exam_menu.categories
                        if row.category_id == category_id
                    ),
                    None,
                )
                if category is not None:
                    return category.display_name
            if text.startswith("exam:"):
                exam_id = text.removeprefix("exam:")
                exam = next(
                    (row for row in self.exam_menu.exams if row.exam_id == exam_id),
                    None,
                )
                if exam is not None:
                    return exam.display_name
        for value in (*self.age_bands, *self.qualification_options):
            if text in {f"age:{_slug(value)}", f"qualification:{_slug(value)}"}:
                return value
        return text

    async def quick_replies_for(self, *, session_id: str) -> list[QuickReply]:
        if self.exam_menu is None:
            return list(self.quick_replies)
        context_reader = getattr(self._store, "conversation_context", None)
        context = (
            await context_reader(session_id)
            if context_reader is not None
            else None
        )
        state = context or {}
        eligibility_step = state.get("eligibility_step")
        if eligibility_step == "age":
            return [
                QuickReply(
                    action_id=f"age:{_slug(value)}", label=value, send_text=value
                )
                for value in self.age_bands
            ]
        if eligibility_step == "qualification":
            return [
                QuickReply(
                    action_id=f"qualification:{_slug(value)}",
                    label=value,
                    send_text=value,
                )
                for value in self.qualification_options
            ]
        selected_exam = state.get("selected_exam")
        if isinstance(selected_exam, str):
            return [
                QuickReply(
                    action_id="course:batch_timings",
                    label="Batch timings",
                    send_text="What are the batch timings?",
                ),
                QuickReply(
                    action_id="course:fees",
                    label="Fees",
                    send_text="What are the course fees?",
                ),
                QuickReply(
                    action_id="course:demo_class",
                    label="Demo class",
                    send_text="Do you offer a demo class?",
                ),
                QuickReply(
                    action_id="eligibility:check",
                    label="Check my eligibility",
                    send_text="Check my eligibility",
                ),
                QuickReply(
                    action_id="handoff:counsellor",
                    label="Talk to a counsellor",
                    send_text="I would like to talk to a counsellor.",
                ),
            ]
        category = state.get("selected_category")
        if isinstance(category, str):
            replies = exam_replies(self.exam_menu, category)
            replies.append(("Back", "category:back"))
            return [
                QuickReply(
                    action_id=value,
                    label=label,
                    send_text=label if value != "category:back" else "Back",
                )
                for label, value in replies
            ]
        page = state.get("category_page", 0)
        category_page = page if isinstance(page, int) else 0
        return [
            QuickReply(
                action_id=value,
                label=label,
                send_text=label if value.startswith("category:") else value,
            )
            for label, value in category_replies(self.exam_menu, category_page)
        ]


def _slug(value: str) -> str:
    return "-".join(value.casefold().replace("-", " ").split())
