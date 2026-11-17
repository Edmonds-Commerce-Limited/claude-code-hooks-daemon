# Plan 00618 Phase 2: non-blocking defects and nits

Status: in progress. Base: main at f0ce508bc.

Triage of the 33 items (20 N, 13 T) from `261116-step10-code-review.md`, plus Task 2.5.

## Already fixed on main

- N-16: `session-state --interval` takes `_positive_seconds` (`daemon/cli.py`, commits 31edbba11 red, b0349a116 fix).

## Owner decisions (left alone)

- N-7 and N-8: the stop guard's warn-mode and over-cap counting. Fixing either makes the stop guard allow stops it refuses on main.

## Niggles logged (00474 ledger)

- N630: playbook test #379 drives `echo "test"`, which cannot show the session-start drift notice.
- N631: the Plan 00609 proof script hard-codes `REPO = Path("/workspace")`.
