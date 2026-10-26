"""Background worker for the chat message pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from coaching_inquiry_engine.adapters.calendar_fake import FakeCalendar
from coaching_inquiry_engine.adapters.clock import SystemClock
from coaching_inquiry_engine.adapters.llm_ollama import OllamaLlmAdapter
from coaching_inquiry_engine.adapters.messenger_fake import FakeMessenger
from coaching_inquiry_engine.adapters.messenger_telegram import TelegramMessenger
from coaching_inquiry_engine.agent.answering import answer_message
from coaching_inquiry_engine.agent.config import CONVERSATION_TEXTS
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
from coaching_inquiry_engine.db.repositories.counselling_requests import (
    CounsellingRequestRepository,
)
from coaching_inquiry_engine.db.repositories.jobs import JobRepository
from coaching_inquiry_engine.db.repositories.leads import LeadRepository
from coaching_inquiry_engine.db.repositories.messages import MessageRepository
from coaching_inquiry_engine.db.repositories.outbox import OutboxRepository
from coaching_inquiry_engine.db.session import create_engine, create_session_factory
from coaching_inquiry_engine.domain.chat_routing import (
    extract_name,
    is_human_request,
    is_prediction_question,
    normalize_chat_text,
    parse_stage,
    parse_target,
    parse_timeline,
)
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
from coaching_inquiry_engine.domain.exam_menu import Exam, ExamMenuFile, load_exam_menu
from coaching_inquiry_engine.domain.flow import (
    EligibilityStatus,
    FlowStage,
    buttons_for_stage,
    evaluate_eligibility,
    expected_input,
)
from coaching_inquiry_engine.domain.flow import (
    transition as transition_flow,
)
from coaching_inquiry_engine.domain.knowledge import (
    CourseInfoEntry,
    KnowledgeEntry,
    load_knowledge,
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
from coaching_inquiry_engine.domain.quick_replies import QuickReply
from coaching_inquiry_engine.domain.safety import (
    SafetyKeywords,
    detect_triggers,
    plan_response,
)
from coaching_inquiry_engine.domain.slots import format_slot_label
from coaching_inquiry_engine.domain.sources import SourceEntry, load_sources
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
    counselling_request_requested: bool = False


@dataclass(frozen=True, slots=True)
class _RoutedReply:
    text_key: str | None = None
    reply_text: str | None = None
    context_updates: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _DeferredTelegramMessage:
    recipient: str
    text: str
    quick_replies: tuple[QuickReply, ...]


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
        knowledge: tuple[KnowledgeEntry, ...] = (),
        topic_keywords: dict[str, list[str]] | None = None,
        knowledge_max_age_days: int = 30,
        answering_enabled: bool = False,
        source_registry: dict[str, SourceEntry] | None = None,
        exam_menu: ExamMenuFile | None = None,
        courses: dict[str, dict[str, CourseInfoEntry | str]] | None = None,
        age_bands: tuple[str, ...] = (
            "under 18",
            "18-21",
            "22-25",
            "26-30",
            "above 30",
        ),
        qualification_options: tuple[str, ...] = (
            "Class 10",
            "Class 12",
            "Diploma",
            "Undergraduate",
            "Graduate",
            "Postgraduate",
        ),
        display_name: str = "coaching-enquiry",
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
        self._knowledge = knowledge
        self._topic_keywords = topic_keywords or {}
        self._knowledge_max_age_days = knowledge_max_age_days
        self._answering_enabled = answering_enabled
        self._source_registry = source_registry or {}
        self._exam_menu = exam_menu
        self._courses = courses or {}
        self._age_bands = age_bands
        self._qualification_options = qualification_options
        self._display_name = display_name

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
        channel: ContactChannel = ContactChannel.chat,
    ) -> TurnResult:
        detected_flags = detect_triggers(inbound_text, self._keywords)
        if inbound_text == "handoff:counsellor":
            detected_flags = detected_flags.model_copy(update={"human_request": True})
        if (
            is_human_request(inbound_text)
            and not detected_flags.human_request
            and not detected_flags.injection_attempt
        ):
            detected_flags = detected_flags.model_copy(update={"human_request": True})
        has_safety_or_handoff = any(detected_flags.model_dump().values())
        if channel is ContactChannel.telegram and not has_safety_or_handoff:
            return await self._process_telegram_flow_turn(
                lead_id=lead_id,
                recipient=recipient,
                text=inbound_text,
                context=context,
                prior_messages=prior_messages,
                consent_granted=consent_granted,
                now=now,
                booking_service=booking_service,
                slot_options=slot_options,
            )
        extracted_name = None if has_safety_or_handoff else extract_name(inbound_text)
        parsed_fields = _parse_open_question(context, inbound_text)
        routed = (
            None
            if has_safety_or_handoff or parsed_fields is not None or extracted_name
            else self._route_deterministic(inbound_text, context)
        )
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
        answering_result = None
        skip_llm = (
            has_safety_or_handoff
            or parsed_fields is not None
            or extracted_name is not None
            or routed is not None
        )
        if skip_llm:
            decision = None
        elif self._answering_enabled:
            try:
                answering_result = await answer_message(
                    inbound_text,
                    llm=self._llm,
                    context=decision_context,
                    knowledge=self._knowledge,
                    topic_keywords=self._topic_keywords,
                    source_registry=self._source_registry,
                    max_age_days=self._knowledge_max_age_days,
                    today=now.date(),
                    max_attempts=self._llm_max_attempts,
                )
                decision = answering_result.decision
            except LLMUnavailable:
                decision = None
                llm_unavailable = True
        else:
            try:
                decision = await decide_safely(
                    self._llm,
                    decision_context,
                    max_attempts=self._llm_max_attempts,
                )
            except LLMUnavailable:
                decision = None
                llm_unavailable = True

        extracted = (
            parsed_fields
            if parsed_fields is not None
            else _decision_profile_updates(context.profile, decision)
        )
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
            extracted_name=extracted_name,
        )
        if routed is not None:
            context_updates: dict[str, object] = {
                "message_count": context.message_count + 1
            }
            context_updates.update(routed.context_updates or {})
            new_context = context.model_copy(update=context_updates)
            actions: list[ConversationAction] = []
        else:
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

        if has_safety_or_handoff:
            plan = plan_response(detected_flags)
            text_keys = [plan.text_key] if plan.text_key is not None else []
        elif routed is not None and routed.text_key is not None:
            text_keys = [routed.text_key]
        elif routed is not None:
            text_keys = []
        elif answering_result is not None and answering_result.text_key is not None:
            text_keys = [answering_result.text_key]
        elif llm_unavailable:
            text_keys = [
                "llm_unavailable_follow_up"
                if channel is ContactChannel.telegram
                else "llm_fallback"
            ]
        elif booking_result_key is not None:
            text_keys = [booking_result_key]
        else:
            text_keys = _text_keys_from_actions(actions)

        if (
            booking_result_key is None
            and any(isinstance(action, OfferSlots) for action in actions)
            and booking_service is not None
        ):
            await booking_service.create_offers(lead_id, now)

        stored_texts: list[str] = []
        if self._can_send(consent_granted, channel):
            quick_replies = (
                self._buttons_for_context(new_context, slot_options)
                if channel is ContactChannel.telegram
                else ()
            )
            for key in dict.fromkeys(text_keys):
                action = SendText(text_key=key)
                placeholders: dict[str, str] = {}
                if action.text_key == "greeting_welcome":
                    placeholders["display_name"] = self._display_name
                if action.text_key == "booking_confirmed" and booking_label:
                    placeholders["label"] = booking_label
                if action.text_key == "eligibility_pending":
                    selected_exam = new_context.selected_exam
                    if selected_exam is None:
                        raise RuntimeError("eligibility response has no selected exam")
                    placeholders = {
                        "official_url": str(
                            self._get_exam(selected_exam).official_notice_url
                        )
                    }
                text = resolve_text(action.text_key, **placeholders)
                await self._messenger.send_text(recipient, text, quick_replies)
                stored_texts.append(mask_contact_text(text))
            if routed is not None and routed.reply_text is not None:
                await self._messenger.send_text(
                    recipient, routed.reply_text, quick_replies
                )
                stored_texts.append(mask_contact_text(routed.reply_text))
            if (
                answering_result is not None
                and decision is not None
                and decision.next_action is NextAction.answer_question
            ):
                await self._messenger.send_text(
                    recipient, decision.reply_text, quick_replies
                )
                stored_texts.append(mask_contact_text(decision.reply_text))

        return TurnResult(
            context=new_context,
            status=status,
            text_keys=text_keys,
            stored_texts=stored_texts,
            llm_unavailable=llm_unavailable,
            staff_alert_payload=staff_alert_payload,
        )

    async def _process_telegram_flow_turn(
        self,
        *,
        lead_id: UUID,
        recipient: str,
        text: str,
        context: ConversationContext,
        prior_messages: list[SanitizedMessage],
        consent_granted: bool,
        now: datetime,
        booking_service: BookingService | None,
        slot_options: list[SlotOption],
    ) -> TurnResult:
        flow = context.flow
        status = qualify(context.profile, context.flags, self._offered_targets)
        if flow.stage is FlowStage.closed:
            return TurnResult(context, status, [], [], False, None)

        action_value = text.strip()
        stage_input = expected_input(flow.stage)
        is_question = "?" in action_value or action_value.casefold().startswith(
            (
                "what ",
                "how ",
                "why ",
                "can ",
                "could ",
                "tell me ",
                "\u0915\u094d\u092f\u093e",
            )
        )
        is_action = ":" in action_value and not is_question
        if stage_input is not None and not is_action and is_question:
            return await self._answer_telegram_free_text(
                recipient=recipient,
                text=action_value,
                context=context,
                prior_messages=prior_messages,
                consent_granted=consent_granted,
                now=now,
                status=status,
            )
        if stage_input.value == "button" and not is_action:
            return await self._answer_telegram_free_text(
                recipient=recipient,
                text=action_value,
                context=context,
                prior_messages=prior_messages,
                consent_granted=consent_granted,
                now=now,
                status=status,
            )

        transition = transition_flow(
            flow,
            value=action_value,
            now=now,
            qualification_options=self._qualification_options,
            exam_menu=self._exam_menu or ExamMenuFile(categories=[], exams=[]),
        )
        updated_flow = transition.context
        text_key = transition.text_key
        reply_text = transition.text
        counselling_request_requested = False
        slots: tuple[tuple[int, str], ...] = tuple(
            (option.index, option.label) for option in slot_options
        )
        if transition.action == "check_eligibility":
            if flow.exam_id is None:
                raise RuntimeError("eligibility check has no selected exam")
            exam = self._get_exam(flow.exam_id)
            summaries = tuple(
                source.answer_summary
                for source in self._source_registry.values()
                if source.exam_id == flow.exam_id
                and source.status == "VERIFIED"
                and source.topic in {"eligibility", "age_limit"}
                and source.answer_summary is not None
            )
            eligibility = evaluate_eligibility(
                flow.age_years,
                flow.qualification,
                summaries,
                self._qualification_options,
            )
            updated_flow = updated_flow.model_copy(
                update={"eligibility_status": eligibility}
            )
            if eligibility is EligibilityStatus.eligible:
                text_key = "eligibility_result_eligible"
            elif eligibility is EligibilityStatus.not_eligible:
                text_key = "eligibility_result_not_eligible"
            else:
                text_key = "eligibility_to_confirm"
                reply_text = CONVERSATION_TEXTS[text_key].format(
                    official_url=exam.official_notice_url
                )
        elif transition.action == "create_offers":
            if not consent_granted:
                updated_flow = flow
                text_key = None
            else:
                if booking_service is None:
                    raise RuntimeError("booking service is required to create offers")
                created = await booking_service.create_offers(lead_id, now)
                slots = tuple((option.index, option.label) for option in created)
        elif transition.action.startswith("book_offer:"):
            if not consent_granted:
                updated_flow = flow
                text_key = None
            else:
                if booking_service is None:
                    raise RuntimeError("booking service is required to book an offer")
                index = int(transition.action.partition(":")[2])
                result = await booking_service.book_offer(lead_id, index, now)
                text_key = result.text_key
                if result.ok:
                    updated_flow = updated_flow.model_copy(
                        update={"stage": FlowStage.closed}
                    )
                if result.label is not None:
                    reply_text = CONVERSATION_TEXTS[text_key].format(label=result.label)
        elif transition.action.startswith("course:"):
            course_name = transition.action.removeprefix("course:")
            course_map = self._courses.get(flow.exam_id or "", {})
            course = course_map.get(course_name)
            if not isinstance(course, CourseInfoEntry) or course.status == "TO_VERIFY":
                text_key = "course_info_pending"
            else:
                reply_text = _format_course_text(course_name, course.text)
        elif transition.action == "already_submitted":
            text_key = None
        elif transition.action == "create_counselling_request":
            blocked = (
                status
                in {
                    LeadStatus.escalated,
                    LeadStatus.minor_linked,
                    LeadStatus.out_of_scope,
                }
                or context.flags.is_minor
                or context.flags.distress_detected
                or context.flags.self_harm
                or context.flags.scam_signal
                or context.flags.complaint
                or context.flags.fee_dispute
                or context.flags.human_request
            )
            contact_missing = (
                flow.contact_method == "phone"
                and (
                    context.profile.contact is None
                    or context.profile.contact.channel is not ContactChannel.call
                )
            )
            if not consent_granted:
                updated_flow = flow
                text_key = None
            elif blocked:
                updated_flow = flow
                text_key = "counselling_request_blocked"
            elif contact_missing:
                updated_flow = flow.model_copy(update={"stage": FlowStage.contact})
                text_key = "contact_retry"
            else:
                counselling_request_requested = True
                updated_flow = updated_flow.model_copy(
                    update={"stage": FlowStage.request_received}
                )
                first_name = (flow.name or "").strip().split(maxsplit=1)[0]
                text_key = "counsellor_request_received"
                reply_text = resolve_text(text_key, first_name=first_name)
        elif text_key == "counselling_review_prompt":
            exam = self._get_exam(flow.exam_id or "")
            reply_text = CONVERSATION_TEXTS[text_key].format(
                exam=exam.display_name
            )

        if transition.action == "show_buttons" and text_key is None:
            text_key = (
                "category_menu_intro"
                if updated_flow.stage is FlowStage.exam_category
                else "exam_menu_intro"
            )

        new_context = context.model_copy(update={"flow": updated_flow})
        keys = [text_key] if text_key is not None else []
        if self._can_send(consent_granted, ContactChannel.telegram):
            buttons = self._buttons_for_context(new_context, slots)
            if text_key is not None:
                if not counselling_request_requested:
                    await self._messenger.send_text(
                        recipient,
                        resolve_text(text_key) if reply_text is None else reply_text,
                        buttons,
                    )
            elif reply_text is not None:
                if not counselling_request_requested:
                    await self._messenger.send_text(recipient, reply_text, buttons)
            stored = (
                [mask_contact_text(reply_text)]
                if reply_text is not None
                else [resolve_text(text_key)]
                if text_key is not None
                else []
            )
        else:
            stored = []
        return TurnResult(
            new_context,
            status,
            keys,
            stored,
            False,
            None,
            counselling_request_requested,
        )

    async def _answer_telegram_free_text(
        self,
        *,
        recipient: str,
        text: str,
        context: ConversationContext,
        prior_messages: list[SanitizedMessage],
        consent_granted: bool,
        now: datetime,
        status: LeadStatus,
    ) -> TurnResult:
        messages = list(prior_messages[-9:])
        messages.append(SanitizedMessage(role="user", text=text))
        decision_context = DecisionContext(
            messages=messages[-10:],
            profile=_field_updates(context.profile),
            allowed_next_actions=list(NextAction),
            slot_options=[],
        )
        try:
            answer = await answer_message(
                text,
                llm=self._llm,
                context=decision_context,
                knowledge=self._knowledge,
                topic_keywords=self._topic_keywords,
                source_registry=self._source_registry,
                max_age_days=self._knowledge_max_age_days,
                today=now.date(),
                max_attempts=self._llm_max_attempts,
            )
        except LLMUnavailable:
            answer = None
        key = "llm_unavailable_follow_up" if answer is None else answer.text_key
        reply = (
            answer.decision.reply_text
            if answer is not None
            and answer.decision is not None
            and answer.decision.next_action is NextAction.answer_question
            else None
        )
        keys = [key] if key is not None else []
        new_context = context.model_copy(
            update={"message_count": context.message_count + 1}
        )
        stored: list[str] = []
        if self._can_send(consent_granted, ContactChannel.telegram):
            buttons = self._buttons_for_context(new_context, [])
            if key is not None:
                text_to_send = resolve_text(key)
                await self._messenger.send_text(recipient, text_to_send, buttons)
                stored.append(mask_contact_text(text_to_send))
            elif reply is not None:
                await self._messenger.send_text(recipient, reply, buttons)
                stored.append(mask_contact_text(reply))
        return TurnResult(new_context, status, keys, stored, answer is None, None)

    def _buttons_for_context(
        self,
        context: ConversationContext,
        slots: list[SlotOption] | tuple[tuple[int, str], ...],
    ) -> tuple[QuickReply, ...]:
        if self._exam_menu is None:
            return ()
        if slots and isinstance(slots[0], SlotOption):
            slot_pairs = tuple(
                (slot.index, slot.label) for slot in slots
            )
        else:
            slot_pairs = cast(tuple[tuple[int, str], ...], slots)
        return tuple(
            buttons_for_stage(
                context.flow,
                qualification_options=self._qualification_options,
                exam_menu=self._exam_menu,
                slots=slot_pairs,
            )
        )

    def _route_deterministic(
        self, text: str, context: ConversationContext
    ) -> _RoutedReply | None:
        if self._exam_menu is None:
            if is_prediction_question(text):
                return _RoutedReply(text_key="prediction_declined")
            return None

        raw = text.strip()
        normalized = normalize_chat_text(raw)
        if is_prediction_question(raw):
            return _RoutedReply(text_key="prediction_declined")

        if raw == "category:more" or normalized == "more":
            return _RoutedReply(
                text_key="category_menu_intro",
                context_updates={"category_page": context.category_page + 1},
            )
        if raw == "category:back" or normalized == "back":
            if context.selected_category is not None:
                return _RoutedReply(
                    text_key="category_menu_intro",
                    context_updates={"selected_category": None},
                )
            return _RoutedReply(
                text_key="category_menu_intro",
                context_updates={"category_page": max(0, context.category_page - 1)},
            )

        selected_category: str | None = None
        if raw.startswith("category:"):
            selected_category = raw.removeprefix("category:")
        else:
            selected_category = next(
                (
                    category.category_id
                    for category in self._exam_menu.categories
                    if normalize_chat_text(category.display_name) == normalized
                ),
                None,
            )
        if selected_category == "more":
            return _RoutedReply(
                text_key="category_menu_intro",
                context_updates={"category_page": context.category_page + 1},
            )
        if selected_category is not None and any(
            category.category_id == selected_category
            for category in self._exam_menu.categories
        ):
            return _RoutedReply(
                text_key="exam_menu_intro",
                context_updates={
                    "selected_category": selected_category,
                    "selected_exam": None,
                    "category_page": 0,
                },
            )

        selected_exam: Exam | None = None
        if raw.startswith("exam:"):
            exam_id = raw.removeprefix("exam:")
            selected_exam = next(
                (exam for exam in self._exam_menu.exams if exam.exam_id == exam_id),
                None,
            )
        elif context.selected_category is not None:
            selected_exam = next(
                (
                    exam
                    for exam in self._exam_menu.exams
                    if exam.category == context.selected_category
                    and normalize_chat_text(exam.display_name) == normalized
                    and exam.status == "ACTIVE"
                ),
                None,
            )
        if selected_exam is not None and selected_exam.status == "ACTIVE":
            return _RoutedReply(
                text_key="exam_selected",
                context_updates={
                    "selected_exam": selected_exam.exam_id,
                    "selected_category": selected_exam.category,
                    "eligibility_step": None,
                    "age_band": None,
                    "qualification_band": None,
                },
            )

        if raw == "eligibility:check" or "check my eligibility" in normalized:
            if context.selected_exam is not None:
                return _RoutedReply(
                    text_key="eligibility_ask_age",
                    context_updates={"eligibility_step": "age"},
                )
        if context.eligibility_step == "age":
            age = next(
                (
                    value
                    for value in self._age_bands
                    if normalize_chat_text(value) == normalized
                ),
                None,
            )
            if age is not None:
                return _RoutedReply(
                    text_key="eligibility_ask_qualification",
                    context_updates={
                        "age_band": age,
                        "eligibility_step": "qualification",
                    },
                )
        if context.eligibility_step == "qualification":
            qualification = next(
                (
                    value
                    for value in self._qualification_options
                    if normalize_chat_text(value) == normalized
                ),
                None,
            )
            if qualification is not None and context.selected_exam is not None:
                exam = self._get_exam(context.selected_exam)
                sources = [
                    source
                    for source in self._source_registry.values()
                    if source.exam_id == context.selected_exam
                    and source.status == "VERIFIED"
                    and source.topic in {"eligibility", "age_limit", "attempts"}
                    and source.answer_summary is not None
                ]
                updates = {
                    "qualification_band": qualification,
                    "eligibility_step": None,
                }
                if sources:
                    summary = " ".join(
                        source.answer_summary or "" for source in sources
                    )
                    reply = f"{summary} Official notice: {exam.official_notice_url}"
                    return _RoutedReply(reply_text=reply, context_updates=updates)
                return _RoutedReply(
                    text_key="eligibility_pending",
                    context_updates=updates,
                )

        if context.selected_exam is not None:
            course_key = _course_key(raw, normalized)
            if course_key is not None:
                exam_courses = self._courses.get(context.selected_exam)
                course = exam_courses.get(course_key) if exam_courses else None
                if (
                    not isinstance(course, CourseInfoEntry)
                    or course.status == "TO_VERIFY"
                ):
                    return _RoutedReply(text_key="course_info_pending")
                return _RoutedReply(
                    reply_text=_format_course_text(course_key, course.text)
                )
        return None

    def _get_exam(self, exam_id: str) -> Exam:
        if self._exam_menu is None:
            raise RuntimeError("exam menu is not configured")
        exam = next(
            (row for row in self._exam_menu.exams if row.exam_id == exam_id), None
        )
        if exam is None:
            raise KeyError(f"unknown exam {exam_id}")
        return exam

    async def run_once(self) -> bool:
        job_id: UUID | None = None
        claimed_attempt = 1
        now = self._clock.now()
        deferred_message: _DeferredTelegramMessage | None = None
        try:
            async with self._sessions() as session:
                async with session.begin():
                    jobs = JobRepository(session)
                    job = await jobs.claim_next(now)
                    if job is None:
                        return False
                    job_id = job.id
                    claimed_attempt = job.attempts
                    deferred_message = await self._process_job(session, job, now)
                    await jobs.mark_done(job.id, now)
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
        if deferred_message is not None:
            await self._messenger.send_text(
                deferred_message.recipient,
                deferred_message.text,
                deferred_message.quick_replies,
            )
        return True

    async def _process_job(
        self, session: AsyncSession, job: JobRow, now: datetime
    ) -> _DeferredTelegramMessage | None:
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
            lead.id, lead.channel
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
            channel=lead.channel,
        )
        deferred_confirmation: _DeferredTelegramMessage | None = None
        if result.counselling_request_requested:
            request_flow = result.context.flow
            if not consent_granted:
                raise RuntimeError("counselling request requires stored consent")
            if (
                request_flow.goal is None
                or request_flow.name is None
                or request_flow.age_years is None
                or request_flow.qualification is None
                or request_flow.exam_category is None
                or request_flow.exam_id is None
                or request_flow.eligibility_status is None
                or request_flow.contact_method is None
            ):
                raise RuntimeError("counselling request is missing required fields")
            if request_flow.contact_method == "phone" and (
                context.profile.contact is None
                or context.profile.contact.channel is not ContactChannel.call
            ):
                raise RuntimeError("counselling request has no validated phone contact")
            if request_flow.contact_method == "telegram" and (
                lead.channel is not ContactChannel.telegram
            ):
                raise RuntimeError("Telegram follow-up requires a Telegram lead")
            _request, created = await CounsellingRequestRepository(
                session
            ).create_or_get_open(lead.id)
            if created:
                exam = self._get_exam(request_flow.exam_id)
                request_payload = build_staff_payload(
                    lead_id=lead.id,
                    status=result.status,
                    reason="counselling_request",
                    messages=[],
                    flags=context.flags,
                    counselling_request=True,
                    first_name=request_flow.name.strip().split(maxsplit=1)[0],
                    exam=exam.display_name,
                    eligibility_status=(
                        request_flow.eligibility_status.value
                        if request_flow.eligibility_status is not None
                        else None
                    ),
                )
                await OutboxRepository.enqueue_in_session(
                    session,
                    lead_id=lead.id,
                    target="staff_alert",
                    payload=request_payload.model_dump(
                        mode="json", exclude_none=True
                    ),
                    available_at=now,
                )
            if result.stored_texts and self._can_send(consent_granted, lead.channel):
                deferred_confirmation = _DeferredTelegramMessage(
                    recipient=lead.external_user_id,
                    text=result.stored_texts[-1],
                    quick_replies=self._buttons_for_context(
                        result.context, slot_options
                    ),
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
        return deferred_confirmation

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
                payload=result.staff_alert_payload.model_dump(
                    mode="json", exclude_none=True
                ),
                available_at=now,
            )

    @staticmethod
    def _can_send(
        consent_granted: bool, channel: ContactChannel = ContactChannel.chat
    ) -> bool:
        return can_send_outbound(consent_granted, channel.value)


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


def _parse_open_question(context: ConversationContext, text: str) -> LeadProfile | None:
    field = context.last_asked_field
    if field is None:
        return None
    if field.value == "stage":
        stage_value = parse_stage(text)
        return LeadProfile(stage=stage_value) if stage_value is not None else None
    if field.value == "target":
        target_value = parse_target(text)
        return LeadProfile(target=target_value) if target_value is not None else None
    if field.value == "timeline":
        timeline_value = parse_timeline(text)
        return (
            LeadProfile(timeline=timeline_value)
            if timeline_value is not None
            else None
        )
    return None


def _course_key(raw: str, normalized: str) -> str | None:
    if raw.startswith("course:"):
        candidate = raw.removeprefix("course:")
        return (
            candidate if candidate in {"batch_timings", "fees", "demo_class"} else None
        )
    if "timing" in normalized or "batch" in normalized:
        return "batch_timings"
    if "fee" in normalized or "price" in normalized:
        return "fees"
    if "demo" in normalized or "trial" in normalized:
        return "demo_class"
    return None


def _format_course_text(course_key: str, text: str) -> str:
    if course_key == "batch_timings":
        return text.replace(". Timings not yet published.", "; timings not provided.")
    return text


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
    institute = load_knowledge("data/institute.yaml")
    upsc_reference = load_knowledge("data/upsc_reference.yaml")
    knowledge = (*institute.entries, *upsc_reference.entries)
    source_registry = load_sources("data/approved_sources.yaml")
    topic_keywords = yaml.safe_load(
        Path("data/topic_keywords.yaml").read_text(encoding="utf-8")
    )
    messenger: MessengerPort = (
        TelegramMessenger(settings=settings)
        if settings.messenger_provider == "telegram"
        else FakeMessenger()
    )
    worker = Worker(
        sessions,
        cipher,
        OllamaLlmAdapter(settings),
        messenger,
        load_safety_keywords(),
        FakeCalendar(),
        llm_max_attempts=settings.llm_max_attempts,
        job_max_attempts=settings.job_max_attempts,
        clock=SystemClock(),
        knowledge=knowledge,
        topic_keywords=topic_keywords,
        knowledge_max_age_days=settings.knowledge_max_age_days,
        answering_enabled=True,
        source_registry=source_registry,
        exam_menu=load_exam_menu("data/exams.yaml"),
        courses=institute.courses,
        age_bands=tuple(settings.age_bands),
        qualification_options=tuple(settings.qualification_options),
        display_name=settings.institute_display_name,
    )
    try:
        while True:
            if not await worker.run_once():
                await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
