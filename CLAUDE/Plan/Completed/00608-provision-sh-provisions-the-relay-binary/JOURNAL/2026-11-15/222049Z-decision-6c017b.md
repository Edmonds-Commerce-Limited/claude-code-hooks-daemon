## 22:20 · decision · — — Branch ready; merge gated on a semgrep environment fault; goal retracted

Plan 00608 state and why the supervisor goal cannot be satisfied from inside this session.

Built and pushed: branch `agent-a85cf266bd3c1c30d-57f43a44` (provision.sh runs the relay step; tests 71 relay_deploy and 92 provision_sh pass). Targeted QA on a still tree: 40 of 43. The failing check is `semgrep`, an environment fault: the pinned semgrep 1.185.0, obtained through `uv tool run`, exits 2 with "Failed to find semgrep-core in PATH or in the semgrep package", from the main checkout as well as the worktree. `uv cache clean semgrep` and a fresh download did not change it, although the semgrep-core binary exists in the cached site-packages and runs when called directly. The other two non-passes follow from it (`project_handlers` and `changed_tests` are marked not meaningful when the semgrep detector fails; 1171 changed tests pass, 0 fail). The one unmapped file (`install/relay_deploy.py`, too-broad) is allowed under the advisor rulings.

Why the goal cannot be met: the merge of the branch waits on a semgrep run that this container cannot perform, so it is gated on an external fault, not on more work here. Merging without that check would skip a QA gate; the release pull request's CI runs the whole gate and is the backstop. The open follow-ups (start the repair at daemon startup, log the silent failure branch, show repair state in status) are queued after the merge. Plan 00594 is blocked on the second client seat and the release decision.

Next for a human or a later session: repair semgrep under uv in this container (the pin comes from Plan 00607's change), re-run `scripts/qa/run_semgrep_check.sh`, then merge the branch with --no-ff.
