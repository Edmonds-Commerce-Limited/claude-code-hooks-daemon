# N527: status-line loading tests error at teardown

Fix commit: 209283e73 (ledger rows follow in the report commit).

## Which process writes after teardown begins

Evidence from `untracked/scratch/n527_probe.py` (11 runs, 8 under 16 busy loops): once the status hook returns its
loading line, the only matching process is the orphaned launcher
(`python -m claude_code_hooks_daemon.daemon.cli --project-root P start`, ppid 1; sometimes still the `/bin/bash`
wrapper before its exec). The daemon does not exist until the launcher forks twice (`cli.py` lines 864-918). The
daemon writes its PID file, socket and start log into the sandbox base (`d.pid`, `d.sock`, `started`) after its
slowed init.

`stop_daemons_of` scanned once. A launcher stopped just after its first fork leaves a child that becomes the daemon;
the scan could not have listed it, so it outlives the teardown and writes under `shutil.rmtree`. This ordering is
inferred from the code and the CI error. The window is milliseconds and was not observed live: all 11 probe runs were
clean.

## Fix

`tests/daemon_teardown.py::stop_daemons_of` now re-scans after each round of stops until a scan finds nothing it has
not already stopped. It is bounded by `Timeout.PROCESS_DEATH_WAIT / 0.1` rounds and raises `RuntimeError` if daemons
keep appearing. No `ignore_errors`, no rmtree retry, no suppressions.

## TDD

Three new unit tests in `tests/unit/test_daemon_teardown.py` with scripted scans. RED before:
`assert [10] == [10, 11]`, same for the no-restop test, and `DID NOT RAISE`. GREEN after (13 passed together with the
integration file, 29 s). A 20-run loop was not done; the race is not reproducible live, so the deterministic unit
test is the evidence.
