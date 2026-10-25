# Step 09a: Chat API and worker

## Files changed

- `.env.example`
- `alembic/env.py`
- `alembic/versions/0003_chat_jobs.py`
- `src/coaching_inquiry_engine/adapters/messenger_fake.py`
- `src/coaching_inquiry_engine/adapters/rate_limiter_memory.py`
- `src/coaching_inquiry_engine/agent/config.py`
- `src/coaching_inquiry_engine/api/chat_routes.py`
- `src/coaching_inquiry_engine/config.py`
- `src/coaching_inquiry_engine/db/models.py`
- `src/coaching_inquiry_engine/db/repositories/__init__.py`
- `src/coaching_inquiry_engine/db/repositories/bookings.py`
- `src/coaching_inquiry_engine/db/repositories/jobs.py`
- `src/coaching_inquiry_engine/db/repositories/leads.py`
- `src/coaching_inquiry_engine/db/repositories/messages.py`
- `src/coaching_inquiry_engine/domain/models.py`
- `src/coaching_inquiry_engine/main.py`
- `src/coaching_inquiry_engine/ports/chat_store.py`
- `src/coaching_inquiry_engine/ports/messenger.py`
- `src/coaching_inquiry_engine/ports/rate_limiter.py`
- `src/coaching_inquiry_engine/services/chat_service.py`
- `src/coaching_inquiry_engine/services/chat_store.py`
- `src/coaching_inquiry_engine/services/job_retry.py`
- `src/coaching_inquiry_engine/services/safety_keywords.py`
- `src/coaching_inquiry_engine/worker.py`
- `tests/integration/conftest.py`
- `tests/integration/test_worker_db.py`
- `tests/unit/test_chat_routes.py`
- `tests/unit/test_job_retry.py`
- `tests/unit/test_worker_pipeline.py`
- `docs/steps/step09a.md`

## Reused names

Reused the existing `ConversationContext`, `handle_event`, `detect_triggers`,
`plan_response`, `qualify`, `decide_safely`, and `PROMPT_VERSION`. Persistence
uses the existing lead, message, consent, booking, and audit repositories. The
new `JobRow` is the single job model; conversation state is stored on the lead
row in `conversation_context`.

The request accepts 32–128 URL-safe characters for `session_id`. The database
stores its SHA-256 lookup key rather than the raw bearer token. Inbound text is
masked before persistence, and outbound text is resolved from configured
`SendText` keys before it is sent or stored.

## Test counts

- `tests/unit/test_chat_routes.py`: 5 cases
- `tests/unit/test_worker_pipeline.py`: 5 cases
- `tests/unit/test_job_retry.py`: 8 cases (including four retry-attempt cases)
- `tests/integration/test_worker_db.py`: 3 cases
- Full unit suite: 266 passed
- Integration suite: 13 passed, 15 deselected

## Decisions that differ from the prompt

No requested behavior was changed. The prompt did not prescribe a session-token
encoding or persistence format; this implementation validates URL-safe tokens
of 32–128 characters and persists only a SHA-256 lookup key. The in-memory
limiter uses a thread-safe sliding one-minute window. The standalone worker is
wired to `FakeMessenger` because this step excludes a real Messenger adapter.

## Verification

- `uv run pytest tests/unit -q`: 266 passed
- `uv run pytest tests/integration -q -m integration`: 13 passed, 15 deselected
- `uv run alembic upgrade head`: passed
- `uv run alembic downgrade -1`: passed
- `uv run alembic upgrade head`: passed
- `uv run mypy --strict src/coaching_inquiry_engine/domain src/coaching_inquiry_engine/ports`: passed
- `uv run ruff check .`: passed
