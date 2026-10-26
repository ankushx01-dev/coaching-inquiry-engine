# Step 09h: Telegram messenger and webhook

## Files changed

- `.env.example`
- `src/coaching_inquiry_engine/config.py`
- `src/coaching_inquiry_engine/domain/models.py`
- `src/coaching_inquiry_engine/agent/config.py`
- `src/coaching_inquiry_engine/adapters/messenger_telegram.py`
- `src/coaching_inquiry_engine/api/telegram_webhook.py`
- `src/coaching_inquiry_engine/main.py`
- `src/coaching_inquiry_engine/services/telegram_webhook.py`
- `src/coaching_inquiry_engine/worker.py`
- `tests/unit/test_messenger_telegram.py`
- `tests/unit/test_telegram_webhook.py`
- `tests/unit/test_worker_pipeline.py`
- `tests/integration/test_telegram_webhook_db.py`
- `docs/steps/step09h.md`

## Reused names

The implementation reuses `MessengerPort`, `FakeMessenger`,
`ContactChannel`, `LeadRepository.get_or_create_lead`,
`MessageRepository.insert_message_if_new`, `JobRepository.enqueue`,
`ConsentService`, `CONVERSATION_TEXTS`, and the existing `quick_replies.yaml`
and `QuickReply` model. Telegram update IDs become message provider IDs, so the
existing database uniqueness constraint deduplicates webhook retries.

## Behavior

- `TelegramMessenger` sends Bot API requests using `httpx.AsyncClient`, config
  timeout/retry/backoff, redacts the bot token from HTTPX log records, and
  encodes existing quick reply action IDs as inline keyboard callback data.
- The webhook checks the secret with `secrets.compare_digest`, maps the Telegram
  chat ID to `external_user_id`, and only enqueues a new inbound update once.
- `/start` sends the consent notice and `I agree` callback. The callback records
  consent. `/stop` uses the existing consent revocation service and sends the
  `consent_stopped` text only when the outbound consent gate permits it.
- Worker outbound messages query and check consent for the lead's actual
  channel, preserving the existing send gate.
- Telegram is selected only when `MESSENGER_PROVIDER=telegram`; fake remains
  the default. Startup validation names missing Telegram environment values.

## BotFather and webhook setup

1. In Telegram, open the verified `@BotFather`, run `/newbot`, and follow its
   prompts to choose the bot display name and username.
2. Copy the BotFather token into `TELEGRAM_BOT_TOKEN` in the deployment secret
   store. Do not put it in source code or logs.
3. Generate a long random webhook secret and configure it as
   `TELEGRAM_WEBHOOK_SECRET`. Set `MESSENGER_PROVIDER=telegram`.
4. Deploy the HTTPS application and configure Telegram's webhook for
   `https://<host>/webhooks/telegram`, supplying the same secret as Telegram's
   `secret_token` parameter. Keep the URL secret out of logs and source.
5. Verify updates arrive and that `/start`, the `I agree` callback, normal
   messages, quick replies, and `/stop` behave as expected. Use a test bot and
   test chat before enabling the bot for visitors.

## Tests and environment notes

- `tests/unit/test_messenger_telegram.py`: 5
- `tests/unit/test_telegram_webhook.py`: 2
- `tests/integration/test_telegram_webhook_db.py`: 1
- `tests/unit/test_worker_pipeline.py`: 5 existing cases retained; one fake
  Lead fixture now includes its required `channel` field.

HTTP adapter tests use HTTPX `MockTransport`, so they make no network calls.
The requested `respx` dependency could not be fetched because package-index DNS
is unavailable in this environment. The PostgreSQL integration test is present
but could not run here because the configured database refused the connection.
