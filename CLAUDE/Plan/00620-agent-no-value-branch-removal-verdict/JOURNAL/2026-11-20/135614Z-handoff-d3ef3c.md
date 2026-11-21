## 13:56 · handoff · —

Task 2.3 progress (twelfth agent).

- The near-miss ALLOW probe of branch_reject_dispatch_gate was denied by a strict
  dispatch_declaration. This was verified red. Its prompt now declares 'not plan work'
  plus a destination, and a strict-handler test pins it (3d328b6f0).
- The digest core landed red then green (daa7515f1, 67283be03). Its parts:
  - an identity watermark keyed by the sha256 of each entry's canonical JSON, so a line
    union-merged after a mark-read stays undigested;
  - listing never writes;
  - mark-read unions exactly the listed snapshot into `<state_dir>/digest.json`;
  - a damaged ledger, keep or watermark raises;
  - `branch_still_at_tip` separates present, absent and git failure.
- approve_removal is pinned to answer the same whatever the digest state.
- Residue: an agent can mark digest entries read. This hides them from the digest
  only, and unlocks nothing.
- Open: the verdict_id == nonce check is not validated, which is a possible reuse by
  copy. It goes to Task 2.4 adversarial tests.
- Handoff: subagent-reports/261120-task-2.3-core-handoff.md. The CLI digest command,
  the session-start count, the docs and all of Task 2.4 remain.
