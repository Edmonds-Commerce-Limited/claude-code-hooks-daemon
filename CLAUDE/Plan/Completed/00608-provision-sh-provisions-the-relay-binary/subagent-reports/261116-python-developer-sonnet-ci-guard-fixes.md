# CI guard fixes on the relay-repair branch

Merged origin/agent-ae24600c2e68e3034-07dabf0e (tip 28a42139e), then fixed the two CI guard failures.

1. Signal target checker: `_end_group` in `install/relay_repair.py` now signals through
   `utils.safe_signal.signal_own_session_child(child, sig)`. It validates the Popen we hold
   (unreaped, plain pid, leads its own group, not ours) before `killpg`. No suppression or
   allowlist entry. The test cleanup that used a bare `os.killpg(pid, 9)` now records the Popen
   that `spawn_detached` creates and signals it through the same helper (a `psutil.Process(pid).kill()`
   was also flagged as an unproven handle).
2. Wall-clock guard: `time.monotonic() - started < 5` in `test_relay_repair_owned.py` is now
   `< scaled_seconds(5.0)`.

Behaviour unchanged: SIGTERM to the group, SIGKILL after the grace, reaped before stop returns.

Verified: both guard tests, the 11 owned-repair tests and the symlinked-project stop integration
test pass (42 passed); ruff, black (py311), mypy clean. Pyright reports only the environment's
unresolved pytest import.
