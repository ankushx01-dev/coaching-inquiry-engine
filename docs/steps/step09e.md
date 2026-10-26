# Step 09e: Exam, eligibility, and course routing

## Files changed

- `.env.example`
- `data/exams.yaml` (new)
- `data/institute.yaml`
- `data/quick_replies.yaml`
- `src/coaching_inquiry_engine/agent/config.py`
- `src/coaching_inquiry_engine/agent/answering.py`
- `src/coaching_inquiry_engine/agent/conversation.py`
- `src/coaching_inquiry_engine/api/chat_routes.py`
- `src/coaching_inquiry_engine/config.py`
- `src/coaching_inquiry_engine/domain/chat_routing.py` (new)
- `src/coaching_inquiry_engine/domain/exam_menu.py` (new)
- `src/coaching_inquiry_engine/domain/knowledge.py`
- `src/coaching_inquiry_engine/domain/sources.py`
- `src/coaching_inquiry_engine/main.py`
- `src/coaching_inquiry_engine/ports/chat_store.py`
- `src/coaching_inquiry_engine/services/chat_service.py`
- `src/coaching_inquiry_engine/services/chat_store.py`
- `src/coaching_inquiry_engine/worker.py`
- `tests/integration/test_worker_db.py`
- `tests/unit/test_course_info.py` (new)
- `tests/unit/test_eligibility.py` (new)
- `tests/unit/test_exam_menu.py` (new)
- `tests/unit/test_open_question.py` (new)
- `tests/unit/test_routing_order.py` (new)
- `tests/unit/test_text_keys.py`
- `docs/steps/step09e.md` (new)

## Reused names

- `detect_intent`, `answer_message`, `retrieve`, `load_knowledge`,
  `load_sources`, `get_source`, and `Found` / `Stale` / `Missing` remain the
  existing greeting, answering, knowledge, and approved-source paths.
- `detect_triggers`, `plan_response`, `handle_event`, `qualify`,
  `CONVERSATION_TEXTS`, `TEXT_REVIEW_STATUS`, `SendText`, and `resolve_text`
  remain the safety, qualification, and fixed-text owners.
- `ChatMessageService`, `PostgresChatStore`, and the existing chat GET route
  return session-specific quick replies; the stored `ConversationContext`
  determines the active category, exam, and eligibility question.
- `NotifyStaff`, the existing handoff plan, the staff payload builder, and the
  worker consent gate continue to deliver counsellor requests.

## Test counts

- `tests/unit/test_routing_order.py`: 3 cases
- `tests/unit/test_exam_menu.py`: 3 cases
- `tests/unit/test_eligibility.py`: 3 cases
- `tests/unit/test_course_info.py`: 2 cases
- `tests/unit/test_open_question.py`: 3 cases
- `tests/unit/test_text_keys.py`: 2 cases total
- Unit suite: 371 passed
- Integration suite: 17 passed, 15 deselected

## Decisions and differences

- Collected names and eligibility bands are saved on `ConversationContext`,
  which is already persisted as session state. They are not added to contact
  data or the qualification profile.
- The category screens show up to three categories plus a More button, so the
  screen stays at four options. Exams are loaded from `data/exams.yaml`.
- The selected exam screen returns the three course options, eligibility, and
  counsellor handoff as session-specific quick replies.
- Eligibility uses only `VERIFIED` `approved_sources.yaml` rows whose optional
  `exam_id` matches the selected exam. If none qualify, the fixed pending key
  includes the official notice URL configured for that exam. The worker does
  not calculate an eligibility result.
- The shipped course rows remain `TO_VERIFY` placeholders. Verified course
  wording is covered with a unit fixture; no batch schedule, fee, or demo
  details were invented.
- `AGE_BANDS` and `QUALIFICATION_OPTIONS` are editable through their JSON list
  values in the environment; the defaults are in `Settings`.
- The integration fixture now sets job `available_at` to its fixed `_NOW`.
  The database default used the current date, which was later than that test's
  fixed clock and made the advisory-lock test date-sensitive.
- `approved_sources.yaml` and its existing verified-summary/date validation
  rules were not changed.

## Verification

- `uv run pytest tests/unit -q`: 371 passed
- `uv run pytest tests/integration -q -m integration`: 17 passed, 15 deselected
- `uv run ruff check .`: passed
- `uv run mypy --strict src/coaching_inquiry_engine/domain src/coaching_inquiry_engine/ports`: passed
