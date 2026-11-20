# Probe #350 rewritten without --dry-run

The conflict-marker commit gate acceptance probe `git commit --dry-run && cd - && git commit --dry-run` is now `git commit -m acceptance -- no-such-acceptance-path && cd - && git commit -m acceptance -- no-such-acceptance-path`, expected ALLOW. The secret guard's denial of a dry run after a computed `cd -` stays; only the probe changed.

- The dry-run skip is still covered by the unit test at `tests/unit/handlers/pre_tool_use/test_conflict_marker_commit_gate.py` (`git commit --dry-run`).
- The chained probe is judged on its first half, so it allows on a clean index and denies with a marker staged; a new unit test pins both. The staged-marker loop now covers only the `cd - ` probes.
- Harness run in the worktree after a worktree daemon restart: 1 of 259 probes fails, #125 (known, ledger N677).
