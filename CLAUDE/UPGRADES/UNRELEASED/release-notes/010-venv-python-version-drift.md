# Callout: a venv whose Python changed underneath it is now rebuilt instead of trusted

**Plan**: 00555
**Audience**: operators

A host or image update can change the system Python, for example from 3.11 to 3.13. The daemon venv's `bin/python` then runs the new version and can no longer see its own installed packages. Earlier versions still judged that venv usable because its interpreter ran, so every daemon start failed with `ModuleNotFoundError` and the automatic rebuild never fired.

Every venv check, Python and shell alike, now compares the `major.minor` recorded in the venv's `pyvenv.cfg` with the interpreter that will actually run. A venv that differs is treated as stale, so the normal hook bootstrap builds a fresh one for the current Python with no command needed. A new QA check, `venv_interpreter_trust`, blocks any code that trusts a venv interpreter without that comparison.

Nothing to do on upgrade. If a drifted venv from an earlier version is still in place, the first hook after upgrading replaces it. `bin/hooks-daemon repair` forces the rebuild if needed. The troubleshooting entry "Interpreter changed under the venv" in `CLAUDE/SELF_INSTALL.md` gives the manual diagnosis.
