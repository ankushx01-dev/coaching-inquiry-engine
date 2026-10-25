"""Background worker for the chat message pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.llm_ollama import OllamaLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.agent.conversation import (
    AskField,
    CloseConversation,
    ConversationAction,
    ConversationContext,
    InboundMessage,
    NotifyStaff,
    OfferSlots,
    SendText,
    handle_event,
    resolve_text,
)
from coaching_inquiry_engine.config import get_settings
from coaching_inquiry_engine.db.encryption import ContactCipher
from coaching_inquiry_engine.db.models import JobRow
from coaching_inquiry_engine.db.repositories.audits import AuditRepository
from coaching_inquiry_engine.db.repositories.bookings import BookingRepository
from coaching_inquiry_engine.db.repositories.consents import ConsentRepository
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.db.repositories.outbox import OutboxRepository
from coaching_inquiry_engine.db.session import create_engine, create_session_factory
from coaching_inquiry_engine.domain.config import (
    BOOKING_TZ,
    OFFERED_TARGETS,
    PROMPT_VERSION,
)
from coaching_inquiry_engine.domain.consent import can_send_outbound
from coaching_inquiry_engine.domain.decisions import (
    AgentDecision,
    FieldUpdates,
    NextAction,
    SlotOption,
)
from coaching_inquiry_engine.domain.models import (
    Contact,
    ContactChannel,
    LeadProfile,
    LeadStatus,
    MessageDirection,
    QualifyFlags,
    Target,
)
from coaching_inquiry_engine.domain.qualify import qualify
from coaching_inquiry_engine.domain.safety import (
    SafetyKeywords,
    detect_triggers,
    plan_response,
)
from coaching_inquiry_engine.domain.slots import format_slot_label
from coaching_inquiry_engine.logging import mask_contact_text
from coaching_inquiry_engine.ports.calendar import CalendarPort
from coaching_inquiry_engine.ports.clock import ClockPort
from coaching_inquiry_engine.ports.llm import DecisionContext, LlmPort, SanitizedMessage
from coaching_inquiry_engine.ports.messenger import MessengerPort
from coaching_inquiry_engine.services.booking_service import BookingService
from coaching_inquiry_engine.services.escalation_service import (
    StaffAlertPayload,
    build_staff_payload,
)
from coaching_inquiry_engine.services.job_retry import retry_at
from coaching_inquiry_engine.services.llm_guard import LLMUnavailable, decide_safely
from coaching_inquiry_engine.services.safety_keywords import load_safety_keywords


@dataclass(frozen=True, slots=True)
class TurnResult:
    context: ConversationContext
    status: LeadStatus
    text_keys: list[str]
    stored_texts: list[str]
    llm_unavailable: bool
    staff_alert_payload: StaffAlertPayload | None


class Worker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        cipher: ContactCipher,
        llm: LlmPort,
        messenger: MessengerPort,
        keywords: SafetyKeywords,
        calendar: CalendarPort,
        *,
        offered_targets: frozenset[Target] = OFFERED_TARGETS,
        llm_max_attempts: int = 3,
        job_max_attempts: int = 5,
        clock: ClockPort | None = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._llm = llm
        self._messenger = messenger
        self._keywords = keywords
        self._calendar = calendar
        self._offered_targets = offered_targets
        self._llm_max_attempts = llm_max_attempts
        self._job_max_attempts = job_max_attempts
        self._clock = clock or SystemClock()

    async def process_turn(
        self,
        *,
        lead_id: UUID,
        recipient: str,
        inbound_text: str,
        context: ConversationContext,
        prior_messages: list[SanitizedMessage],
        consent_granted: bool,
        slot_options: list[SlotOption],
        now: datetime,
        booking_service: BookingService | None = None,
    ) -> TurnResult:
        detected_flags = detect_triggers(inbound_text, self._keywords)
        decision: AgentDecision | None
        llm_unavailable = False
        messages = list(prior_messages[-9:])
        if (
            not messages
            or messages[-1].role != "user"
            or messages[-1].text != inbound_text
        ):
            messages.append(SanitizedMessage(role="user", text=inbound_text))
        decision_context = DecisionContext(
            messages=messages[-10:],
            profile=_field_updates(context.profile),
            allowed_next_actions=list(NextAction),
            slot_options=slot_options,
        )
        try:
            decision = await decide_safely(
                self._llm,
                decision_context,
                max_attempts=self._llm_max_attempts,
            )
        except LLMUnavailable:
            decision = None
            llm_unavailable = True

        extracted = _decision_profile_updates(context.profile, decision)
        merged_profile = _merge_profile(context.profile, extracted)
        merged_flags = _merge_flags(context.flags, detected_flags)
        status = qualify(merged_profile, merged_flags, self._offered_targets)
        event = InboundMessage(
            text=inbound_text,
            extracted_fields=extracted,
            detected_flags=detected_flags,
            is_off_topic=(
                decision is not None
                and decision.next_action is NextAction.redirect_off_topic
            ),
        )
        new_context, actions = handle_event(
            context, event, self._offered_targets, now
        )
        staff_action = next(
            (action for action in actions if isinstance(action, NotifyStaff)), None
        )
        staff_alert_payload = (
            build_staff_payload(
                lead_id=lead_id,
                status=staff_action.status,
                reason=staff_action.reason,
                messages=[message.text for message in messages],
                flags=new_context.flags,
            )
            if staff_action is not None
            else None
        )

        booking_result_key: str | None = None
        booking_label: str | None = None
        if (
            decision is not None
            and decision.booking_choice_index is not None
            and not any(detected_flags.model_dump().values())
        ):
            if booking_service is None:
                raise RuntimeError("booking service is required for a booking choice")
            booking_result = await booking_service.book_offer(
                lead_id, decision.booking_choice_index, now
            )
            booking_result_key = booking_result.text_key
            booking_label = booking_result.label

        if any(detected_flags.model_dump().values()):
            plan = plan_response(detected_flags)
            text_keys = [plan.text_key] if plan.text_key is not None else []
        elif llm_unavailable:
            text_keys = ["llm_fallback"]
        elif booking_result_key is not None:
            text_keys = [booking_result_key]
        else:
            text_keys = _text_keys_from_actions(actions)

        if booking_result_key is None and any(
            isinstance(action, OfferSlots) for action in actions
        ) and booking_service is not None:
            await booking_service.create_offers(lead_id, now)

        stored_texts: list[str] = []
        if self._can_send(consent_granted):
            for key in dict.fromkeys(text_keys):
                action = SendText(text_key=key)
                placeholders = (
                    {"label": booking_label}
                    if action.text_key == "booking_confirmed" and booking_label
                    else {}
                )
                text = resolve_text(action.text_key, **placeholders)
                await self._messenger.send_text(recipient, text)
                stored_texts.append(mask_contact_text(text))

        return TurnResult(
            context=new_context,
            status=status,
            text_keys=text_keys,
            stored_texts=stored_texts,
            llm_unavailable=llm_unavailable,
            staff_alert_payload=staff_alert_payload,
        )

    async def run_once(self) -> bool:
        job_id: UUID | None = None
        claimed_attempt = 1
        now = self._clock.now()
        try:
            async with self._sessions() as session:
                async with session.begin():
                    jobs = JobRepository(session)
                    job = await jobs.claim_next(now)
                    if job is None:
                        return False
                    job_id = job.id
                    claimed_attempt = job.attempts
                    await self._process_job(session, job, now)
                    await jobs.mark_done(job.id, now)
            return True
        except Exception as exc:
            if job_id is None:
                raise
            failed_at = self._clock.now()
            async with self._sessions() as session:
                async with session.begin():
                    await JobRepository(session).mark_failed(
                        job_id,
                        error=type(exc).__name__,
                        now=failed_at,
                        max_attempts=self._job_max_attempts,
                        next_attempt_at=retry_at(failed_at, claimed_attempt),
                    )
            return True

    async def _process_job(
        self, session: AsyncSession, job: JobRow, now: datetime
    ) -> None:
        leads = LeadRepository(session, self._cipher)
        lead = await leads.get_by_id(job.lead_id)
        if lead is None:
            raise KeyError(f"lead {job.lead_id} not found")
        message_repo = MessageRepository(session)
        inbound = await message_repo.get_by_id(job.inbound_message_id)
        if inbound is None:
            raise KeyError(f"inbound message {job.inbound_message_id} not found")
        context_payload = await leads.get_conversation_context(lead.id) or {}
        await self._hydrate_contact(context_payload, lead.id, leads)
        context = ConversationContext.model_validate(context_payload)

        rows = await message_repo.list_recent(lead.id, limit=10)
        prior_messages = [
            SanitizedMessage(
                role=(
                    "user"
                    if row.direction == MessageDirection.inbound.value
                    else "assistant"
                ),
                text=mask_contact_text(row.body),
            )
            for row in rows
        ]
        bookings = BookingRepository(session, commit_on_persist=False)
        active_offers = await bookings.list_active_offers(lead.id, now)
        slot_options = [
            SlotOption(
                index=offer.option_index,
                label=format_slot_label(offer.start, BOOKING_TZ),
            )
            for offer in active_offers
        ]
        consent_granted = await ConsentRepository(session).latest_consent_granted(
            lead.id, ContactChannel.chat
        )
        booking_service = BookingService(self._calendar, bookings)
        result = await self.process_turn(
            lead_id=lead.id,
            recipient=lead.external_user_id,
            inbound_text=mask_contact_text(inbound.body),
            context=context,
            prior_messages=prior_messages,
            consent_granted=consent_granted,
            slot_options=slot_options,
            now=now,
            booking_service=booking_service,
        )
        await self._persist_context_and_staff_alert(
            session=session,
            leads=leads,
            lead_id=lead.id,
            result=result,
            now=now,
        )
        for index, text in enumerate(result.stored_texts):
            await message_repo.insert_message_if_new(
                f"worker-{job.id}-{index}",
                lead.id,
                MessageDirection.outbound,
                text,
                now,
            )
        await AuditRepository(session).append_audit_event(
            lead_id=lead.id,
            event_type="chat_turn_processed",
            detail={
                "job_id": str(job.id),
                "message_id": str(inbound.id),
                "status": result.status.value,
                "outbound_count": len(result.stored_texts),
                "llm_fallback": result.llm_unavailable,
            },
            prompt_version=PROMPT_VERSION,
        )

    async def _hydrate_contact(
        self,
        context: dict[str, object],
        lead_id: UUID,
        leads: LeadRepository,
    ) -> None:
        profile = context.get("profile")
        if not isinstance(profile, dict):
            return
        contact = profile.get("contact")
        if not isinstance(contact, dict) or contact.get("value") != "[ENCRYPTED]":
            return
        value = await leads.get_decrypted_contact_value(lead_id)
        if value is None:
            profile["contact"] = None
        else:
            contact["value"] = value

    @staticmethod
    async def _persist_context_and_staff_alert(
        *,
        session: AsyncSession,
        leads: LeadRepository,
        lead_id: UUID,
        result: TurnResult,
        now: datetime,
    ) -> None:
        await leads.save_conversation_context(
            lead_id,
            result.context.model_dump(mode="json"),
            result.context.profile,
            result.status,
        )
        if result.staff_alert_payload is not None:
            await OutboxRepository.enqueue_in_session(
                session,
                lead_id=lead_id,
                target="staff_alert",
                payload=result.staff_alert_payload.model_dump(mode="json"),
                available_at=now,
            )

    @staticmethod
    def _can_send(consent_granted: bool) -> bool:
        return can_send_outbound(consent_granted, ContactChannel.chat.value)


def _field_updates(profile: LeadProfile) -> FieldUpdates:
    return FieldUpdates(
        stage=profile.stage,
        target=profile.target,
        timeline=profile.timeline,
        contact_name=profile.contact.name if profile.contact is not None else None,
    )


def _decision_profile_updates(
    profile: LeadProfile, decision: AgentDecision | None
) -> LeadProfile:
    if decision is None:
        return LeadProfile()
    fields = decision.field_updates
    contact = profile.contact
    if contact is not None and fields.contact_name is not None:
        contact = Contact(
            name=fields.contact_name,
            channel=contact.channel,
            value=contact.value,
        )
    return LeadProfile(
        stage=fields.stage,
        target=fields.target,
        timeline=fields.timeline,
        contact=contact,
    )


def _merge_profile(base: LeadProfile, extracted: LeadProfile) -> LeadProfile:
    return LeadProfile(
        stage=base.stage if extracted.stage is None else extracted.stage,
        target=base.target if extracted.target is None else extracted.target,
        timeline=base.timeline if extracted.timeline is None else extracted.timeline,
        contact=base.contact if extracted.contact is None else extracted.contact,
    )


def _merge_flags(base: QualifyFlags, detected: QualifyFlags) -> QualifyFlags:
    return QualifyFlags(
        **{
            name: getattr(base, name) or getattr(detected, name)
            for name in QualifyFlags.model_fields
        }
    )


def _text_keys_from_actions(actions: list[ConversationAction]) -> list[str]:
    keys: list[str] = []
    for action in actions:
        if isinstance(action, SendText):
            keys.append(action.text_key)
        elif isinstance(action, AskField):
            keys.append(f"ask_{action.field.value}")
        elif isinstance(action, OfferSlots):
            keys.append("offers_refreshed")
        elif isinstance(action, NotifyStaff):
            keys.append("escalated")
        elif isinstance(action, CloseConversation):
            continue
    return keys


async def run_worker() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    cipher = ContactCipher.from_settings(settings)
    worker = Worker(
        sessions,
        cipher,
        OllamaLlmAdapter(settings),
        FakeMessenger(),
        load_safety_keywords(),
        FakeCalendar(),
        llm_max_attempts=settings.llm_max_attempts,
        job_max_attempts=settings.job_max_attempts,
        clock=SystemClock(),
    )
    try:
        while True:
            if not await worker.run_once():
                await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
