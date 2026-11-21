# Review fixes: handoff (worktree agent-aec4691c2826688fd-18abb934)

## Done and pushed

- `a4b4ae605` **Fix (1), F-BYPS F1 / D-PATH F1 (blocks merge).** Single use, the 2-reviewer step and the rate cap now read shared state.
  - In `core/branch_reject.py`:
    - `RejectStore.claim_consumed` creates `consumed/<verdict_id>.json` and `consumed-agents/<sha256(agent)[:32]>.json` exclusively with `os.link`, in `record_removal`, immediately before the ledger append.
    - `cancel_removal` writes `cancelled/<first verdict id>` on a git refusal (`record_git_refusal`).
    - `used_state()` is the one reader: ledger ∪ shared markers. It is used by `issue_requests`, `approve_removal`, `record_removal` and `build_digest`.
    - `_all_with_paths` raises when a kind path exists but is not a directory.
  - The accepted-residue test is replaced by `TestSingleUseAcrossCheckouts` (5 tests) in `tests/unit/core/test_branch_reject_forge.py`.
  - PLAN.md Known gaps (Q8 resolved) and Success Criterion 1 are updated, as is the `BranchRejectConfig` docstring.
- `b22a393f3` **Fix (4), the recorder crash.** `read_review_transcript` reads content only through the dict check. The SubagentStop handler also catches LookupError, AttributeError and TypeError.
- State: 637 tests in the 12 branch_reject files, branch_safety and branch_sweep all pass. ruff, black and mypy are clean on the changed files.

## Left to do

### Fix (2), D-EXEC F1: compare-and-delete

- **Where:** `daemon/branch_safety.py` `_delete_rejected` (~line 956).
- **Change:** replace `_git(repo, *delete_argv_for_tier(...), name)` with `git update-ref -d refs/heads/<name> <approval.tip>`, using `branch_ref(name)` from `utils.git_repo`. Git refuses if the ref no longer equals the tip. On refusal, keep the existing git-refused path: the message plus `record_git_refusal`.
- **Caveat:** `update-ref -d` does NOT refuse a branch checked out in a worktree, which `git branch -D` does. Re-check `worktree_branches(repo)` immediately before the delete and fail closed. It also leaves the `branch.<name>.*` config behind; decide whether to `git config --remove-section`.
- **Test first:** monkeypatch `branch_reject.record_removal` with a wrapper that calls the real one, then runs `git branch -f feat <other sha>`. Assert the branch survives at the new sha, `report.deleted == ()`, and the ledger holds a LedgerLine plus a LedgerRefusal. Check the existing lock-file refusal tests in `test_branch_reject_delete.py` (lines 284-315 and 363-385) still pass.

### Fix (3), F-BYPS F2: failed or killed reviewer

- **What counts as unresolved:** a killed reviewer emits no stop, so count from existing records. An unresolved attempt is a request that has a dispatch record and no verdict file. That covers unparseable replies, killed reviewers, withdrawn verdicts and in-flight reviews; in-flight blocking is intended, so document it.
- **Explicit trace:** still write a `reviewer-failed` record (for example `failures/<nonce>.json` with reason, branch, tip and time) in `record_review_stop` at the `facts.damaged` / reply-mismatch branch (~1307) and the parse-failure branch (~1311).
- **Relating attempts:** relate them to the work the way `related_keeps` does (same name, same tip, or a shared commit). Keying on tip alone lets an empty commit reset the limit.
- **Rule (a named constant, documented):** each unresolved attempt adds one required reviewer. A second unresolved attempt closes the route for that work, as two keeps do.
- **Admission:** make the attempt count a REQUIRED parameter of `admit_request` (no default of 0, which would fail open). Pass it from both `issue_requests` and `approve_removal`; this needs a new `RejectStore` method listing requests.
- **Tests:** an unparseable reply and a dispatch with no stop each raise the bar and then refuse. Older no-value verdicts cannot meet the raised count.
- **Docs:** update PLAN.md Known gaps (line ~65, "A killed reviewer keeps its verdict…").

### Docs still owed

- DESIGN.md: the state layout section and the delete section should describe the `consumed/`, `consumed-agents/` and `cancelled/` markers.

## Notes

- Commit trailers use `Co-Authored-By: Claude Opus 5.5`, following the harness attribution reminder. The dispatch asked for Sonnet 5.5, which conflicts with it.
- Test runner (run from inside the worktree): `untracked/scratch/run-br.sh` is gitignored, so recreate it from the dispatch's QA command if needed.
