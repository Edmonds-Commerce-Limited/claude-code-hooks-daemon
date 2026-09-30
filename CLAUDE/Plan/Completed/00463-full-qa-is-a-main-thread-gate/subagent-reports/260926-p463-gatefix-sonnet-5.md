# Plan 00463 gate fix — subagent report

**Agent**: p463-gatefix (Sonnet 5)
**Worktree**: `worktree-plan-463-full-qa-gate`
**HEAD**: `e5ec261367774ba5521a6716a9c320cf552a37e6`

## Task

Merge `main` into the worktree and fix the full-QA gate's 6/39 failing
checks (magic_values, tests x11, security x3, generated_doc_drift,
project_handlers 0-collected), in the product, without weakening any test
or adding an exclusion.

## Merge

`main` (11 commits ahead) merged cleanly except one conflict in
`CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`'s niggles table. Resolved
by keeping every row from both sides, with N2's more-advanced status
(`✅ Remedied by Plan 00463`, from this branch) kept over main's
(`🔄 Graduated to 00463`), and main's N84–N94 rows inserted in main's
position. Committed separately from the fix commit.

## Fixes (all in one commit, `e5ec261`)

- **magic_values (3)**: `tests/unit/qa/test_full_qa_gate.py` had three
  `timeout=60` literals; replaced with `Timeout.REQUEST_LONG`.
- **security / bandit (3)**: `full_qa_lock.py` spawned git directly via
  `subprocess.run(["git", ...])` (the two B603/B607 findings) and imported
  `subprocess` at module scope (B404). Rewrote `git_common_dir()` to call
  the project's bounded `run_git()` runner (`utils/git_repo.py`) and to
  raise a plain `OSError` on failure instead of
  `subprocess.CalledProcessError`, which let the `subprocess` import be
  removed entirely (no `# nosec`, no suppression).
- **test_git_spawns_are_bounded / test_subprocess_spawns_are_bounded**:
  same fix — `full_qa_lock.py`'s raw git spawn was the one direct,
  untimed spawn both tests were catching.
- **test_handler_options_accessor**: `daemon/cli.py`'s `check` command
  built `SubagentFullQaBlockerHandler`'s options with
  `full_qa_settings.get(ConfigKey.OPTIONS) or {}` instead of
  `config.models.handler_options(full_qa_settings)`. Fixed to use the
  accessor.
- **test_hook_input_field_single_source**: `subagent_full_qa_blocker.py`
  declared its own `_CWD_FIELD: Final[str] = "cwd"` instead of importing
  `HookInputField.CWD` from `constants`. Fixed and the private constant
  deleted.
- **generated_doc_drift / test_claude_md_guidance_coverage**: `.claude/ HOOKS-DAEMON.md` was stale by one handler count (66 vs the live 67) and
  missing `subagent_full_qa_blocker`'s table row. Regenerated with
  `bin/hooks-daemon generate-docs`; `CLAUDE.md`'s `<hooksdaemon>` block was
  already current (regenerating it produced no diff).
- **test_glob_readers_are_declared (2)**: the branch's own new
  `tests/integration/test_documented_hook_probes_are_marked.py` reads
  several markdown trees by glob (`.claude/agents/*.md`, `CLAUDE/**/*.md`,
  plus four already-declared patterns) with no `path_glob` rule naming it.
  Added two new rules and extended four existing rules' `tests:` lists in
  `scripts/qa/changed_tests_map.yaml`.
- **test_run_dependency_check (3)**: the gate's own fail-closed logic
  (CLI-error handling, missing-JSON handling, `uv lock --check`) was
  already correct post-merge — main's Ledger 00466 N21 fix. The failure
  was environmental: the worktree's venv had drifted from `uv.lock` after
  this branch's own package-version bump. `uv sync --frozen --all-extras`
  fixed it; no code change needed.
- **project_handlers (0 tests collected)** — the interesting one. Root
  cause: this branch's round 10 M1 added `-p claude_code_hooks_daemon.qa.full_qa_gate` to `pyproject.toml`'s
  `addopts`, force-loading the whole-suite-refusal plugin into *every*
  pytest invocation that reads that config — including
  `test-project-handlers`'s `pytest .claude/project-handlers/ --import-mode=importlib`. `.claude/project-handlers/` has a
  `conftest.py`, but it does not import
  `full_qa_gate.pytest_collection_modifyitems`, so `_gate_anchor()` found
  no conftest-registered candidate and fell back to the plugin's *own*
  directory (`src/claude_code_hooks_daemon/qa/`), which holds zero
  `test_*.py` files. `_total_test_file_count` returned 0, and the plugin
  refused the run outright with "REFUSED: ... could not establish how many
  test files the real suite holds" — collected 202 items, ran 0, exit 1.
  **This gate was already failing loudly, not silently**:
  `check_project_handler_tests.py`'s `build_report()` already conjoins the
  verdict with a positive test count (`passed = exit_code == 0 and parsed["failed"] == 0 and total > 0`), so 0-collected was already read
  as a gate FAILURE, matching the brief's "make a check that collects 0
  tests FAIL loudly" requirement without any change needed there.
  **Fix**: `cmd_test_project_handlers` (`daemon/cli.py`) now passes `-p no:claude_code_hooks_daemon.qa.full_qa_gate` to explicitly unload the
  plugin for this one invocation — project handlers are a small,
  self-contained tree the whole-suite-lock rule was never meant to cover.
  Added `_FULL_QA_GATE_PLUGIN` as a named constant next to `_PYTEST_MODULE`.
  Verified `bin/hooks-daemon test-project-handlers` now runs and passes
  202 tests, and `check_project_handler_tests.py --json` reports
  `passed_all: true, total: 202`.
- **Does main have the same hole?** No. `main`'s `pyproject.toml` has no
  `-p` entry in `addopts` at all (`full_qa_gate.py` does not exist on
  main) — this hole was introduced entirely by this branch's round 10 M1
  change, so there is nothing to fix on main.

## TDD

Added `test_unloads_the_full_qa_gate_plugin` to
`tests/unit/daemon/test_cli_test_project_handlers.py`. Proven RED by
copying it into a `git archive HEAD` scratch extraction of the pre-fix
commit (`untracked/scratch/`, deleted after use, never `git stash`) —
failed with `ImportError: cannot import name '_FULL_QA_GATE_PLUGIN'`.
Confirmed GREEN against the real fix (11 tests passed in the real file).

## Verification

- Every originally-failing test file, plus the new/touched ones, run
  together: 462 passed (`tests/integration/test_claude_md_guidance_coverage.py`,
  `test_git_spawns_are_bounded.py`, `test_subprocess_spawns_are_bounded.py`,
  `test_handler_options_accessor.py`, `test_hook_input_field_single_source.py`,
  `test_check_generated_doc_drift.py`, `test_glob_readers_are_declared.py`,
  `test_run_dependency_check.py`, `test_full_qa_gate.py`, `test_full_qa_lock.py`,
  `test_cli_test_project_handlers.py`, `test_project_handler_test_gate.py`).
- `bin/hooks-daemon test-project-handlers`: 202 passed.
- `scripts/qa/check_magic_values.py`: 0 violations (1849 files).
- `scripts/qa/run_security_check.sh` (the real gate invocation, `bandit -r src/ -s B101`): 0 issues (1366 files).
- `mypy`, `ruff check`, `black --check`, `pyright`: clean on every touched
  file.
- Daemon restarted from inside the worktree; `bin/hooks-daemon status`
  reports `RUNNING`.
- Full gate queued in the background:
  `bash /workspace/untracked/scratch/gate.sh worktree-plan-463-full-qa-gate`
  (not waited on — result lands in
  `/workspace/untracked/scratch/gate-worktree-plan-463-full-qa-gate.out`).

## Files changed (fix commit `e5ec261`)

- `.claude/HOOKS-DAEMON.md` (regenerated)
- `scripts/qa/changed_tests_map.yaml`
- `src/claude_code_hooks_daemon/daemon/cli.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py`
- `src/claude_code_hooks_daemon/qa/full_qa_lock.py`
- `tests/unit/daemon/test_cli_test_project_handlers.py`
- `tests/unit/qa/test_full_qa_gate.py`

Merge commit: (previous commit) resolves
`CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`.
