# N59 gate fix 4 (Sonnet 5)

Worktree: `worktree-n466-n59`. Brief: `/workspace/untracked/scratch/briefs/n59-gatefix-4.md`.

## Cause

The full gate failed with only the `tests` stage red, but zero failed and
zero errored tests: `29642 passed, 0 failed, 20 skipped | coverage: 95.0%`.

Reproducing `scripts/qa/run_tests.sh` on its own (the gate's tests-stage
command) showed the real cause buried in `untracked/qa/tests.json.raw`:
pytest-cov's own end-of-run line, `FAIL Required test coverage of 95.0% not reached. Total coverage: 94.99%`. `finalize_passed_all` correctly turned
`passed_all` False via the runner's own exit code, but nothing downstream
said WHY — and the gate's own coverage display rounds to one decimal place,
so 94.99% showed as "95.0%", which reads as passing. This is the gate-rule
defect the brief asked me to check for: the gate must always NAME why a
stage failed, and this one named nothing.

The actual 0.01-point coverage gap was `safe_signal.py` (Plan 00466 N59,
introduced on this ledger) at 90.68%: six real branches with no test
exercising them — `verified_daemon_process`'s `AccessDenied` branch reading
a process's command line, `signal_verified_daemon`'s `NoSuchProcess`/
`AccessDenied` branches around `send_signal`, `stop_verified_daemon`'s
SURVIVED-after-both-grace-waits-time-out path and its `NoSuchProcess` race
during `terminate`, and `signal_own_session_child`'s own-group re-check race.

## Fix

1. **N118 (gate-rule defect, logged and remedied)**: added
   `find_unnamed_failure_reason(content, failed=, errors=, total=, exit_code=)` to `src/claude_code_hooks_daemon/qa/pytest_text_report.py`.
   Returns `None` whenever the failed/errored counts already explain a red
   run (or the run is clean, or nothing was collected), and otherwise
   returns pytest-cov's own fail line when present, or a generic
   `"pytest exited {exit_code} but reported no failed or errored tests"`
   fallback. `scripts/qa/run_tests.sh`'s text-fallback branch (the path this
   project actually takes — `pytest-json-report` is not installed) now
   records this as `summary.unnamed_failure_reason`, and
   `scripts/qa/llm_qa.py`'s `_summarize_tests` appends it as a `cause:`
   line whenever present. RED confirmed: the function did not exist before
   this fix, and the coverage report showed the six `safe_signal.py`
   branches genuinely uncovered before the new tests were added (proven via
   `--cov-report=term-missing`), green after.

2. **Real coverage gap**: six new tests in `tests/unit/utils/test_safe_signal.py`
   (monkeypatching the specific psutil calls each branch guards, plus one
   exercising the `os.getpgid` own-group race via a faked call-count return
   sequence) bring `safe_signal.py` to 100% coverage.

3. Logged as **N118** (remedied) with a PLAN.md row and a NIGGLES.md write-up.

4. Merged `main` (`git merge --no-ff main`): reconciled the ledger table with
   `merge_ledger_table.py`, then the N1-row trivial Edit to re-trigger the
   markdown-table formatter over the script's raw write. Renumbered this
   branch's release note `80` → `100` (main already had `110` from N105;
   next free number from 100 up). Regenerated `.claude/HOOKS-DAEMON.md` and
   `CLAUDE.md`'s `<hooksdaemon>` block.

   The merge's substantive conflict was `cmd_stop` in
   `src/claude_code_hooks_daemon/daemon/cli.py`: this branch's own
   `verified_daemon_process`-based implementation vs. main's independent
   pidfd-based one (closing a TOCTOU) with SIGKILL escalation after the
   SIGTERM grace (Plan 00466 N40 review 2 MA2). Resolved by keeping the
   `safe_signal.py`-based implementation — the canonical proof path this
   branch's own `check_signal_targets.py` QA gate enforces — and folding
   main's SIGKILL-escalation behaviour into it: `stop_verified_daemon`
   gained an optional `kill_grace_seconds` parameter (psutil's own
   start-time check on the verified handle already closes the same TOCTOU
   main's pidfd was for, so no separate pidfd was needed). Deleted the
   now-superseded pidfd helpers (`_open_pidfd`, `_signal_proven_pid`) and
   main's unused, unproven `kill_daemon_process` helper in
   `process_verification.py` (no callers, and a raw `psutil.Process(pid)`
   signal with no identity proof — exactly what `check_signal_targets.py`
   exists to deny). Rewrote `tests/unit/daemon/test_cli_commands.py`'s
   `TestCmdStop*` classes onto the merged implementation, replacing the
   stale "outlives the wait" expectation (written before SIGKILL escalation
   existed) with one proving the escalation actually reaps a
   SIGTERM-ignoring daemon.

5. Verified: `ruff`, `black`, `mypy`, `pyright` clean on every touched file;
   `bin/hooks-daemon restart` → RUNNING; the full tests-stage command run
   standalone after the merge: **30260 passed, 0 failed, 18 skipped,
   coverage 95.1%, Status: PASSED**.

## SHA

`083b8c3d352154ef088cbc7ae3be764a2bee51a8` (HEAD after the merge-fallout
fixup commit; merge commit `1998fee75`, original fix commit `3ff517a85`).

The full gate is queued in the background
(`bash /workspace/untracked/scratch/gate.sh worktree-n466-n59`); not waited
on here.
