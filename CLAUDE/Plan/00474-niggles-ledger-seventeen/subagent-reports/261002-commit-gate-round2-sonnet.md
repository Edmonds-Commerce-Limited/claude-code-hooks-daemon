# Commit-gate same-command branch: review round 2 fixes

Branch: worktree-commit-gate-same-command (worktree /workspace/untracked/worktrees/worktree-commit-gate-same-command)
Review being answered: /workspace/untracked/agent-reports/auto/261002-164317-commit-gate-review-acommit-gate-review-464628e5d5836d92.md

## Fix 1: merge with main

- git_repo.py: kept main's `_child_environment` (strips inherited relocating variables from os.environ, then the caller env, then GIT_OPTIONAL_LOCKS=0). `read_blobs` now calls `_child_environment(env)`, so a caller's scratch GIT_OBJECT_DIRECTORY, alternates and GIT_INDEX_FILE reach git.
- TRIAGE-ledger-466.md: the two sides differed only by the N85 row (`FIXED f3d13077e`) and column padding; main's side contains both sides' content, so it was taken whole.
- Tests (tests/unit/utils/test_git_repo.py, class TestReadBlobs): a blob that exists only in the scratch object store is returned when the caller passes the scratch env and is absent without it; a caller GIT_INDEX_FILE reaches git and GIT_OPTIONAL_LOCKS stays 0. Note: `cat-file --batch` does not read the index itself, so the object-store test is the behavioural one and the index variable is checked at the process boundary.
- Merge commit: bec9719c7.

## Fix 2: an incomplete simulation denies

- staging_simulation.py: new `SimulationIncompleteError`. The fallback is now `git add -A --ignore-errors`; exit 0 or 1 (1 is "some files skipped", e.g. an embedded repository with no commit) counts as complete, any other status (127 for timeout or git unavailable, 128 for a fatal such as a leftover index.lock) raises. The message says to run `git add` as its own call and commit as a separate command. Scratch directory is still removed (the raise happens inside the TemporaryDirectory block).
- Gates: sensitive_content (matches returns True so the chain reaches handle, which denies), remote_docs_commit_gate (always deny), staged_lint_gate (deny in block mode, advisory in warn), docs_qa_commit_gate and plan_qa_commit_gate (deny when commit_gate_mode is block, advisory otherwise). Deny-in-block-only for the three configurable gates is a judgement call: in warn mode those gates already only advise.
- Tests: the old test that locked in the allow was inverted (test_staging_simulation.py, TestAnIncompleteSimulationIsNotAnAnswer: failed fallback raises, timeout raises, message wording, scratch cleanup, embedded repository still stages leak.txt). Gate tests added in test_sensitive_content_same_command.py (handle denies, matches selects) and test_staged_lint_gate.py (block denies, warn advises). No new tests for the docs QA, plan QA and remote docs gates' handling (same three-line pattern, not covered by a dedicated test).

## Fix 3: split-index repositories

- The simulated adds run as `git -c core.splitIndex=false add ...`. Test builds a split-index repo, runs the simulation, asserts the set of `.git/sharedindex.*` files is unchanged. Confirmed red without the fix by setting `_NO_SPLIT_INDEX = ()` (1 failed), green with it.

## Cheap non-blocking items done

- Removed `extra_directories` from git_facts.py, docs_qa/context.py, plan_qa/context.py (and docstrings).
- Removed the redundant `if self._env is None` branches in git_facts.py (`_run`, blob reads); two test fakes (test_git_facts.py, plan_qa/test_context.py) now accept `env`.
- Module docstring of staging_simulation.py now states the clean-filter / fsmonitor exposure (review item 8).
- Left alone: shared simulation per dispatch (4), residual `git apply --cached` / `update-index --add` shapes (7, still allowed and recorded, see probe), combination cap doc (9).

## Verification

Python: /workspace/.venv/bin/python, PYTHONPATH set to the worktree src.

- Targeted tests (12 files: test_staging_simulation, test_git_repo, test_sensitive_content_same_command, test_sensitive_content, test_staged_lint_gate, test_docs_qa_commit_gate, test_plan_qa_commit_gate, test_remote_docs_commit_gate, test_git_facts, plan_qa/test_context, tests/daemon/test_init_config.py, test_blocking_handler_evasion.py): 954 passed.
- ruff check on all touched files and src: clean. black --check on touched files: clean. mypy on touched files: clean.
- scripts/qa/check_dangerous_invocation_corpus.py: exit 0, "Every recorded verdict holds (29 rows: 8 covered, 9 open, 12 accepted)".

## Reviewer probes re-run

- timeout_decision.py: `slow DENY 5.02` (was `slow allow 5.02`); plain DENY 0.02.
- extra_probe.py (fresh repos under untracked/scratch/probe-r2): add-plus-ignored DENY/RECORDED, add-p-unreadable DENY/RECORDED, add-var-nested-repo DENY/RECORDED (was allow while recorded), add-chmod DENY/RECORDED. Still allow while RECORDED: apply-cached and update-index-add (the residual shapes, review item 7, same as main).
- Split-index (safety/split repo via sensitive_content handle): decision deny; sharedindex.\* file set identical before and after.
- The 5s timeout case still costs 5s per gate; shared simulation (item 4) is not done.
