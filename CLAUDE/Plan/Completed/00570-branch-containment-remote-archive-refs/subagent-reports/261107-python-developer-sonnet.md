# Plan 00570 report: remote proof for branches held outside refs/heads (issue #166)

## RED (before the fix)

Collecting `tests/unit/utils/test_remote_refs.py` and `tests/unit/core/test_remote_archive_proof.py`
failed:

```
ImportError: cannot import name 'TIER_REMOTE_HELD' from 'claude_code_hooks_daemon.daemon.branch_safety'
2 errors during collection
```

## What changed

- `utils/remote_refs.py` (new): one shared helper. `list_remote_refs` makes ONE `git ls-remote <remote>` through
  `run_git` with the new `Timeout.GIT_LS_REMOTE` (30 s); a failure is returned in `RemoteRefs.failure`, never
  raised and never proof. `holder_of` accepts a ref whose sha equals the tip, or descends from it when the object
  exists locally and `merge-base --is-ancestor` holds. `LazyRemoteRefs` defers the call until a branch actually needs it.
- `core/branch_inventory.py`: `build_inventory(..., remote_refs=)`; a branch the offline answer calls NOWHERE becomes
  the new `Containment.REMOTE_UNFETCHED` when a listed ref holds it. The cache stores only the offline answer.
- `daemon/branch_safety.py`: new proof tier `remote-held` in `classify_branch`/`delete_branches(remote=)`, placed after
  patch-equivalent and before the content tier; `held_by` names the ref; a failed listing is named in an unproven verdict.
- `core/branch_sweep.py`: offline wording now says "no fetched remote-tracking ref of <remote> holds its commits" with the
  hint that a remote may hold it outside `refs/heads` and `branch-sweep`/`delete-branch` can verify; remote-held branches
  get no push advice; a failed listing prints a warning.
- `daemon/cli.py`: `cmd_branch_sweep` and `cmd_delete_branch` (explicit paths only) pass the lazy listing / `remote`.
  `branch-sweep --clean` and every hook path stay offline.
- Docs: `docs/guides/CONFIGURATION.md` branches section; handler guidance in `handlers/session_start/branch_sweep.py`;
  release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/004-branch-containment-remote-archive-refs.md`.

## Deviations from the brief

- The coordinator's correction was applied: `delete-branch` goes through `classify_branch`, not `containment_of`, so it
  has its own proof kind and shares only the ls-remote helper. Plan 00558's batched helper (`_live_remote_tips` in
  `destructive_git.py`) lists per-branch heads patterns for the remote-delete guard; it cannot list non-heads refs, so it
  was not reused. The new helper follows its fail-closed and `GIT_TERMINAL_PROMPT=0` conventions.
- The call is lazy (made only when something would otherwise be unproven/nowhere), so a plain merged delete or a clean
  sweep never touches the network.
- `destructive_git.py` push advice (hook path) was left as is; it is a different guard with its own wording.

## Tests

`tests/unit/utils/test_remote_refs.py`, `tests/unit/core/test_remote_archive_proof.py`, helper
`tests/support/archive_remote.py`. Covers archive-ref proof, descendant proof, no push advice, failure fallback, one
ls-remote per run, laziness, and a watcher proving the inventory/session-summary path never runs `ls-remote`.
Related existing suites (inventory, sweep, branch_safety, delete-branch CLI, sweep CLI, session-start handler):
309 passed.
