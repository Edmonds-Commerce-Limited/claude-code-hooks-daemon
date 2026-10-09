# Fact check: 00480 diff (live run)

## REFUTED

1. Claim 2: "`utils/plan_fact_check.py` sets [MAX_OFFERS] to 10". The file sets it to 3 (`src/claude_code_hooks_daemon/utils/plan_fact_check.py:62`: `MAX_OFFERS: Final[int] = 3`). Plan change: replace 10 with 3.

## Table

| #   | Claim                                                     | Verdict  | Evidence                                                         |
| --- | --------------------------------------------------------- | -------- | ---------------------------------------------------------------- |
| 1   | "an unacted offer is re-offered up to `MAX_OFFERS` times" | VERIFIED | plan_fact_check.py:15, 547 (`pending.offers >= MAX_OFFERS`), 571 |
| 2   | "`utils/plan_fact_check.py` sets [MAX_OFFERS] to 10"      | REFUTED  | plan_fact_check.py:62 is 3                                       |
