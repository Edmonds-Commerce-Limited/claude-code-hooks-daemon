# Issue 130 Phase 1 report (Sonnet)

Tasks 1.1 and 1.2 done and ticked in PLAN.md.

## Red first

New tests in `tests/integration/test_upgrade_eager_cleanup.py`, class `TestEagerCleanupInterpreterChoice`, run before the
fix: `5 failed, 16 passed`. Representative red output (case B and the 3.9 cases):

```
assert 'WARNING' in 'Kept venv-* entries: list-stale-venvs failed\nTypeError: unsupported operand type(s) for |\n'
```

That is the bug itself: the fake 3.9 `python3` crashed, and the output was the routine "Kept venv-\* entries" line.

Cases: (A1) fake failing `python3` first on PATH, venv `bin/python` works, stale entry removed, `python3` marker never
touched; (A2) same with the venv python non-executable and `HOOKS_DAEMON_PYTHON` set; (B1) no usable interpreter, WARNING
naming `HOOKS_DAEMON_PYTHON`; (B2) `HOOKS_DAEMON_PYTHON` names a missing file, WARNING names the path; (B3) the interpreter
exits non-zero, WARNING plus its own stderr shown.

## Fix (`scripts/install/venv.sh`, `eager_cleanup_stale_venvs`)

Interpreter order: `$2/bin/python` if executable (the function's second argument, the current venv), else
`HOOKS_DAEMON_PYTHON` if executable, else a stderr `WARNING: stale venv-* cleanup SKIPPED` block naming both. A failing
`list-stale-venvs` gives the same loud warning (the interpreter's own error is already on stderr). Bare `python3` is gone.
The missing-`paths.py` line is kept as a routine line, since that is not an interpreter problem.

## Decision: warn, do not fail the upgrade

Cleanup runs after the new daemon is verified RUNNING (rollback-safety ordering). Failing the upgrade there would report
a failed upgrade for a healthy one and invite a rollback over housekeeping. The warning goes to stderr, is unmissable and
names the recovery command (`bin/hooks-daemon list-venvs`). It is never silent. Return stays 0, documented in the header.

## Test-harness changes worth knowing

- `_seed_venv_dir` stub `bin/python` now `exec`s `sys.executable`; the old `echo fake` stub would now be run.
- A venv with no runnable python makes the resolver treat a sibling stale venv as live (paths.py `live` set), so the
  `HOOKS_DAEMON_PYTHON` test makes both venv pythons non-executable. This is a test artefact only.

## Verification

- `bash -n scripts/install/venv.sh` clean. shellcheck: 5 lines of findings, identical on main (pre-existing).
- `tests/integration/test_upgrade_eager_cleanup.py`: 21 passed.
- A broader run of `-k "eager or upgrade_sh or venv"` over tests/integration: 509 passed, 1 failed; the one failure was
  the HOOKS_DAEMON_PYTHON test before the resolver-artefact fix above, passing since.
- Targeted QA `changed --allow-unmapped`: first run 37/40, one `format` failure (Black wanted three small rewrites of the
  new test file), fixed in commit 62b5b4a9b. Re-run: QA 40/40 PASSED (untracked/scratch/qa-130b.txt).

## Release note

`CLAUDE/UPGRADES/UNRELEASED/release-notes/014-upgrade-stale-venv-cleanup-uses-the-resolved-interpreter.md` (013 was the
highest on main).

## Disagreement / notes

None with the brief. `upgrade_version.sh` exports `HOOKS_DAEMON_PYTHON` already, so the fallback is reachable in a real
upgrade; the venv's own python normally wins.
