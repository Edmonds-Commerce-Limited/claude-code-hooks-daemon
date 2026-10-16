# Plan 00495 finish: Tasks 1.4, 3.1, 3.2

## Assumptions

- The start-up budget is 2 s CPU for the start before the bind, median of 5 samples with a retry round
  (`CLAUDE/Performance/startup-budget.json`), checked as a release step and not in the per-commit suite.
- The secret-file guard's cost is a Python fix tracked as ledger N465 and fixed separately. It is recorded in
  `RUST-HELPERS-ASSESSMENT.md` as not a Rust candidate, and Plan 00529 no longer asks the owner to decide it.

## Delivered (commit fd79648ab and the follow-up commit that carries this report)

- Task 1.4: `CLAUDE/Performance/BASELINE.md` re-measured with the Phase 1 method; `README.md` relay row corrected.
- Task 3.1: `scripts/release/check_startup_budget.py`, RELEASING.md Step 8b, budget file, unit tests
  (`tests/unit/scripts/test_check_startup_budget.py`) and the planted-slowdown test
  (`tests/integration/test_startup_budget_planted_slowdown.py`).
- Task 3.2: `RUST-HELPERS-ASSESSMENT.md` (six paths, none passes Rule 3) and Plan 00529 with its README row.
- After the reboot: the assessment and Plan 00529 were reworded so the secret-file guard is the N465 Python fix, not a
  Rust candidate and not an owner decision.

## Evidence that the check fails on a planted slowdown

The test plants a `sitecustomize.py` on `PYTHONPATH` that burns 6 s of CPU in every Python process the check starts,
against a test budget of 4 s CPU. Nothing in the script under test is stubbed. Run on this branch after the reboot:

```
pytest tests/integration/test_startup_budget_planted_slowdown.py tests/unit/scripts/test_check_startup_budget.py
22 passed in 23.06s
```

The two integration cases assert exit 0 and `PASS` for the unplanted start, and exit 1 and `FAIL` for the planted one.
The earlier manual run (recorded in PLAN.md Task 3.1): clean PASS at 1.39 s; with 1.5 s planted, FAIL at 2.92 s, exit 1.

Flake resistance: the budget is CPU seconds, which do not grow with host run-queue length, and a failing round is
measured again before the check fails.

## Limits

- The red output of the unit tests written first was not kept before the reboot, so it is not quoted here.
- No full suite was run (targeted QA only, per the brief).

## Final QA

First run on 240fc6e4d: 36/40 passed; pyright (an `__doc__` possibly None in the budget script), plan_qa
`header-body-coherence` (every box ticked under In Progress) and `stats-recount` (Active 57 vs 58) failed. Fixed in the
next commit: `(__doc__ or "")`, an unticked "merged and archived" criterion for the coordinator, and Active 58. The
journal-freshness advisory names Plan 00477 and is not this plan's.
