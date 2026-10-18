# Callout: the status line no longer goes blank while the daemon is down, and names the outage

**Plan**: 00488
**Audience**: operators

Claude Code renders nothing for a status line command that exits non-zero. The status-line forwarder printed its daemon-down marker and then exited 1, so the bar was blank for the whole outage, including the first minutes of a fresh checkout whose venv is building. The forwarder now exits 0 on that path (a per-event `daemon_down_exit_code` in the event catalogue); the `WorktreeCreate` forwarder keeps exit 1 because its stdout is a value and non-zero there means "not handled". Regenerate the forwarders on upgrade (the upgrade does this) to pick it up.

`init.sh` also names each daemon-down state it can tell apart, instead of the generic `DAEMON FAILED`: `VENV BUILDING` while the self-heal build runs, `VENV MISSING` when a clone or leftover venv exists but nothing builds, `VERSION MISMATCH` for a stale clone, and the existing `NOT PROVISIONED`. The list is in `CLAUDE/Architecture/StatusLine.md`.

`mkplan.bash` already advances a lagging plan counter to the highest plan on disk instead of refusing; a regression test now pins that for a fresh clone far behind the disk. No configuration change is needed.
