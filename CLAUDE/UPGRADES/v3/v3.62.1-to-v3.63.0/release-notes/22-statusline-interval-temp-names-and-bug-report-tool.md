# Callout: the status-line suggestion recommends the shipped refresh interval; temp names are collision-proof; the bug-report tool reports cleanly

**Plan**: 00362
**Audience**: everyone

The session-start status-line suggestion and the installer's no-venv fallback
both now say `refreshInterval: 1`, the value the daemon's own settings have
shipped since Plan 00175 — a project that copied the old suggestion's `10`
can lower it and get a clock and thread indicator that stay live while the
session is idle. Every atomic writer of a status or signal file now builds its
temp filename from one helper that includes the thread and a random token, so
two writers in one process can no longer pick the same name. `scripts/debug_info.py`
no longer carries `[Errno 13] Permission denied: ''` in its "Daemon Status" and
"Installed Handlers" sections; a blank interpreter path is named as the problem
instead of being executed, and a resolvable one yields both sections in full.
