# Callout: a signal now goes only to a process proven to be its target

**Plan**: 00466
**Audience**: everyone

Before this fix, the installer's pre-install check sent SIGTERM and then SIGKILL
to whatever pid a `daemon*.pid` file held, and `upgrade.sh` sent SIGTERM the
same way. PID files survive a container restart, and a restarted container
reuses small pids, so a stale file could name any process, including Claude
Code itself. Both now signal a pid only when its command line shows the daemon
server for your project root. Any other pid is named in a warning and left
running. If a daemon for your project is still up when you install, stop it
yourself. Container single-daemon enforcement now re-checks each peer the same
way, and it signals nothing when it cannot tell which project a daemon serves.
`hooks-daemon stop` (and so `restart`) checks the project root too. Before,
its PID file only had to name some hooks daemon. If that daemon serves another
project, `stop` now refuses with an error and leaves it running.

The venv bootstrap watchdog, the venv lock heartbeat and the resolver's probe
watchdog now each confirm, before signalling, that the pid still names the
process they started. The dummy client teardown signals only the survivor's
own pid, not its whole process group, and re-reads its command line first. A
new QA check, `signal_targets`, fails on any nonzero signal to a pid that has
not been verified this way. It checks Python code and shell scripts. You
don't need to configure anything. The only visible changes are the new
warning and the new `stop` error.
