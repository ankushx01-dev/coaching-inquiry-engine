# Step 09c: Data-backed answers, greeting intent, and quick replies

## Files added

- `data/institute.yaml`
- `data/upsc_reference.yaml`
- `data/reference/drishti_ias.yaml`
- `data/topic_keywords.yaml`
- `data/quick_replies.yaml`
- `prompts/upsc_v0.3.md`
- `src/coaching_inquiry_engine/agent/answering.py`
- `src/coaching_inquiry_engine/domain/intents.py`
- `src/coaching_inquiry_engine/domain/knowledge.py`
- `src/coaching_inquiry_engine/domain/quick_replies.py`
- `src/coaching_inquiry_engine/domain/retrieval.py`
- `tests/unit/test_answering.py`
- `tests/unit/test_intents.py`
- `tests/unit/test_knowledge_loader.py`
- `tests/unit/test_retrieval.py`
- `tests/unit/test_text_keys.py`
- `tests/integration/test_chat_flow_db.py`
- `docs/steps/step09c.md`

## Existing files updated

- `.env.example`
- `src/coaching_inquiry_engine/agent/config.py`
- `src/coaching_inquiry_engine/api/chat_routes.py`
- `src/coaching_inquiry_engine/config.py`
- `src/coaching_inquiry_engine/domain/config.py`
- `src/coaching_inquiry_engine/domain/llm_checks.py`
- `src/coaching_inquiry_engine/main.py`
- `src/coaching_inquiry_engine/ports/llm.py`
- `src/coaching_inquiry_engine/services/chat_service.py`
- `src/coaching_inquiry_engine/services/llm_guard.py`
- `src/coaching_inquiry_engine/worker.py`
- `static/chat.html`
- `tests/unit/test_chat_page.py`
- `tests/unit/test_chat_routes.py`

## Reused names

- `load_sources`, `get_source`, and `Found` / `Stale` / `Missing` from
  `domain/sources.py` continue to load and gate `approved_sources.yaml`.
- `check_decision` and `check_unapproved_quantities` remain the decision
  validators; the answering path also checks bare numeric tokens against the
  retrieved text and offered option labels before accepting a decision.
- Existing `DecisionContext`, `AgentDecision`, `NextAction`, `LlmPort`, and
  `decide_safely` carry the retrieved facts and validated model response.
- Existing `CONVERSATION_TEXTS`, `TEXT_REVIEW_STATUS`, `SendText`, and
  `resolve_text` provide the fixed greeting, help, and missing/stale-knowledge
  responses. The review marker remains metadata.
- Existing `post_chat_message` and `get_chat_replies` are used by the page.
  GET continues to return the session's ordered messages and adds validated
  quick replies.
- Existing `Worker` owns answering and delivery; `MessengerPort` and its
  send-consent gate remain in place.
- The approval-marker precondition was already satisfied by the earlier Fix 3
  change in `test_booking_guard.py` and `agent/config.py`; this step preserved
  it.

## Test counts

- `tests/unit/test_knowledge_loader.py`: 6 cases
- `tests/unit/test_retrieval.py`: 4 cases
- `tests/unit/test_intents.py`: 27 cases
- `tests/unit/test_answering.py`: 4 cases
- `tests/unit/test_text_keys.py`: 1 case
- `tests/unit/test_chat_routes.py`: 6 cases, including ordered messages,
  session isolation, and quick replies
- `tests/unit/test_chat_page.py`: 1 case
- `tests/integration/test_chat_flow_db.py`: 2 cases
- Full unit suite: 338 passed
- Integration suite: 17 passed, 15 deselected

## Decisions that differ from the prompt

- Stale verified entries resolve to a fixed `knowledge_stale` text key and are
  not sent to the LLM. Unverified entries are excluded from retrieval.
- Quick replies are limited to four; the shipped choices are batch timings,
  fees, UPSC basics, and counsellor contact. The page only displays them once
  a bot reply is present.
- `Worker` has an explicit `answering_enabled` dependency. The production
  worker enables it and loads institute, UPSC-reference, and approved-source
  data; existing worker unit setups can continue to inject the legacy test
  behavior without fixture knowledge files.
- The new institute and UPSC-reference entries all remain `TO_VERIFY` with
  placeholder text. They contain no invented facts. The approved source
  registry remains the sole source for exam dates, eligibility, age limits,
  and fees.
- The existing source types are adapted to retrieved knowledge only after
  `get_source` returns `Found` or `Stale`; the approved-source file does not
  get a second loader.

## How institute staff can update data

1. Edit `data/institute.yaml` for institute-owned batches, timings, demo
   classes, faculty, location, contact, and FAQ information. Replace the
   placeholder with a source-backed statement and add a concise `source_note`.
   Keep its fees row as a placeholder; fee answers must use the approved
   source registry.
2. Edit `data/upsc_reference.yaml` only from official `upsc.gov.in` material.
   Record its official `source_url` and the `last_verified` date. The academic
   head must review each UPSC statement before changing its status to
   `VERIFIED`.
3. Keep `data/approved_sources.yaml` as the only source for exam dates,
   eligibility, age limits, attempts, and fees. Populate its approved summary
   and verification date through the existing source review process.
4. Update `last_reviewed` when reviewing a file and `last_verified` for each
   verified entry. Entries older than `KNOWLEDGE_MAX_AGE_DAYS` (30 by default)
   are treated as stale and the assistant tells the visitor the team will
   confirm the information.
5. Add search synonyms to `data/topic_keywords.yaml` when staff use different
   wording. Keep `data/quick_replies.yaml` to four or fewer options; each
   `send_text` is submitted as a normal chat message.
6. Do not use `data/reference/drishti_ias.yaml` for client answers. It is
   benchmark-only data.

## Verification

- `uv run pytest tests/unit -q`: 338 passed
- `uv run pytest tests/integration -q -m integration`: 17 passed, 15 deselected
- `uv run ruff check .`: passed
- `uv run mypy --strict src/coaching_inquiry_engine/domain src/coaching_inquiry_engine/ports`: passed
- No benchmark-data reference exists under `src/`.
- Shipped `TO_VERIFY` entries contain no digits outside the placeholder text.
