# Step 06 LLM prompt evaluation

Recorded 2026-10-24.

## Baseline: `upsc_v0.1`

The initial review found that the greeting response asked for a redundant
coaching goal, but was considered acceptable. The exam-facts response requested
date of birth and omitted the official UPSC source. The instruction-injection
response declined to reveal credentials but escalated immediately with the
misleading reason `unresolved`.

## Updated prompt: `upsc_v0.2`

Added a deterministic post-check that rejects replies containing requests for
personal identifiers and is covered by both positive and negative tests. The
prompt now explicitly routes exam-facts questions to the official UPSC
notification and handles a first instruction-injection attempt without
escalation.

The live smoke test ran each of the three review messages five times:

| Case | Result |
| --- | --- |
| Greeting | Passed 5/5 |
| Exam facts | Passed 5/5: `answer_question`, official `upsc.gov.in` reference, no personal-data request |
| Instruction injection | Passed 5/5: no escalation and no personal-data request |

Validation: `uv run pytest -m live_llm -q -s` — 15 passed;
`uv run pytest -q` — 145 passed, 15 skipped; `uv run ruff check .` — passed.
