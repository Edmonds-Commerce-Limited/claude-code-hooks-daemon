# Fact-checker report 4 (Plan 00630)

14 claims checked: 12 verified, 1 refuted, 1 unverifiable.

- Refuted: DESIGN.md quoted the module header of `core/branch_reject.py` as saying
  "No remote delete. R-GIT-PUSH-DELETE-REMOTE is unchanged". The header says no
  such thing (it never mentions remote). Replaced with a description of the
  behaviour; the quote appeared only in 00630 DESIGN.md (not in 00633/00636/00637).
- Unverifiable at check time, now checked: the ledger path and rate limits.
  `branches.reject.ledger_path` defaults to `.claude/branch-removals.jsonl`
  (verified). Rate: `window_days` 7, `two_reviewer_after` 3, `refuse_after` 10
  (config/models.py `BranchRejectConfig`). Plans 00637/00633/00636 state no numeric
  limits and have no DESIGN.md section 21, so nothing there needed correcting.
