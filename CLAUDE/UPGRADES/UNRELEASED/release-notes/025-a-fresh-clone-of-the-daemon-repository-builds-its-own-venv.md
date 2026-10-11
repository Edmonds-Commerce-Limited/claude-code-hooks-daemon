# Fix: a raw clone of the daemon's repository builds its venv with no manual step, and the build's first moments read as building

**Plan**: 00488
**Audience**: operators

Two gaps in the first-session venv build are closed. A fresh `git clone` of this repository has no `.claude/hooks-daemon.env` (it is gitignored), so `init.sh` looked for the daemon in `.claude/hooks-daemon/`, found nothing, and the status line read "DAEMON FAILED" while SessionStart advised installing, which is wrong for this repository. `init.sh` now recognises the daemon's own source tree and uses the project itself as the root, so the first hook starts the background venv build with no step from you. `scripts/bootstrap-self-install.sh` still works for a foreground build. A client project is never matched.

Separately, for the first sub-second to few seconds of a build, uv has made the interpreter but not yet installed the package. A hook arriving then used to read "DAEMON FAILED" and PreToolUse denied the call. A held venv build lock now marks the whole window as "venv building", and tool calls fail open with the announcement, as the rest of the window does. No configuration change is needed.
