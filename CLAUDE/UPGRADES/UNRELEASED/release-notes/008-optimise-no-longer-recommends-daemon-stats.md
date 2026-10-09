# Callout: `/hooks-daemon optimise` no longer recommends the `daemon_stats` status-line handler

**Plan**: 00474
**Audience**: operators

The config-optimisation review used to treat `handlers.status_line.daemon_stats` (the daemon health line: uptime, memory, log level, error count) as relevant to every project, so it recommended enabling it everywhere. That health line is a diagnostic for people developing the daemon itself. It now reports as "not applicable here" in every project except the daemon's own repository. If you enabled it because the review recommended it, you can set `handlers.status_line.daemon_stats.enabled: false` (or remove the entry, since it ships disabled) and restart the daemon. Nothing else changes, and the separate daemon-upgrade notifier (`version_check`) stays on by default.
