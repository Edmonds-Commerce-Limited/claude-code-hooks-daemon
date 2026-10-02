# Plan 00470 Task 4.2: stale worktrees and daemons in the idle housekeeping report

## What was built

- `src/claude_code_hooks_daemon/utils/stale_checkouts.py`: read-only detection.
  - `find_stale_worktrees(repo_root, base_branch, ...)` lists registered linked worktrees (`git worktree list --porcelain`, main checkout skipped) whose branch is fully merged into the base, whose directory is missing (prunable), or whose branch has no commit for N days.
  - `find_stale_daemons(checkout_roots, ...)` reports `daemon*.pid` files (in each registered checkout's untracked dir) that are corrupt or name a dead pid, and running daemon servers whose project root no longer exists.
  - `render_stale_report(...)` returns `None` when nothing is stale (quiet), otherwise a text block with each finding and the exact cleanup commands.
  - `collect_stale_report(...)` ties the three together for the handler.
- `idle_housekeeping_advisor.py`: `_build_guidance` appends the report to the guidance (also in `replace` mode). New options: `report_stale_checkouts` (default true), `base_branch` (default `main`), `stale_worktree_days` (default 7).
- `.claude/hooks-daemon.yaml.example`: the three options documented under the handler.
- PLAN.md Task 4.2 marked done.

## Safety rules carried over from `core/worktree_reaping.py`

- Unknown is not stale: unknown worktree age, unattributable daemon root, unreadable pid file are all left off.
- A just-created worktree is an ancestor of main, so "merged" needs worktree age >= `MINIMUM_AGE_SECONDS`; "idle" needs the worktree itself to be at least N days old (a branch cut today from an old commit has an old tip time); a live process with its cwd inside the worktree vetoes both.
- Locked worktrees (a deliberate hold) and detached worktrees are not reported on merge/idle grounds. A missing directory is reported regardless.
- `git branch -d` is only offered for a merged branch (git refuses otherwise anyway). Nothing is ever executed; the daemon hosting the advisory is excluded from the process scan by `find_all_daemon_processes`.

## How the daemon names its files (for the record)

- PID file: `<untracked>/daemon[-<host>].pid`, socket `daemon[-<host>].sock`; `<untracked>` is `<root>/untracked` in self-install mode and `<root>/.claude/hooks-daemon/untracked` otherwise. Over-long paths fall back to `$XDG_RUNTIME_DIR/hooks-daemon-<hash>.{pid,sock}`.
- Each worktree is its own project root, so a worktree runs its own daemon with its own pid file inside its own untracked dir.

## Gap, not done

- The `$XDG_RUNTIME_DIR/hooks-daemon-<hash>.*` fallback files are keyed by a hash of the project root and cannot be mapped back to a root, so a stale fallback pid file for a deleted worktree is not detected. A live daemon for a deleted root IS caught via the process table. Stated rather than guessed at.
- No separate `docs/` section exists for this handler's options, so none was added; the yaml example and the handler's `get_claude_md` carry them.

## Tests

- `tests/unit/utils/test_stale_checkouts.py`: 26 tests, real git over `tmp_path`, fake process tables and liveness probes.
- `tests/unit/handlers/user_prompt_submit/test_idle_housekeeping_advisor.py`: 6 new tests (report appended, quiet when none, options reach the detector, switch-off, replace mode, claude_md); an autouse fixture keeps the scan off the host.
- Run together with `test_claude_md_guidance_coverage.py`, `test_init_config.py`, `test_dogfooding_config.py`, `test_default_enabled_template_consistency.py`, `test_eviction_sites.py`: 462 passed.
- ruff, black `--check --target-version py311` and mypy clean on the changed files; `check_generated_doc_drift.py` reports no drift.
