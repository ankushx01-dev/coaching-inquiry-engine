"""Chat HTTP request validation, idempotency, and rate-limit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from coaching_inquiry_engine.adapters.rate_limiter_memory import InMemoryRateLimiter
from coaching_inquiry_engine.api.chat_routes import router
from coaching_inquiry_engine.domain.models import MessageDirection
from coaching_inquiry_engine.domain.quick_replies import QuickReply
from coaching_inquiry_engine.ports.chat_store import StoredChatMessage
from coaching_inquiry_engine.services.chat_service import ChatMessageService

_SESSION_A = "A" * 43
_SESSION_B = "B" * 43


class _MemoryChatStore:
    def __init__(self) -> None:
        self.message_ids: dict[tuple[str, str], UUID] = {}
        self.enqueued: list[tuple[str, str]] = []
        self.messages_by_session: dict[str, list[StoredChatMessage]] = {}

    async def accept_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        text: str,
        consent_given: bool,
    ) -> UUID:
        _ = text, consent_given
        key = session_id, client_message_id
        existing = self.message_ids.get(key)
        if existing is not None:
            return existing
        message_id = uuid4()
        self.message_ids[key] = message_id
        self.enqueued.append(key)
        return message_id

    async def list_messages(self, session_id: str) -> list[StoredChatMessage]:
        return self.messages_by_session.get(session_id, [])


def _app(
    store: _MemoryChatStore,
    *,
    per_session: int = 10,
    per_ip: int = 60,
) -> FastAPI:
    app = FastAPI()
    app.state.chat_message_service = ChatMessageService(
        store,
        InMemoryRateLimiter(
            per_session_per_minute=per_session,
            per_ip_per_minute=per_ip,
        ),
        (QuickReply(label="Fees", send_text="What are the fees?"),),
    )
    app.include_router(router)
    return app


async def _post(
    client: AsyncClient,
    *,
    session_id: str = _SESSION_A,
    client_message_id: str = "client-1",
    text: str = "hello",
) -> object:
    return await client.post(
        "/v1/chat/messages",
        json={
            "session_id": session_id,
            "client_message_id": client_message_id,
            "text": text,
            "consent_given": True,
        },
    )


async def test_chat_message_rejects_text_over_1000_characters() -> None:
    app = _app(_MemoryChatStore())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post(client, text="x" * 1001)

    assert response.status_code == 422


async def test_repeated_client_message_id_returns_original_without_enqueueing() -> None:
    store = _MemoryChatStore()
    app = _app(store)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post(client)
        repeat = await _post(client)

    first_body = first.json()
    repeat_body = repeat.json()
    assert first.status_code == repeat.status_code == 202
    assert first_body["message_id"] == repeat_body["message_id"]
    assert first_body == {"accepted": True, "message_id": first_body["message_id"]}
    assert "text" not in first_body
    assert "reply" not in first_body
    assert store.enqueued == [(_SESSION_A, "client-1")]


async def test_get_returns_both_directions_in_time_order_for_one_session_only() -> None:
    store = _MemoryChatStore()
    first_time = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    second_time = datetime(2026, 10, 25, 12, 1, tzinfo=UTC)
    store.messages_by_session = {
        _SESSION_A: [
            StoredChatMessage(
                UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                MessageDirection.outbound,
                "reply A",
                second_time,
            ),
            StoredChatMessage(
                UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                MessageDirection.inbound,
                "hello A",
                first_time,
            ),
        ],
        _SESSION_B: [
            StoredChatMessage(
                UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                MessageDirection.inbound,
                "private to B",
                first_time,
            )
        ],
    }
    app = _app(store)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/chat/messages", params={"session_id": _SESSION_A}
        )

    assert response.status_code == 200
    assert response.json() == {
        "messages": [
            {
                "message_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "direction": "inbound",
                "text": "hello A",
                "received_at": "2026-10-25T12:00:00Z",
            },
            {
                "message_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "direction": "outbound",
                "text": "reply A",
                "received_at": "2026-10-25T12:01:00Z",
            },
        ],
        "quick_replies": [{"label": "Fees", "send_text": "What are the fees?"}],
    }
    assert "private to B" not in response.text


async def test_rate_limit_returns_429_after_session_threshold() -> None:
    app = _app(_MemoryChatStore(), per_session=1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post(client)
        second = await _post(client, client_message_id="client-2")

    assert first.status_code == 202
    assert second.status_code == 429


async def test_rate_limit_returns_429_after_ip_threshold() -> None:
    app = _app(_MemoryChatStore(), per_ip=1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post(client)
        second = await _post(
            client, session_id=_SESSION_B, client_message_id="client-2"
        )

    assert first.status_code == 202
    assert second.status_code == 429


async def test_polling_get_does_not_consume_the_message_send_limit() -> None:
    app = _app(_MemoryChatStore(), per_session=1)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await _post(client)
        poll = await client.get(
            "/v1/chat/messages", params={"session_id": _SESSION_A}
        )
        second = await _post(client, client_message_id="client-2")

    assert first.status_code == 202
    assert poll.status_code == 200
    assert second.status_code == 429
