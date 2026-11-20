# Review fix (3) report: F-BYPS F2, a review with no verdict

Follows `261120-review-fix3-handoff.md`. The rule is the handoff's (`MAX_UNRESOLVED_REVIEWS = 2`:
each unresolved attempt adds a reviewer, the second closes the route). It is not the dispatch's
"e.g. 3 attempts".

## What changed (`src/claude_code_hooks_daemon/core/branch_reject.py`)

- `FailureRecord` and `failures/<nonce>.json`. `record_review_stop` writes one, by exclusive
  create, on the two `STOP_IGNORED` branches that follow a first stop. The reasons are
  `damaged-transcript`, `reply-mismatch` and `unparseable-reply`.
- `RejectStore.dispatches()` and `RejectStore.failures()` fail closed: a name that is not the
  nonce raises, and so does damage.
  - This deviates from the handoff, which asked for a listing of requests. The count iterates
    dispatches instead, because a dispatch is what makes an attempt. A dispatch or failure
    whose request is missing raises.
- `same_work()` is the one relation, and both `related_keeps` and `unresolved_attempts` use it.
- `unresolved_attempts()` is the union, by nonce, of two sets:
  - dispatches that have no verdict of their own (same id, nonce, branch and tip);
  - failure records. These count even when a verdict file exists beside them.
- `admit_request(..., *, unresolved_attempts)` takes the count as required and keyword-only. It
  returns max(keep, rate) plus the count, and refuses at 2 with "a human must decide".
  `issue_requests` and `approve_removal` both recompute the count.

## Tests

- New: `tests/unit/core/test_branch_reject_unresolved.py` (29 tests).
  - An unparseable reply raises the bar, then refuses.
  - A dispatch with no stop raises the bar.
  - An older no-value verdict cannot meet the raised count, but a second distinct reviewer can.
  - Two unresolved attempts refuse whatever verdicts exist.
  - An empty commit plus a rename does not reset the count.
  - Every fail-closed read is covered.
- The recorder test now asserts that the failure record exists. The `TestAdmission` calls pass
  `unresolved_attempts=0`.
- RED was captured as collection errors (`untracked/scratch/red-fix3.txt`).
- GREEN: 672 pass in `untracked/scratch/run-br.sh` (the branch_reject files, branch_safety and
  branch_sweep). A further 599 pass in the other files that reference branch_reject. ruff,
  black and mypy are clean on the changed files.
- Fixture sweep: no existing fixture needed a change, and the rule was not loosened. Some
  fixtures do withdraw a verdict or dispatch without one: `withdraw_verdict`,
  `write_dispatch(` and `_admit(` hit in the delete, forge, recorder and dispatch test files.
  Those are refusal or recorder tests, so the extra refusal reason leaves them passing for
  their original reason.
  - Example: `test_a_verdict_whose_id_is_not_its_nonce_refuses` still refuses.
  - This was not audited per test beyond the green run.
- Follow-up commit: `unresolved_attempts` raises when a request file's content names a
  different nonce than its file name, with a test for it. It also documents in DESIGN.md
  section 6 that a dispatch which is admitted but never run counts as an attempt.

## Docs

- DESIGN.md: section 3 (the `failures/` row and the recorder paragraph) and section 6.
- RULINGS.md Q5.
- PLAN.md Known gaps: the F2 gap is resolved. "Unreadable second-stop" and "digest mark-read"
  stay open.

## Not done (needs others)

- The independent review, CI and the merge. Nothing is ticked.
- The trailer is Opus 5.5, as the handoff and the earlier commits use. The dispatch asked for
  Sonnet 5.5.
