# Full-gate failure triage (gate run at 8c1ebe38e)

The gate failed with 7 failing test entries, which come from 3 distinct tests, plus magic_values,
error_hiding and dependencies. origin/main (b5d3b332a) was merged in with no conflicts.

Commits on the branch:

- `a7f2af3b6`: the error-hiding and magic-value fixes.
- `a5e51bb81`: the doc-write-jail wiring test is now hermetic.

## Real failures on this branch, fixed

- **magic_values**, `tests/unit/core/test_submodule_ignore_proof.py:135,150`. The tests now use
  `timeout=Timeout.GIT_CONTEXT`, the same budget that `remote_branch_proof` itself passes. The
  check now passes.

- **error_hiding**, `daemon/branch_safety.py:670` (`_gitlinks_held`). A `ProofUnavailableError` now
  goes through `utils.deliberate_swallow.log_and_continue` with a stated reason, and the function
  still returns False. The branch therefore stays refused (it fails closed). There is a new test,
  `TestGitlinkGateFailsClosed::test_an_unavailable_proof_is_logged_as_a_refusal`. The existing test
  `test_an_unavailable_proof_is_not_held` still passes.

- **`test_doc_write_jail.py::TestSessionWiring::test_every_checkout_of_the_repository_is_protected`**
  failed in the py3.12 leg only. The cause is environmental, a race:

  - The jail reads `git worktree list` once, when conftest is imported.
  - The test re-listed the worktrees live.
  - The worktree `.claude/worktrees/idle-threshold-100k` changed between those two moments during
    the run.

  The fix:

  - conftest keeps the set it armed (`_DOC_WRITE_JAIL_PROTECTED`).
  - The test asserts that the environment set equals that armed set.
  - The test also asserts that the armed set covers this checkout and the main checkout, which it
    finds from the git common dir.

  This was test-first. A red test monkeypatches `checkout_roots` to add a later worktree.

## Main drift (also fails on main itself, b5d3b332a)

- **`tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan::test_repo_is_clean_under_widened_scope`**
  - It fails on main with
    `handlers/session_start/optimal_config_checker.py:592 [log-and-continue]` (the
    `logger.debug(...); continue` in `_idle_threshold_value`).
  - It also fails with `:630 [silent-fallback]` (`except ValueError: tokens = None` in
    `_check_idle_threshold`).
  - Both came in with c39e8b195 (idle-threshold-100k). I reproduced the failure in /workspace with
    main's venv.
  - The fix on main is trivial: route `:592` through `log_and_continue(..., reason=...)`, and
    replace the `:630` try/except with a parse helper that logs or reports the unparsable value.
  - **The fix is not on this branch.** This test stays red here until main is fixed and merged in
    again.

## Environment and harness (not caused by this branch)

- **`tests/acceptance/test_playbook_harness.py::...::test_every_executable_probe_matches_its_expected_decision_and_reason`**
  - The failing probe is #125, `WorktreeFileCopyHandler`, "rsync from worktree to main repo".
  - The probe is `bash -n -c 'rsync -a --dry-run untracked/worktrees/acceptance-probe-absent/src/ src/'`
    with `cwd=$MAIN_CHECKOUT_DIR` (/workspace).
  - `tests/acceptance/conftest.py::_discover_socket` finds the WORKTREE's own daemon, whose project
    root is the worktree. Its `project_containment` (priority 14) treats the rsync destination
    `/workspace/src/` as outside the root and denies it first. `worktree_file_copy` comes later at
    priority 15. The cp probe passes only because containment does not judge cp destinations.
  - I called both handlers' `matches()` directly on the source at 3aa108bd2 and 7e679d8fc (N398),
    at b4b2b0462^ and at HEAD. All of them give the same verdicts, so this is not a regression on
    this branch. The branch's only handler change is `destructive_git.py`.
  - The latent defect is in `playbook_harness.main_checkout_root`. It assumes that "the daemon the
    harness talks to guards the checkout that holds it". That only holds when the socket found
    belongs to the main checkout's daemon (for example, when `CLAUDE_HOOKS_SOCKET_PATH` points
    there).
  - **The gate fails again in any worktree whose own daemon is running.**
  - The fix belongs in how the harness plans `$MAIN_CHECKOUT_DIR` probes, for the coordinator to
    decide. The handler, its priority and the expected patterns should all stay unchanged.
  - I could not confirm that this passes on main: main's live daemon is stale (source and config
    fingerprints), and I did not restart it.
- **dependencies (deptry)**
  - Infrastructure. After the merge, the worktree venv no longer matched the lock hash
    (`abf0537ced66` against `b4c24b4484e9`).
  - After `bin/hooks-daemon repair`, `llm_qa.py dependencies` passes with 0 issues.
  - Why the original pre-merge run was left "pending" was not established.

## Targeted QA run

- pytest passed:
  - `test_submodule_ignore_proof.py` and the `branch_safety` daemon tests: 117 passed.
  - `test_doc_write_jail.py`: 28 passed.
- ruff, black and `mypy --strict` are clean on the touched files.
- llm_qa results:
  - magic_values: 0.
  - dependencies: 0.
  - error_hiding: only the two main-drift findings remain.
