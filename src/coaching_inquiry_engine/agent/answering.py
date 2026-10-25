"""Policy orchestration for intent shortcuts and knowledge-grounded answers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from coaching_inquiry_engine.domain.decisions import AgentDecision
from coaching_inquiry_engine.domain.intents import Intent, detect_intent
from coaching_inquiry_engine.domain.knowledge import KnowledgeEntry, KnowledgeFile
from coaching_inquiry_engine.domain.llm_checks import DecisionRejectedError
from coaching_inquiry_engine.domain.retrieval import RetrievedEntry, retrieve
from coaching_inquiry_engine.domain.sources import (
    Found,
    Missing,
    SourceEntry,
    Stale,
    get_source,
)
from coaching_inquiry_engine.ports.llm import (
    DecisionContext,
    KnowledgeContextEntry,
    LlmPort,
)
from coaching_inquiry_engine.services.llm_guard import decide_safely


@dataclass(frozen=True, slots=True)
class AnsweringResult:
    intent: Intent | None
    text_key: str | None
    decision: AgentDecision | None
    retrieved: tuple[RetrievedEntry, ...]


async def answer_message(
    text: str,
    *,
    llm: LlmPort,
    context: DecisionContext,
    knowledge: KnowledgeFile | Sequence[KnowledgeEntry],
    topic_keywords: dict[str, list[str]],
    source_registry: dict[str, SourceEntry] | None = None,
    max_age_days: int = 30,
    today: date | None = None,
    max_attempts: int | None = None,
) -> AnsweringResult:
    """Short-circuit greeting/help and answer only from retrieved facts."""
    intent = detect_intent(text)
    if intent is not None:
        return AnsweringResult(
            intent=intent,
            text_key="greeting_welcome" if intent == "greeting" else "help_menu",
            decision=None,
            retrieved=(),
        )

    terms = text.split()
    source_entries = _verified_source_entries(
        text,
        source_registry or {},
        topic_keywords=topic_keywords,
        today=today or date.today(),
        max_age_days=max_age_days,
    )
    matches = tuple(
        retrieve(
            terms,
            [*_knowledge_entries(knowledge), *source_entries],
            topic_keywords=topic_keywords,
            today=today,
            max_age_days=max_age_days,
        )
    )
    if not matches:
        return AnsweringResult(
            intent=None,
            text_key="knowledge_not_found",
            decision=None,
            retrieved=(),
        )
    if any(match.stale for match in matches):
        return AnsweringResult(
            intent=None,
            text_key="knowledge_stale",
            decision=None,
            retrieved=matches,
        )

    knowledge_context = [
        KnowledgeContextEntry(
            id=match.entry.id,
            topic=match.entry.topic,
            text=match.entry.text,
            status=match.entry.status,
            source=str(match.entry.source_url or match.entry.source_note),
        )
        for match in matches
    ]
    llm_context = context.model_copy(update={"knowledge_entries": knowledge_context})
    decision = await decide_safely(
        llm,
        llm_context,
        max_attempts=max_attempts,
        decision_validator=lambda candidate: _check_answer_numbers(
            candidate.reply_text, llm_context
        ),
    )
    return AnsweringResult(
        intent=None,
        text_key=None,
        decision=decision,
        retrieved=matches,
    )


def _check_answer_numbers(reply_text: str, context: DecisionContext) -> None:
    text_without_citations = re.sub(r"\[[^\]]+\]", "", reply_text)
    allowed = " ".join(
        [entry.text for entry in context.knowledge_entries]
        + [option.label for option in context.slot_options]
    )
    numbers = re.findall(
        r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])", text_without_citations
    )
    for number in numbers:
        if re.search(rf"(?<![\w]){re.escape(number)}(?![\w])", allowed) is None:
            raise DecisionRejectedError(
                f"reply_text contains an unapproved number {number!r}"
            )


def _knowledge_entries(
    knowledge: KnowledgeFile | Sequence[KnowledgeEntry],
) -> Sequence[KnowledgeEntry]:
    return knowledge.entries if isinstance(knowledge, KnowledgeFile) else knowledge


def _verified_source_entries(
    question: str,
    source_registry: dict[str, SourceEntry],
    *,
    topic_keywords: dict[str, list[str]],
    today: date,
    max_age_days: int,
) -> list[KnowledgeEntry]:
    question_tokens = set(re.findall(r"[^\W_]+", question.casefold()))
    result: list[KnowledgeEntry] = []
    for topic in source_registry:
        keywords = set(re.findall(r"[^\W_]+", topic.casefold()))
        for keyword in topic_keywords.get(topic, []):
            keywords.update(re.findall(r"[^\W_]+", keyword.casefold()))
        if not question_tokens.intersection(keywords):
            continue
        lookup = get_source(source_registry, topic, today, max_age_days)
        if isinstance(lookup, (Found, Stale)):
            verified = lookup.entry
            if verified.answer_summary is None or verified.last_verified is None:
                continue
            result.append(
                KnowledgeEntry(
                    id=verified.id,
                    topic=verified.topic,
                    text=verified.answer_summary,
                    source_note=verified.owner,
                    source_url=verified.official_url,
                    last_verified=verified.last_verified,
                    status="VERIFIED",
                )
            )
        elif not isinstance(lookup, Missing):
            raise AssertionError("unknown source lookup result")
    return result
