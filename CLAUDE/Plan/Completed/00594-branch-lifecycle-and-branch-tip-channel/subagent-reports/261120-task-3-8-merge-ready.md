# Task 3.8: brought up to v3.76.0 and made merge-ready (independent security review still to come)

Branch `agent-a20c91c23eca4e56e-43e33957`, worktree
`.claude/worktrees/agent-a20c91c23eca4e56e-43e33957`.

## What was done

- `git merge origin/main` (v3.76.0, `de8833b5b`) gave merge commit `fd2076fdc`. The merge was
  clean: the branch and the release touch no common file. The release moved the old
  `UNRELEASED/` notes into `v3/v3.75.0-to-v3.76.0/`. This branch's note
  `010-agents-may-delete-an-unmerged-remote-branch-that-holds-nothing-unique.md` was not part of
  that move and is now the only release note in `UNRELEASED/release-notes/`, so its number is free.
- Composition with Plan 00626 (shipped in v3.76.0): the surviving-content tier was already
  re-expressed on 00626's `prove_remote_merged` before this merge (`6a0d1e123`). The release's
  23 commits do not touch `remote_branch_proof.py`, `branch_cleanup.py` or `destructive_git.py`.
  Every source caller of the proof (`branch_cleanup._remote_note`, `_proven_remote`,
  `delete_remote_branches`, `destructive_git`) goes through the one proof, and none of them caches
  a verdict. The sweep's candidates are limited to `REMOTE_CLEAN_STATES`, so the sweep does not
  start deleting unmerged branches because of this tier. The release's
  `test_remote_delete_proof_remote_default.py` passes on the merged tree.
- Docs (`246c6e379`): note 010 now states three things. The remote default is always confirmed live
  (F-BYPS Finding 1). Every push URL that names a different repository must agree (Finding 3).
  The tier judges tip content only, so intermediate revisions are lost (the F-BYPS
  "net-diff only" item). `docs/guides/CONFIGURATION.md` used to point a surviving-content delete at a
  bare, unleased `git push --delete`. It now points at the leased `delete-branch --remote-only`.

## QA

`llm_qa.py changed --allow-unmapped` did not start: the host QA lock was held by another
worktree's run for the whole 600 s wait (exit 4). As the brief allows, I ran these directly against
the worktree's `src` (PYTHONPATH, the main checkout's venv):

- ruff, black --check and mypy on the 5 changed source files plus the 19 test files: all clean.
- pytest on 19 files: the 5 new or changed proof/delete files, plus the remote-delete,
  branch-sweep, empty-commit and destructive_git suites from main, including
  `test_remote_delete_proof_remote_default.py` and `test_destructive_git_unenumerated_spellings.py`.
  Result: **464 passed**, 0 failed. The order-dependent `test_empty_commit_proof` case that was journalled on 20 November
  did not recur.
- Not run here: the full gate (the coordinator's). The CI git version was not run either. Local git is
  2.47.3, and CI runs 2.56.1, which records `refs/remotes/<r>/HEAD` on fetch. None of the new tests deletes
  the remote HEAD (they only `set-head origin main`), so the v3.76.0 CI-fix class does not apply,
  but this has not been run on git ≥ 2.48.

## Remaining before merge

1. **Independent security review.** The F-BYPS review covered `b0c596d5f`. These later fix commits
   have not been reviewed: `c20fd1570` (default anchored in the live check), `79b8fa956` (push-URL
   confirmation), `e8320a726` (pushInsteadOf pinned). The review should cover those three
   commits and the merge.
2. Full QA gate (coordinator), then `--no-ff` merge. Never while `untracked/release-state.json`
   exists.

## Owner decisions

- **F-BYPS Finding 4 (accepted residue):** should the hook DENY a raw `git push --delete` of a
  surviving-content branch and point to `delete-branch --remote-only`? The leased route closes the
  proof-to-push race, and denying would change the contract of a command that is allowed today. Holder leases are
  not possible in git, so they stay residue.
- Finding 2 (`gh pr close --delete-branch`, `gh api -X DELETE .../refs/heads/...`) is already
  on main's ledger as **N680**. It was not ledgered again here.
