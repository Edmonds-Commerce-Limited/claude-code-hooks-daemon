# Review fix (3) handoff (worktree agent-aec4691c2826688fd-18abb934)

Supersedes the "Left to do" list in `261120-review-fixes-handoff.md`: fix (2) and the DESIGN.md
marker docs are done, and only fix (3) remains.

## Done and pushed

- `1c20d5469` **Fix (2), D-EXEC F1.** `daemon/branch_safety.py` adds `_compare_and_delete`, which runs
  `git update-ref --no-deref -d refs/heads/<name> <approval.tip>`.
  - It refuses a symref (rc 0 from `symbolic-ref --quiet`) and fails closed on any rc other than 1.
  - It refuses a branch checked out in a worktree, and fails closed when the listing raises.
  - Either refusal goes through `record_git_refusal`.
  - On success, `_remove_branch_config` drops `branch.<name>.*`. It only logs a failure and never refuses.
  - Tests: `TestCompareAndDelete` (6) in `tests/unit/core/test_branch_reject_delete.py`.
  - DESIGN.md section 3 (the consumed/, consumed-agents/ and cancelled/ markers) and section 10
    (the compare-and-delete and its residue) are updated, as is the journal.
- 643 tests pass in `untracked/scratch/run-br.sh`. ruff, black and mypy are clean.
- Git probes (2.47) are in `untracked/scratch/gt/probe*.py`. Without `--no-deref`, a symref
  delete removes the TARGET. With it, the old-value compare is skipped for a symref.

## Left: fix (3), F-BYPS F2 (reviewer failed or killed)

The design settled with the advisor follows the earlier handoff's rule rather than the
dispatch's "e.g. 3 attempts". Say so in the report.

1. **Unresolved attempts.** These are DERIVED, not just recorded. Count every request with a
   `dispatches/<nonce>.json` and no `verdicts/<nonce>.json`, related to this work by the
   `related_keeps` relation: same branch, same tip, or a shared inventory commit. Extract that
   relation into one shared helper that both the keep and attempt checks use. Union the result
   by nonce with the `failures/<nonce>.json` trace records, so nothing counts twice. This also
   covers killed reviewers (no stop at all), withdrawn verdicts and in-flight reviews. Blocking
   in-flight reviews is intended; document it.
2. **Trace record.** Add `failures/<nonce>.json` (reason, branch, tip, time), written in
   `record_review_stop` at the `facts.damaged`/reply-mismatch branch and the parse-failure
   branch (both currently `return STOP_IGNORED`, core/branch_reject.py ~1413-1418).
3. **Rule.** Add the named constant `MAX_UNRESOLVED_REVIEWS = 2`. Each unresolved attempt adds
   one required reviewer to `max(keep-need, rate-need)`. Two close the route for that work, with
   a message saying a human must decide.
4. **Admission.** `admit_request(..., unresolved_attempts: int, ...)` takes the count as a
   REQUIRED parameter with no default. Recompute it in `issue_requests` and in `approve_removal`;
   the latter is what stops older no-value verdicts meeting the raised count. Add a new
   `RejectStore` listing of requests that fails closed the way `verdicts_for` does: the file name
   must equal the nonce, and damage raises.
5. **Fixtures.** `test_a_verdict_whose_id_is_not_its_nonce_refuses` withdraws a verdict, which
   leaves an unresolved dispatch. It still refuses, which is fine. Check every other fixture that
   dispatches without a verdict, and do not loosen the rule to make one pass.
6. **Tests first.** Cover these cases:
   - an unparseable reply raises the bar, then refuses;
   - a dispatch with no stop does the same;
   - an older no-value verdict cannot meet the raised count;
   - an empty commit (a new tip, shared commits) does not reset the count.
7. **Docs.** Update DESIGN.md section 3 (`failures/`) and section 6, RULINGS.md, and PLAN.md
   Known gaps (~line 65, "A killed reviewer keeps its verdict…").

## Notes

- The commit trailer is `Co-Authored-By: Claude Opus 5.5`. That follows the harness attribution
  reminder and the earlier commits; the dispatch asked for Sonnet 5.5.
