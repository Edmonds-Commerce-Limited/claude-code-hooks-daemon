# Task 2.6 (D10) — hermetic git environment for the test suite

**Branch**: `agent-aae8818320128143d-5523a881` · **Commit**: `772ef675` (fixture + proof test), plus the plan-tick commit that follows it.

## What changed

- `tests/conftest.py`: session-scoped autouse fixture `hermetic_git_environment`.
  It writes two EMPTY config files under `tmp_path_factory.mktemp("hermetic-git")`
  and points `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` at them, sets
  `GIT_CONFIG_NOSYSTEM=1`, clears every ambient `GIT_AUTHOR_*` / `GIT_COMMITTER_*`
  (including the `_DATE` pair) and `GIT_CONFIG_PARAMETERS`/`GIT_CONFIG_COUNT`, then
  pins a fixed identity (`Hooks Daemon Test <test@hooks-daemon.invalid>`,
  exported as `HERMETIC_GIT_NAME` / `HERMETIC_GIT_EMAIL`). Applied through
  `pytest.MonkeyPatch()` directly because the `monkeypatch` fixture is
  function-scoped; undone at session end. Every subprocess a test spawns
  inherits it, so `git init` + `git commit` in a bare temp dir succeeds with the
  same author on every machine, and nothing under `HOME` (identity, signing,
  `init.defaultBranch`, credential helpers, hooks paths) is visible.
- `tests/unit/test_hermetic_git_environment.py` (8 tests): global/system config
  are empty files outside `HOME`; `git config --get user.name` resolves to
  nothing outside a repo and in a fresh repo; `--show-origin` lists no value
  from under `HOME`; the env carries the fixed identity; a commit in a fresh
  repo is authored by it; no ambient dates leak.

## RED / GREEN

- RED: the test module failed to import (`HERMETIC_GIT_EMAIL` absent). The
  class-level RED is the direct observation: outside pytest, `git config --get user.name` in `/tmp` prints `joseph` with rc 0; the proof test asserts rc 1
  and empty output, so it fails locally without the fixture — which is the
  "revert a known instance, fails LOCALLY" proof Plan 00252 Task 2.2 asks for.
- GREEN: 8 passed.

## Suite results in the worktree venv (Plan 00252 Task 1.1 measurement)

- `tests/unit`: 16712 passed, 2 skipped, 1 xfailed, 2 errors.
- `tests/integration`: 3125 passed, 6 skipped, 1 error.
- All three errors are `no_test_writes_tracked_generated_docs` at TEARDOWN of
  unrelated tests (`test_check_git_history.py::TestHistoryBaseline`,
  `test_sensitive_content.py::TestInvalidConfiguration`,
  `test_forwarder_socket_stdin.py`), i.e. the tracked-doc guard catching an
  EXTERNAL rewrite of the worktree's `CLAUDE.md` during the run. The preserved
  copy differs from HEAD only in the ORDER of the handler one-liners (the daemon
  regenerating the file, same shape as HEAD's own "Auto: hooks daemon
  regenerated CLAUDE.md" commit). Those files pass in isolation (38 passed).
  Nothing depended on ambient identity or config; no test needed fixing.
- Left `CLAUDE.md` UNCOMMITTED in the worktree (it shows modified — the
  reorder only). It is not part of this change; discard or regenerate at merge.

## Plan 00252

- Phase 1 (1.1, 1.2) and Phase 2 (2.1, 2.2) ticked with `772ef675`; first
  success criterion ticked; status moved to In Progress. Task 2.3 (`_git_init`
  consolidation) left unticked: it is a complementary narrowing whose helper
  needs arbitrary nested paths that `tmp_git_repo` does not offer, and the
  guard already makes the helper's `_give_identity` redundant.
- Decision 1 ("never give CI a git identity") is honoured: the workflow is
  untouched. The identity is pinned INSIDE the suite for every runner alike,
  so a fresh runner and a local run can no longer disagree, which was the
  defect.

## QA

- `ruff check` / `ruff format` clean on both files.
- `mypy --strict`: the new code is clean; `tests/conftest.py` carries two
  PRE-EXISTING errors at lines 162/164 (`HookResultValidator`, untouched) and
  `tests/` is outside `qa_type_paths`, so the QA gate is unaffected.
- Daemon not restarted (per instructions); no `sed`, no stash.

## Environment note

`./scripts/setup_worktree.sh` only CREATES a new worktree (it refuses an
existing directory), so the venv for this pre-existing worktree was built by
sourcing `scripts/install/{python_fingerprint,venv,venv_resolver}.sh` and
calling `ensure_venv`, then `uv sync --extra dev` (the helper installs no dev
extras, so `pytest` was missing). `.venv` is a symlink to the fingerprint-keyed
`untracked/venv-*` dir; editable install verified to import from this worktree.
