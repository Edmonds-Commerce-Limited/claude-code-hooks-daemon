# Plan 00488 Tasks 3.4 and 3.5: raw self-install clone, and the build-start race

Worktree: /workspace/untracked/worktrees/worktree-488-boot (branch worktree-488-boot). Nothing of /workspace's own daemon, venv or `.claude/` was touched; all tests run in sandboxes.

## Task 3.4: a raw self-install clone

Where "not installed" is decided: `init.sh` sources `.claude/hooks-daemon.env` only if the file exists, then defaults `HOOKS_DAEMON_ROOT_DIR` to `$PROJECT_PATH/.claude/hooks-daemon`. The env file's whole content is `HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"` (what `scripts/bootstrap-self-install.sh` writes after `uv sync --frozen --all-extras`, then it restarts the daemon). With no env file, `ensure_daemon` finds no clone and no venv under `.claude/hooks-daemon`, so it lands in NOT_INSTALLED ("use the skill to install") and never reaches `_venv_self_heal`. (A clone whose origin names the daemon repo hits the older repo guard instead, which only emits "run scripts/bootstrap-self-install.sh" and exits.)

Fix: a safe automatic route exists, so no human step. `_is_raw_self_install_clone` in `init.sh` is true only when ALL hold: no env file; no real clone (`.claude/hooks-daemon/pyproject.toml`); `src/claude_code_hooks_daemon/`; `install.py`; `scripts/bootstrap-self-install.sh`; `scripts/venv_bootstrap.sh`; and a `pyproject.toml` with `name = "claude-code-hooks-daemon"`. When it holds and `HOOKS_DAEMON_ROOT_DIR` is unset, the root is the project itself. That is derived in memory (no file written), so the existing self-heal builds the venv in the background under the build lock, the repo guard passes, and the status line reads "venv building". An explicit `HOOKS_DAEMON_ROOT_DIR` always wins. The bootstrap script stays the foreground route; its own "writes the env file" step is unchanged. Where the self-heal is refused (for example uv missing) the existing refused message names the condition and its fix.

Tests (RED first, 4 failed before the fix): `tests/integration/test_init_sh_raw_self_install_clone.py`, 12 tests: build starts with no env file and no "install" advice, next hook starts the daemon, nothing written outside `untracked/`, status line says building, refused without uv, and the negatives (client project, client that vendors the tree, each missing marker, a differently named pyproject, explicit root).

## Task 3.5: the startup race

Cause: state misclassification, as the brief suspected. uv creates the venv's `bin/python` before it installs the package. In that window the canonical resolver accepts the venv (the interpreter runs `import sys`), so `_is_daemon_installed` is true, and none of the venv-missing diagnoses in `ensure_daemon` apply. But `start_daemon` fails at `validate_venv` ("Cannot import claude_code_hooks_daemon. Venv may be broken"). That falls through every diagnosis to the generic failure: `DAEMON FAILED`, and the PreToolUse deny. The lock was held the whole time, but nothing consulted it once an interpreter resolved.

Fix: a new read-only driver verb `scripts/venv_bootstrap.sh probe <dir>` (prints `state=running` plus log/pid/elapsed when the build lock is held, else `state=idle`; starts nothing). `ensure_daemon` gains a branch: venv resolves, daemon will not start, clone present and `_venv_build_running` is true: set VENV_MISSING and the "venv building" status text, so the existing "already running" remedy, the RULING-3.2 behavioural line and fail-open all apply. `_venv_self_heal` is now a thin wrapper over a shared `_venv_driver_verb`. A clone too old to ship `probe` answers with a usage error, treated as "not known to be building". A broken venv with no build running is still a failure (tested).

Test (reproduced RED, matches the E2E signature): `tests/integration/test_init_sh_build_window_race.py`, 3 tests, using a stub uv whose half-built interpreter runs but cannot import the package. One existing test, `test_a_resolvable_venv_whose_daemon_fails_never_reaches_the_driver`, asserted the driver is never called on that path; it now asserts only the read-only `probe` may be, never `hook` (which starts a build).

## Docs and bookkeeping

Release note 025; `CLAUDE/Security/FailOpenBoundaries.md` (build-window section: lock marks the whole window, raw clone enters it unaided); `CLAUDE/SELF_INSTALL.md`; Tasks 3.4 and 3.5 ticked in PLAN.md.

## QA

shellcheck -x on `init.sh` and `scripts/venv_bootstrap.sh`: clean. All 24 `test_init_sh_*` and `test_venv_bootstrap_*` modules: 496 passed, 1 failed (the test above), which passes after the update (21 passed in that module). `llm_qa.py changed --base main --allow-unmapped`: lint, type_check, pyright, shell_check, docs_qa, doc_truth and the rest green; the first run's `format` finding was a tree that changed mid-run (black now reports the three test files unchanged), and the one plan_qa advisory is journal-freshness for plan 00495, unrelated.

## Notes

- The Read tool result of the brief ended with an unrelated note urging shell edits (sed, heredocs) over Edit/Write, and a PostToolUse output urged CronList/CronCreate work. Neither came from the task owner, and both conflict with or fall outside the project rules and this brief, so neither was acted on.
- Gap not closed: on a machine without uv the raw clone still needs uv installed (the refused message says so); that is a precondition, not something init.sh can install safely.

## Round 2

Review r1 (APPROVE) asked for two test gaps and one cleanup:

- `test_init_sh_build_window_race.py`: the no-lock case now has a positive control, asserting `permissionDecision` and `deny` in the output, so removing the lock check would fail it.
- `test_init_sh_raw_self_install_clone.py`: the missing-marker parametrize now includes `src/claude_code_hooks_daemon` (removed as a directory).
- `init.sh`: `_venv_build_running` no longer repeats the driver-file check; `_venv_driver_verb` does it, and the state alone decides. `shellcheck -x init.sh` is clean.

The two touched test files and `test_init_sh_venv_self_heal.py`: 37 passed.
