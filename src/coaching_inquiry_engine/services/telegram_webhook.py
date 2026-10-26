"""Telegram update intake using the existing lead, message, consent, and job stores."""

from __future__ import annotations

from html import escape
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
from coaching_inquiry_engine.config import Settings
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.bookings import BookingRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.domain.consent import can_send_outbound
from coaching_inquiry_engine.domain.exam_menu import ExamMenuFile
from coaching_inquiry_engine.domain.flow import (
    FlowContext,
    FlowStage,
    buttons_for_stage,
)
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    Lead,
    LeadProfile,
    LeadStatus,
    MessageDirection,
)
from coaching_inquiry_engine.logging import mask_contact_text
from coaching_inquiry_engine.ports.clock import ClockPort
from coaching_inquiry_engine.ports.messenger import MessengerPort
from coaching_inquiry_engine.services.consent_service import ConsentService


class TelegramWebhookMessenger(MessengerPort, Protocol):
    async def send_consent_notice(self, recipient: str, text: str) -> None: ...

    async def answer_callback(self, callback_query_id: str) -> None: ...


class TelegramWebhookService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: ContactCipher,
        messenger: TelegramWebhookMessenger,
        settings: Settings,
        clock: ClockPort,
        exam_menu: ExamMenuFile | None = None,
        qualification_options: tuple[str, ...] = (),
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._messenger = messenger
        self._settings = settings
        self._clock = clock
        self._exam_menu = exam_menu or ExamMenuFile(categories=[], exams=[])
        self._qualification_options = qualification_options

    async def process_update(self, update: dict[str, object]) -> bool:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            raise ValueError("Telegram update_id is required")
        message = update.get("message")
        callback = update.get("callback_query")
        if not isinstance(message, dict) and not isinstance(callback, dict):
            return False

        is_agree = False
        contact_payload: dict[str, object] | None = None
        sender_user_id: str | None = None
        raw_text: str | None = None
        if isinstance(callback, dict):
            data = callback.get("data")
            if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
                raise ValueError("invalid Telegram callback_data")
            source = callback.get("message")
            if not isinstance(source, dict):
                raise ValueError("invalid Telegram callback")
            chat = source.get("chat")
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), (int, str)):
                raise ValueError("invalid Telegram callback chat")
            chat_id = str(chat["id"])
            text = data
            is_agree = data == "consent:agree"
            callback_id = callback.get("id")
        else:
            assert isinstance(message, dict)
            chat = message.get("chat")
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), (int, str)):
                raise ValueError("invalid Telegram message chat")
            chat_id = str(chat["id"])
            sender = message.get("from")
            if isinstance(sender, dict) and isinstance(sender.get("id"), (int, str)):
                sender_user_id = str(sender["id"])
            raw_value = message.get("text")
            if isinstance(raw_value, str):
                raw_text = raw_value
                text = raw_value
            else:
                contact_value = message.get("contact")
                if not isinstance(contact_value, dict):
                    return False
                contact_payload = contact_value
                text = "contact:shared"
            callback_id = None

        provider_id = f"telegram-update-{update_id}"
        timestamp = self._clock.now()
        is_message = not isinstance(callback, dict)
        should_start = is_message and text.strip().lower() == "/start"
        should_stop = is_message and text.strip().lower() == "/stop"
        consent_allowed_before = False
        send_consent_notice = False
        send_goal_prompt = False
        stale_callback = False
        ignore_contact = False
        async with self._sessions() as session:
            async with session.begin():
                leads = LeadRepository(session, self._cipher)
                lead = await leads.get_or_create_lead(ContactChannel.telegram, chat_id)
                current_context = await leads.get_conversation_context(lead.id) or {}
                flow_value = current_context.get("flow")
                flow = FlowContext.model_validate(
                    flow_value if isinstance(flow_value, dict) else {}
                )
                if isinstance(message, dict) and raw_text is not None:
                    if flow.stage in {FlowStage.contact, FlowStage.contact_manual}:
                        replies = buttons_for_stage(
                            flow,
                            qualification_options=self._qualification_options,
                            exam_menu=self._exam_menu,
                        )
                        matched = next(
                            (
                                reply
                                for reply in replies
                                if not reply.request_contact
                                and reply.label.casefold()
                                == raw_text.strip().casefold()
                            ),
                            None,
                        )
                        if matched is not None:
                            text = matched.action_id
                        elif raw_text.strip().lower() not in {"/start", "/stop"}:
                            try:
                                contact = Contact(
                                    name=flow.name or "User",
                                    channel=ContactChannel.call,
                                    value=raw_text,
                                )
                            except ValueError:
                                text = "contact:invalid"
                            else:
                                await self._persist_contact_marker(
                                    leads, lead, current_context, contact
                                )
                                text = "contact:manual_saved"
                if contact_payload is not None:
                    if flow.stage not in {FlowStage.contact, FlowStage.contact_manual}:
                        ignore_contact = True
                    else:
                        phone = contact_payload.get("phone_number")
                        owner_id = contact_payload.get("user_id")
                        if (
                            not isinstance(phone, str)
                            or not isinstance(owner_id, (int, str))
                            or sender_user_id is None
                            or str(owner_id) != sender_user_id
                        ):
                            text = "contact:invalid"
                        else:
                            try:
                                contact = Contact(
                                    name=flow.name or "User",
                                    channel=ContactChannel.call,
                                    value=phone,
                                )
                            except ValueError:
                                text = "contact:invalid"
                            else:
                                await self._persist_contact_marker(
                                    leads, lead, current_context, contact
                                )
                                text = "contact:shared"
                if isinstance(callback, dict):
                    if is_agree:
                        stale_callback = flow.stage is not FlowStage.consent
                    elif text == "contact:shared":
                        stale_callback = True
                    else:
                        offers = await BookingRepository(
                            session, commit_on_persist=False
                        ).list_active_offers(lead.id, timestamp)
                        valid_buttons = buttons_for_stage(
                            flow,
                            qualification_options=self._qualification_options,
                            exam_menu=self._exam_menu,
                            slots=tuple(
                                (offer.option_index, str(offer.start))
                                for offer in offers
                            ),
                        )
                        stale_callback = text not in {
                            button.action_id for button in valid_buttons
                        }
                consents = ConsentRepository(session)
                consent_allowed_before = await consents.latest_consent_granted(
                    lead.id, ContactChannel.telegram
                )
                messages = MessageRepository(session)
                if not stale_callback and not ignore_contact:
                    inserted = await messages.insert_message_if_new(
                        provider_id,
                        lead.id,
                        MessageDirection.inbound,
                        mask_contact_text(text),
                        timestamp,
                    )
                    if not inserted:
                        return False
                if stale_callback or ignore_contact:
                    pass
                elif should_start:
                    notice_sent = flow.consent_notice_sent
                    send_consent_notice = not consent_allowed_before and not notice_sent
                    if consent_allowed_before and flow.stage is FlowStage.consent:
                        flow = flow.model_copy(
                            update={"stage": FlowStage.goal, "updated_at": timestamp}
                        )
                        send_goal_prompt = True
                    flow = flow.model_copy(update={"consent_notice_sent": True})
                    current_context["flow"] = flow.model_dump(mode="json")
                    await leads.save_conversation_context(
                        lead.id,
                        current_context,
                        LeadProfile(
                            stage=lead.stage,
                            target=lead.target,
                            timeline=lead.timeline,
                        ),
                        LeadStatus(lead.status),
                    )
                elif should_stop:
                    await ConsentService(
                        consents, AuditRepository(session)
                    ).handle_revocation(lead.id, ContactChannel.telegram, "STOP")
                elif is_agree:
                    if flow.stage is FlowStage.consent and not consent_allowed_before:
                        await ConsentService(
                            consents, AuditRepository(session)
                        ).record_and_audit(
                            lead.id, ContactChannel.telegram, "telegram-v1"
                        )
                        await JobRepository(session).enqueue(
                            lead.id,
                            await self._inbound_message_id(messages, provider_id),
                        )
                        consent_allowed_before = True
                    else:
                        raise ValueError(
                            "consent callback is not valid for this flow stage"
                        )
                else:
                    if consent_allowed_before:
                        await JobRepository(session).enqueue(
                            lead.id,
                            await self._inbound_message_id(messages, provider_id),
                        )

        if isinstance(callback_id, str):
            await self._messenger.answer_callback(callback_id)
        if stale_callback or ignore_contact:
            return True
        if send_consent_notice:
            notice = CONVERSATION_TEXTS["telegram_consent_notice"].format(
                display_name=escape(self._settings.institute_display_name)
            )
            await self._messenger.send_consent_notice(chat_id, notice)
        elif send_goal_prompt and can_send_outbound(
            consent_allowed_before, ContactChannel.telegram.value
        ):
            await self._messenger.send_text(chat_id, CONVERSATION_TEXTS["goal_prompt"])
        elif should_stop and consent_allowed_before:
            if can_send_outbound(consent_allowed_before, ContactChannel.telegram.value):
                await self._messenger.send_text(
                    chat_id, CONVERSATION_TEXTS["consent_stopped"]
                )
        return True

    @staticmethod
    async def _persist_contact_marker(
        leads: LeadRepository,
        lead: Lead,
        context: dict[str, object],
        contact: Contact,
    ) -> None:
        """Encrypt the contact and persist only an encrypted-context marker."""
        lead_id = lead.id
        await leads.set_contact(lead_id, contact)
        profile_value = context.get("profile")
        profile = dict(profile_value) if isinstance(profile_value, dict) else {}
        profile["contact"] = {
            "name": contact.name,
            "channel": contact.channel.value,
            "value": "[ENCRYPTED]",
        }
        context["profile"] = profile
        await leads.save_conversation_context(
            lead_id,
            context,
            LeadProfile(
                stage=lead.stage,
                target=lead.target,
                timeline=lead.timeline,
            ),
            lead.status,
        )

    @staticmethod
    async def _inbound_message_id(
        messages: MessageRepository, provider_id: str
    ) -> UUID:
        row = await messages.get_by_provider_message_id(provider_id)
        if row is None:
            raise RuntimeError("inserted Telegram message was not found")
        return row.id
