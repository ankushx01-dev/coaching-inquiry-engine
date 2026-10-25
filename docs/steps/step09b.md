# Step 09b: Outbox delivery, clock, and embeddable chat

## Files changed

- `.env.example`
- `alembic/versions/0004_outbox_dispatch.py`
- `src/coaching_inquiry_engine/adapters/clock.py`
- `src/coaching_inquiry_engine/adapters/clock_fake.py`
- `src/coaching_inquiry_engine/adapters/crm_fake.py`
- `src/coaching_inquiry_engine/adapters/crm_hubspot.py`
- `src/coaching_inquiry_engine/adapters/staff_alert_email.py`
- `src/coaching_inquiry_engine/adapters/staff_alert_fake.py`
- `src/coaching_inquiry_engine/adapters/staff_alert_telegram.py`
- `src/coaching_inquiry_engine/api/chat_page.py`
- `src/coaching_inquiry_engine/config.py`
- `src/coaching_inquiry_engine/db/models.py`
- `src/coaching_inquiry_engine/db/repositories/outbox.py`
- `src/coaching_inquiry_engine/domain/models.py`
- `src/coaching_inquiry_engine/main.py`
- `src/coaching_inquiry_engine/outbox_worker.py`
- `src/coaching_inquiry_engine/ports/clock.py`
- `src/coaching_inquiry_engine/ports/crm.py`
- `src/coaching_inquiry_engine/ports/staff_alert.py`
- `src/coaching_inquiry_engine/services/chat_store.py`
- `src/coaching_inquiry_engine/services/escalation_service.py`
- `src/coaching_inquiry_engine/services/outbox_service.py`
- `src/coaching_inquiry_engine/worker.py`
- `static/chat.html`
- `tests/integration/test_outbox_db.py`
- `tests/unit/test_chat_page.py`
- `tests/unit/test_clock.py`
- `tests/unit/test_crm_upsert.py`
- `tests/unit/test_escalation_outbox.py`
- `tests/unit/test_outbox_drain.py`
- `docs/steps/step09b.md`

## Reused names

- `NotifyStaff`, `StaffNotificationPayload`, and `build_staff_payload` from
  `services/escalation_service.py`. `StaffAlertPayload` is an alias of the
  existing payload model, not a second schema.
- The existing `OutboxRow` and Step 07 `crm_outbox_payload`,
  `CRM_OUTBOX_EVENT`, and `BookingRepository.persist_booking`. One new
  `OutboxRepository` claims and updates rows from that table.
- Existing `MessengerPort` and `FakeMessenger`; they remain responsible for
  user-facing messages. Staff alerts are queued for `outbox_worker.py`.
- Existing chat endpoints `post_chat_message` and `get_chat_replies`; the page
  calls those endpoints without changing their request or response behavior.
- Existing `JOB_MAX_ATTEMPTS` controls the outbox dead-letter limit as well as
  the message job limit.

## Test counts

- `tests/unit/test_clock.py`: 4 cases
- `tests/unit/test_outbox_drain.py`: 6 cases
- `tests/unit/test_crm_upsert.py`: 1 case
- `tests/unit/test_escalation_outbox.py`: 6 cases
- `tests/unit/test_chat_page.py`: 1 case
- `tests/unit/test_staff_payload.py`: 1 unchanged case; passed
- `tests/integration/test_outbox_db.py`: 2 cases
- Full unit suite: 284 passed
- Integration suite: 15 passed, 15 deselected

## Decisions that differ from the prompt

- Added migration `0004_outbox_dispatch` with `claimed_at` and `last_error`,
  plus a pending-row index. Claims change status to `processing` and record the
  attempt before delivery so concurrent drains cannot select the same row.
- Retry delay is `OUTBOX_BASE_BACKOFF_SECONDS * 2 ** (attempt - 1)`, with the
  failure timestamp obtained from the injected clock.
- The page is served at `/chat`. Its response uses CSP `frame-ancestors` with
  only `CHAT_ALLOWED_ORIGIN`; it has no `X-Frame-Options` header. The consent
  notice retains the requested `[INSTITUTE_NAME]` placeholder and `TO_APPROVE`
  marker for institute review.
- Booking CRM events call idempotent `upsert_contact` and create a deal at
  stage `booked`, using the lead UUID as the reference. No phone number is used
  as a CRM identifier.
- Both email and Telegram staff-alert adapters are stubs because the
  configuration accepts either channel and the institute has not selected a
  production delivery setup.

## Stubs to implement before production

- `adapters/crm_hubspot.py`: authenticated HubSpot contact and deal calls,
  mapping, and production error handling.
- `adapters/staff_alert_email.py` or `adapters/staff_alert_telegram.py`:
  implement the institute-selected staff channel, credentials, and delivery
  handling. Both currently raise `NotImplementedError`.

## Verification

- `uv run pytest tests/unit -q`: 284 passed
- `uv run pytest tests/integration -q -m integration`: 15 passed, 15 deselected
- `uv run alembic upgrade head`: passed
- `uv run alembic downgrade -1`: passed
- `uv run alembic upgrade head`: passed
- `uv run mypy --strict src/coaching_inquiry_engine/domain src/coaching_inquiry_engine/ports`: passed
- `uv run ruff check .`: passed
