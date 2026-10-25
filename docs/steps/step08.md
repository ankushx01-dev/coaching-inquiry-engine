# Step 08: Safety and consent

## Files changed

- `src/coaching_inquiry_engine/services/consent_service.py`
- `src/coaching_inquiry_engine/domain/safety.py`
- `src/coaching_inquiry_engine/agent/conversation.py`
- `tests/unit/test_safety_triggers.py`
- `tests/unit/test_safety_routing.py`
- `tests/unit/test_consent.py`
- `tests/unit/test_staff_payload.py`
- `tests/unit/test_safety_keywords.py`
- `tests/integration/test_consent_db.py`
- `docs/steps/step08.md`

## Reused names

- Safety detection: `SafetyKeywords`, `detect_triggers`, `plan_response`, and
  `QualifyFlags`.
- Lead routing: `qualify`, `LeadProfile`, `LeadStatus`, `handle_event`,
  `ConversationContext`, and `InboundMessage`.
- Consent: `can_send_outbound`, `ConsentService.check_outbound_allowed`,
  `ConsentService.handle_revocation`, and
  `ConsentService.record_and_audit`.
- Conversation: `ConversationContext.injection_count`, `handle_event`,
  `SendText`, and `NotifyStaff`.
- Staff payload: `build_staff_payload` and `StaffNotificationPayload`.
- Text keys: `distress_support`, `minor_guardian`, `scam_warning`,
  `fee_dispute_handoff`, `human_handoff`, `injection_decline`, and
  `consent_stopped`.

## Test counts

- `tests/unit/test_safety_triggers.py`: 33 cases (24 language/category trigger
  cases, 8 category benign cases, and 1 all-flags benign case).
- `tests/unit/test_safety_routing.py`: 6 cases.
- `tests/unit/test_consent.py`: 6 cases (3 outbound states and 3 revocation
  phrases).
- `tests/unit/test_staff_payload.py`: 1 case.
- `tests/unit/test_safety_keywords.py`: 5 cases (empty category, 3 individual
  empty-language cases, and missing review status).
- `tests/integration/test_consent_db.py`: 1 case.

## Fixes

- Consent revocation returns `consent_stopped` for supported opt-out phrases
  and `None` otherwise. Previously the service returned only a boolean, so a
  caller could not select the configured response key. Revoke and audit calls
  remain one per matching call. The integration test now checks the returned
  key instead of a boolean.
- `SafetyKeywords` now rejects an empty `en`, `hi`, or `hinglish` list and
  names both the category and language in the validation error. Previously
  its schema accepted empty phrase lists. The shipped YAML has five phrases
  in each language for every category and remains valid.
- `ConversationContext` tracks injection attempts. The first attempt emits
  `injection_decline`; the second escalates through the existing `_escalate`
  path with reason `injection_repeat`. Previously, the state machine had no
  repeat counter and injection-only flags never escalated. `plan_response`
  remains stateless.

No production caller of `ConsentService.handle_revocation` exists in the
current source tree; the call sites are the unit and integration tests. The
integration test now consumes the returned key. A future message dispatcher
should pass that key through `SendText`; raw inbound text is not used as an
outbound key.

## Injection counter decision

A non-injection message does not reset the counter. The count records how many
injection-flagged messages occurred in the same conversation, even when
benign messages arrive between them.

`build_staff_payload` takes a `lead_id`, recent message strings, status,
reason, and flags, not a lead object. The staff-payload test puts phone and
email values in those message strings.

`data/safety_keywords.yaml` has review status
`PENDING_ACADEMIC_HEAD_REVIEW` and requires academic head review before real
use.
