# Step 09j: Counselling requests and staff dashboard

## Purpose and scope

Step 09j extends the staged Telegram conversation with a contact preference,
an explicit counselling-request review, and a durable, idempotent staff request.
It adds an authenticated server-rendered staff dashboard and a privacy-safe audit
trail. The Step 09i consent, qualification, eligibility, booking, approved-source,
message-delivery, and safety behavior remains in its existing services.

## Existing components reused

- `domain.flow.FlowStage`, `FlowContext`, and the pure `transition()` function
  own valid user transitions and the counselling resume path.
- `domain.models.Contact` validates Indian mobile values; `LeadRepository`
  persists contact data through the existing encrypted contact columns and
  `[ENCRYPTED]` conversation-context marker.
- `ConsentRepository`, `ConsentService`, and `can_send_outbound()` continue to
  own consent persistence, revocation, and the outbound-send gate.
- `Worker` remains the transaction boundary for context, request, messages,
  audit, job completion, and outbox persistence.
- `OutboxRepository` and the existing `staff_alert` target keep staff delivery
  asynchronous and retryable.
- `build_staff_payload()` remains the staff-payload builder and validates its
  masked, data-minimized representation.
- `AuditRepository`, `assert_safe_audit_detail()`, and `mask_contact_text()`
  provide the existing audit and contact-masking contracts.
- `TelegramMessenger`, `TelegramWebhookService`, and the existing Telegram
  update idempotency path handle keyboards, contact updates, callbacks, and
  retries.
- Lead deletion cascades through the foreign keys; no separate retention job or
  retention schedule was introduced.

## Conversation flow and navigation

The existing consent, goal, name, age, qualification, exam category, exam,
eligibility, course-options, and booking stages remain in place. The counselling
action resumes at the earliest missing required field in the established order:
goal, name, age, qualification, exam category, exam, and eligibility result.
Fields already present in the flow context are reused. After those fields are
complete, the user chooses a contact method and reviews the selected exam before
confirming.

At contact collection the Telegram keyboard offers:

- **Share phone number**, using Telegram's native `request_contact` button.
- **Type a phone number**, validating input with the existing `Contact` model.
- **Contact me here**, for follow-up through the current Telegram conversation.
- **Back to courses**, which keeps the collected profile and returns to course
  options.
- **Cancel request**, which returns to course options without deleting the lead
  or an existing request.

Shared contacts are accepted only when Telegram marks the contact as belonging
to the sender and the existing mobile validator accepts its phone number. A
Telegram chat ID or username is never treated as a phone number. Manual input is
replaced with a non-sensitive action marker before it is persisted as a message.
Both valid contact paths call the existing encrypted `LeadRepository` storage
path. Invalid entries receive `contact_retry`.

The final review shows the exam and counselling intent, not contact details.
Only an explicit `Confirm request` action can create a request. Back, cancel,
main-menu, retry, resume, stale callback, and repeated callback behavior is
handled by the flow stage and Telegram update-idempotency checks. A successful
request displays `counsellor_request_received` using only the first name and
makes no response-time promise.

After a request is submitted, the counselling action is removed from the
course-options menu so the user is not invited to submit it again.

## Consent, required fields, and atomic creation

The worker rechecks stored consent, required flow fields, the validated phone
contact (when selected), and Telegram-channel eligibility (when the user chose
follow-up here) before it accepts the action. The transition also checks the
current flow stage and required fields. An incomplete flow asks for the next
missing field without creating a request or staff alert.

Inside the existing job transaction, the worker saves the updated context,
inserts or retrieves the lead's open request through
`CounsellingRequestRepository.create_or_get_open()`, and enqueues a staff alert
only when the insert created a new request. The worker commits before sending
the user confirmation and still checks the existing outbound consent gate.
The database partial unique index is the concurrency boundary; retrying or
concurrently submitting cannot create another open request or alert. A closed
request permits a later new request.

The counselling `staff_alert` payload contains only a non-sensitive lead
reference, first name, exam, and eligibility status. It excludes contact values,
full names, raw conversation messages, and authentication data. Existing
serialization validation and outbox retry behavior are retained.

## Database and retention

Migration `0006_counselling_requests` follows `0005_staged_telegram_flow`. It
creates `counselling_requests` with UUID ID, cascading `lead_id`, constrained
status (`new`, `contacted`, `booked`, `closed`), optional assignment and notes,
and timestamps. The partial unique index
`uq_counselling_requests_one_open_per_lead` applies while status is not `closed`.
The migration supports downgrade and re-upgrade. PostgreSQL is the supported
runtime database; SQLite index metadata is present for local metadata-based
tests only.

Deleting a lead cascades to its counselling requests, including request notes.
The encrypted contact columns, outbox, and audit records retain their existing
deletion and retention behavior; Step 09j adds no independent retention policy.

## Dashboard routes and data handling

The router is registered only when `ADMIN_ENABLED=true`.

- `GET /admin/requests` lists 25 requests per page, newest first, with validated
  exam, status, inclusive date-range, and page filters. Its repository projection
  does not select encrypted or decrypted contact data.
- `GET /admin/requests/{id}` is the only dashboard view that decrypts a stored
  phone contact. It shows request-relevant profile and consent fields, a
  Telegram conversation reference when appropriate, and at most the latest five
  messages after existing phone/email masking. It writes an audit event before
  returning the page.
- `POST /admin/requests/{id}/status` validates status, assignment, and notes,
  updates the request and writes its audit event in one transaction. HTML forms
  redirect after success; JSON callers receive the updated non-contact fields.

All pages are server rendered through autoescaped Jinja templates. There are no
external scripts, stylesheets, or CDN assets. User-controlled values are escaped
in the HTML response. Request notes reject detected Indian phone and email
values and are escaped when rendered.

## Authentication and deployment

Configure `ADMIN_ENABLED=true`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD_HASH`.
Startup names any missing required variable. Passwords are verified with the
stdlib PBKDF2-HMAC-SHA256 implementation in `services.admin_auth`; hashes use a
random 16-byte salt and 310,000 iterations by default. To generate a hash
interactively without placing the plaintext password in shell history, run:

```powershell
uv run python -c "from getpass import getpass; from coaching_inquiry_engine.services.admin_auth import hash_admin_password; print(hash_admin_password(getpass('Admin password: ')))"
```

Put the returned hash in the secret store or environment, and keep the plaintext
password out of configuration. In production, the dashboard rejects requests
whose ASGI URL scheme is HTTP. If TLS terminates at a reverse proxy, configure
Uvicorn to trust proxy headers only from the known proxy addresses (for example,
with `--proxy-headers --forwarded-allow-ips=<trusted-proxy-addresses>`); arbitrary
forwarded headers from clients are not trusted by the dashboard.

Failed Basic-auth attempts receive a generic response and a bounded in-process
per-client-address rate limit. Usernames use constant-time comparison and
password verification uses PBKDF2 plus constant-time digest comparison. Use a
network-level rate limit as well when deploying multiple application workers,
because the in-process limiter is local to each worker.

## Audit and accountability

Every authenticated contact-detail view records
`admin_contact_detail_viewed`; every successful status update records
`admin_counselling_request_status_changed`. Events are appended through
`AuditRepository` in the same database transaction as the corresponding
operation. Details include staff identity, action, request reference, and the
new status where applicable. The audit safety helper rejects contact-shaped
keys; values, notes, raw requests, passwords, and headers are not included.
An audit failure aborts the operation rather than reporting success.

## Environment and configuration

The `.env.example` defaults the dashboard to disabled. Configure the admin
variables only in a protected local environment or secret manager. Existing
`CIE_ENCRYPTION_KEY` and `CIE_CONTACT_HASH_KEY` requirements continue to apply;
this feature does not change their encryption or rotation policy.

## Verification

| Check | Result |
|---|---|
| `uv run ruff check .` | The exact command could not sync Jinja2 because this host cannot resolve PyPI. `uv run --no-sync ruff check .` passed. |
| `uv run mypy --strict src/coaching_inquiry_engine/domain src/coaching_inquiry_engine/ports` | `uv run --no-sync mypy --strict ...` passed: 27 source files, no issues. |
| `uv run pytest tests/unit -q` | The exact command stopped before collection while uv tried to fetch `hatchling`. With sync disabled, 466 tests collected; execution stalled at the first async test on this Windows host and was interrupted. |
| Focused synchronous unit checks | 17 passed, 4 async checks deselected. This covered counselling transitions, text metadata, payload serialization, auth hash/config validation, and template escaping. |
| `uv run pytest tests/integration -q -m integration` | The exact command stopped before collection while uv tried to fetch `hatchling`. With sync disabled, execution stalled before test progress. Collection found 32 database tests out of 47 total; 15 live-LLM tests were deselected. |
| PostgreSQL integration and online migration checks | Not completed. `localhost:5432` was unreachable. The online migration attempt targeted a dedicated `coaching_inquiry_step09j_test` database and was interrupted before connecting; no migration or integration fixture ran against a database. |
| Offline Alembic SQL generation | `uv run --no-sync alembic upgrade head --sql` and the 0006-to-0005 downgrade SQL generation succeeded. Generated SQL contains the status default/check, cascading foreign key, and partial unique index. Offline SQL generation does not verify applying a migration to PostgreSQL. |
| Python compilation | `uv run --no-sync python -m compileall -q src tests` passed. |
| Additional whole-package strict mypy check | Reports 7 errors in existing booking, lead-retention, and outbox typing paths. The required domain/ports strict check passes. |

The project’s existing Step 09i documentation records the Windows async test
runner self-pipe stall. The same behavior prevented the full unit and
integration runs here; async API, worker, Telegram, and PostgreSQL tests remain
unverified on this host.

## Limitations

The failed-login limiter is process-local and resets on application restart.
Contact decryption is scoped to the authenticated detail route; staff account
provisioning and network-level access control remain deployment responsibilities.
