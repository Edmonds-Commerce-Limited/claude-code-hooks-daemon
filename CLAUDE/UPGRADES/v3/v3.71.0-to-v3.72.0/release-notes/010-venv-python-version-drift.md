# Callout: a venv whose Python changed underneath it is now rebuilt instead of trusted

**Plan**: 00555
**Audience**: operators

A host or image update can change the system Python, for example from 3.11 to 3.13. The daemon venv's `bin/python` then runs the new version and can no longer see its own installed packages. Earlier versions still judged that venv usable because its interpreter ran, so every daemon start failed with `ModuleNotFoundError` and the automatic rebuild never fired.

Every venv check, Python and shell alike, now compares the `major.minor` recorded in the venv's `pyvenv.cfg` with the interpreter that will actually run. A venv that differs is treated as stale, so the normal hook bootstrap builds a fresh one for the current Python with no command needed. A new QA check, `venv_interpreter_trust`, blocks any code that trusts a venv interpreter without that comparison.

A daemon that cannot start no longer locks the session out.

- `hooks-daemon diagnose` runs with no venv and no daemon. It names any interpreter drift, the last build result and the fix, and prints the last 20 lines of that build's log.
- `hooks-daemon status` reports any stop that was let through while the daemon was down, giving the count, the most recent entry and the path of `untracked/.daemon-down-stops.log`.
- While the daemon cannot be reached, the fail-closed guard now allows a small read-only set:
  - Read of a project file;
  - plain `ls`, `cat`, `head -n`, `tail -n`, and `git log` (`git status` is excluded: it can rewrite the index and run a configured fsmonitor program);
  - `hooks-daemon diagnose`.
- Protected and quarantined files stay refused. So do the daemon's runtime outputs: payload captures, the verdict and stop-event logs, and `untracked/hook-errors.log`.
- A Stop blocked because the daemon is down is allowed on the third consecutive block, or at once when the stop declares `[awaiting-human]`. The same applies to a daemon that accepts the connection but then fails, and each sub-agent keeps its own count.

Nothing to do on upgrade. If a drifted venv from an earlier version is still in place, the first hook after upgrading replaces it. `bin/hooks-daemon repair` forces the rebuild if needed. The troubleshooting entry "Interpreter changed under the venv" in `CLAUDE/SELF_INSTALL.md` gives the manual diagnosis.
