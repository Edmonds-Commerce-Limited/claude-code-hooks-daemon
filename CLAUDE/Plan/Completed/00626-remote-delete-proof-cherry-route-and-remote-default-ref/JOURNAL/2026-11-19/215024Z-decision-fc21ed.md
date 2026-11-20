## 21:50 · decision · —

Closing Plan 00626 as Complete. It merged to main at `201a17fae`; the work branch is gone.

Both defects were fixed test-first. Defect 1, the over-refusal: the cherry route is restored in `core/remote_branch_proof.py` `_judge_offline`. Defect 2, the unsafe delete:

- Remote proof targets are the remote default only.
- The remote's live tip is confirmed through `git ls-remote`.
- The proof cache no longer authorises a delete.
- `auto` default detection reads `refs/remotes/<remote>/HEAD` only.
- Merged-pool counting is keyed by the remote default sha.

An independent security review passed (`subagent-reports/261119-security-review.md`). It found 6 intended cherry-route loosenings, each justified, and 6 unsafe deletes that are now refused.

The full QA gate ran 45 of 46. The only failures are two tests that also fail on main's code on this host:

- `test_branch_pressure` has a stale expectation, fixed on the Plan 00623 branch.
- Playbook probe #125 is ledgered as N673.

The holding-area artefact is release note `003-remote-delete-proof-remote-default-and-cherry-route.md`, cited in Success Criteria.

One follow-up is ledgered as N674: a stale `origin/HEAD` after a remote default rename needs a live `ls-remote --symref` check.

Decision: close the plan Complete and archive it in the same commit as this journal entry.
