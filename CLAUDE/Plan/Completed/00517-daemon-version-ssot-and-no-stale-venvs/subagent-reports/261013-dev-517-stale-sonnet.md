# Plan 00517 Phases 3-5 (staleness): sub-agent report

Branch `worktree-plan-517-staleness`. Tasks 3.1, 3.2, 3.3, 4.1, 4.2, 4.3 and 5.1 are done and ticked in PLAN.md. Task 5.2
(check this repository's own venvs with the new tool) was out of scope and is still open.

## Commits

- `adae5b3f3` Task 3.1: one rule, `paths.classify_venv`
- `0fcdfc9c0` Tasks 3.2 and 3.3: UNPROVEN evidence, `prune-venvs --unproven`
- `6d5f4ba60` Task 4.1: start, restart and provision remove proven-stale venvs
- `afb74bb20` Tasks 4.2 and 4.3: `unproven_venv_advisor`, dead runtime-set sweep
- `3c2056db3` Task 5.1: release note 055, post-upgrade task 01, lint fixes
- `54e1830ee` QA fixes (magic timeouts, error-hiding shape, guidance verdict, index row)

## What was built

- **The rule** (`daemon/paths.py`, stdlib-only because `list-stale-venvs` runs under the host `python3`):
  `classify_venv(venv_dir, slug, lock_hash, live)` returns `stale`, `unproven` or `keep`. `stale` is the legacy bare
  `venv/`, or this view's slug (or none) with a readable `lock_hash` that differs. `unproven` is missing or unreadable
  metadata, or another view's slug. `keep` is live, the current fingerprint's venv, a matching hash, a symlink name, or an
  uncomputable current hash. `live_venv_realpaths` moved here from `cli.py`, keyed on the daemon dir (the old call passed
  `project_root`, which differs in a client install).
- **Callers**: `list-stale-venvs` (so the bash upgrade cleanup, which now logs `unproven` lines as kept with a pointer),
  `prune-venvs --stale` / `--legacy`, `disk-usage`, `_stale_venv_advisory`. `--all-except-current` is removed and prints a
  message. `_reclaimable_venv_entries` is gone (`_stale_venv_entries`, `_unproven_venv_entries`).
- **Evidence** (`processes_using_venvs`, `gather_venv_evidence`): read-only `/proc` scan of `exe`, `cwd` and `argv[0]`.
  `exe` alone misses a venv because `bin/python` is a symlink to the system interpreter. Later arguments are not read, or
  `prune-venvs --unproven <path>` would refuse itself. Unreadable processes are counted and disclosed in the output.
  `list-venvs` (table marker, section, `--json` `evidence` key) and `prune-venvs --dry-run` show it.
- **`prune-venvs --unproven <path> --force`**: only a venv `_enumerate_venvs` lists can be removed. Refuses a symlink,
  the current or live venv, a proven-stale venv (points at `--stale`), a venv a process uses, a path that is no venv here,
  and a combination with `--stale` / `--legacy`.
- **4.1**: restart, provision (`init.sh` start, `bin/hooks-daemon restart`) and plain start all reach `cmd_start`, so the
  cleanup is in `_reap_stale_runtime_files`. It holds the venv build lock (5 s wait), skips a stale venv a process still
  uses, never touches UNPROVEN, and is fail-open (OSError, ValueError, VenvLockTimeout and anything else are logged).
- **4.2**: the start advisory now reports what the cleanup could not remove. New handler `unproven_venv_advisor`
  (SessionStart, priority 72 shared with `routine_qa_sweep`, enabled by default, silent when none). Its text is
  `paths.unproven_report_lines`, shared with `list-venvs`. Registered in constants, init_config, `.claude/hooks-daemon.yaml`
  and `.example`, `HOOKS-DAEMON.md`, the UNRELEASED config-changes manifest, and the guidance-coverage test (exempt, T4).
- **4.3**: `sweep_dead_runtime_sets` in `paths.py`, called from the same start hook, fail-open. Real-socket tests.

## Judgement calls to review

1. **Pid check is `read_pid_file(verify_daemon=True)`**, "alive and a daemon server", not "alive". After a container
   restart old pids are reused by unrelated processes, so a bare liveness test would keep most dead sets for ever. A
   reused pid that runs a real daemon still keeps its set.
2. **60 second grace** on 4.3: a set with any member written in the last minute is left, because a peer's start writes its
   lock before its pid and sockets. Not in the brief.
3. **Discovery file**: the socket it names is probed too (a long project path puts the real socket elsewhere); an
   unreadable discovery file keeps the set.
4. **The resolver serves a metadata-less venv as a last resort**, so a lone UNPROVEN venv can be the live one and is then
   `keep`. Tests that need UNPROVEN patch the resolver to find none.
5. The current fingerprint's venv is `keep` in `classify_untracked_venvs`: its metadata is written after the sync, so a
   venv mid-build would otherwise read as UNPROVEN.
6. The integration test `test_upgrade_eager_cleanup` expectation changed in two places: a venv built for the current
   source is now reported `live` (the resolver serves it), and the uncomputable-hash case asserts "kept" not the reason text
   (the resolver can also hold that venv live). The unit tests keep both reasons.

## Not done / open

- Task 5.2 (run the tool over `/workspace/untracked` and every worktree). Nothing was deleted anywhere; no `--force`
  prune was run against a real directory.
- Pre-existing: the `housekeeping` held step `prune-venvs` runs the bare command, which has no selection flag and exits 1.
  Untouched.
- `datetime.UTC` (3.11) is used in `paths.py`, which is also run as a bare script; the project floor is 3.11 but a host
  `python3` older than that would fail `list-stale-venvs` on the evidence path only (not the verdict path).
- A venv directory with no `bin/python` is still skipped by `_enumerate_venvs` (pre-existing), so `list-venvs` does not
  show it, though `unproven_venv_advisor` and `list-stale-venvs` (which scan the directories) do.

## QA

`./scripts/qa/llm_qa.py changed --allow-unmapped` on the final commit: 39/40 passed. The single failure,
`tests/unit/test_doc_write_jail.py::TestSessionWiring::test_every_checkout_of_the_repository_is_protected`, passes when run
alone and depends on which sibling worktrees exist while the run is under way; it is not touched by this branch.
changed_tests: 5367 passed, 1 failed (that test), 5 skipped. Eight files are unmapped as too-broad (`cli.py`, `paths.py`,
`constants/handlers.py`, `constants/priority.py`, `init_config.py`, `session_start/__init__.py`, `.claude/hooks-daemon.yaml`,
`.claude/HOOKS-DAEMON.md`): the full gate must cover them. A first run without `--allow-unmapped` listed the same eight
and failed on them by rule. Before the last commit the same run found four magic timeouts, two error-hiding returns, one
repo-hygiene index row and one unclassified handler; all fixed. Also run clean on the touched files: black, ruff, mypy,
`tests/unit/daemon`, `tests/unit/handlers/session_start` (3689 passed).

## Review round 1 (see 261013-review-517-r1-sonnet.md)

Fixed: dead runtime sets are PROVEN dead only (in-tree sockets refused or absent, pid not a verified daemon; a socket
outside the untracked dir keeps the set); the automatic venv cleanup skips while a peer set is not proven dead or the /proc
scan has unreadable processes (decision journalled); `prune-venvs --stale` / `--legacy` skip venvs a process uses; the
housekeeping label, the v3.6 guide note, and one fail-open path around the cleanup and the advisory.

Accepted, not changed: the bare-python-from-an-activated-venv NIT and the advisor scan-cost NIT.
