# N464 report: worktree-reap removal timeout and DRY-RUN label

Work commit `e4c7b64b9` (code, tests, release note); this report and the ledger flip are the following commit.

## Verified before coding

`run_git` never raises on a timeout: it returns `CompletedProcess(argv, GIT_TIMED_OUT, "", str(exc))`, with `GIT_TIMED_OUT = 124` (`utils/git_repo.py`). The observed "timed out after 5 seconds" text is that `stderr`. So the detection is a return-code test, not an exception handler.

## RED (6 failed, 34 passed)

```
AttributeError: type object 'Timeout' has no attribute 'GIT_WORKTREE_REMOVE'
assert 'interrupted' in "git refused to remove /repo/.claude/worktrees/agent-aaa-111: ..."
assert 'git worktree prune' in 'git refused to remove /repo/.claude/worktrees/agent-aaa-111: timed out'   (x2)
assert 'DRY-RUN' not in 'DRY-RUN git...t did not.\n'   (x2, tests/unit/daemon/test_cli_worktree_reap.py)
```

Tests added: `TestRemovingATreeIsNotAMetadataQuery` (5) in `tests/unit/core/test_worktree_reap_action.py`; `TestAFailedRemovalIsNotLabelledADryRun` (3, including a real dry run still reading `DRY-RUN`) in `tests/unit/daemon/test_cli_worktree_reap.py`.

## GREEN

- `constants/timeout.py`: `Timeout.GIT_WORKTREE_REMOVE = 300`, with a comment saying why it is not `GIT_CONTEXT`. The existing `GIT_WORKTREE = 30` is the WorktreeCreate/Remove hook budget and is tied into the chain-deadline tables, so I did not reuse or raise it.
- `core/worktree_reaping.py`: the removal passes `timeout=Timeout.GIT_WORKTREE_REMOVE`; a `GIT_TIMED_OUT` result returns `removed=False` with "interrupted ... may be partial ... Recover with git worktree prune, then git branch -d <branch>" (no branch clause for a detached worktree) and does not touch the branch. The docstring's never `--force`, never `-D` contract is intact, extended with a paragraph on the timeout.
- `daemon/cli.py`: under `--reap`, an unremoved worktree prints `FAILED `; without it, `DRY-RUN`.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/061-worktree-reap-gives-the-removal-time-to-finish.md` (renumbered to 065 at merge: 061–064 were taken on `main`).
- N464 marked fixed in `NIGGLES.md` and `STATUS-INDEX.md`.

## QA

- `./scripts/qa/llm_qa.py changed`: exit 1, 39/40. The only failure was `changed_tests` reporting `timeout.py`, `worktree_reaping.py` and `cli.py` as unmapped `[too-broad]` (its 262 tests all passed).
- `./scripts/qa/llm_qa.py changed --allow-unmapped`: exit 0, 40/40 PASSED, `changed_tests` 262 passed, 0 failed.
- pytest by path on the four reaping test files: 74 passed.
- No QA exclusion or allowlist entry added.

## Notes

- Setup: the worktree existed without a venv, so I ran `ensure_venv` plus `uv sync --frozen --all-extras` with the same helpers `setup_worktree.sh` uses. The script itself refuses an existing directory.
- The 300 s value is a judgement, matching `GIT_BUNDLE_CREATE`. A tree large enough to exceed it still gets the interrupted/partial message and recovery.
- Disagreement with the brief: none. The ledger records the work commit; the final HEAD is the follow-up that carries this report.
