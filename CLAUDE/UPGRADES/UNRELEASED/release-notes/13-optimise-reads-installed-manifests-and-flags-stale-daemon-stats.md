# Callout: the optimise step finds the manifests on a client install, and the upgrader flags a stale `daemon_stats` override

**Plan**: 00362
**Audience**: client projects

`/hooks-daemon optimise` now resolves the config-changes manifests inside
the installed daemon checkout (`.claude/hooks-daemon/CLAUDE/UPGRADES/config-changes/`)
and hands the range comparison to `check-config-migrations`, so the "new
since vX" recommendations that Step 0 used to skip silently on every client
install now surface. The upgrade summary's config-options section also
targets `handlers.status_line.daemon_stats.enabled` precisely: a config from
before v3.40 that still holds `enabled: true` is told the upgrade arrow now
lives in `upgrade_notifier` and the override can go, while a config that
never set the key or already holds `false` gets no nudge (manifests may
mark a `changed` entry `only_if_set: true` for this shape).
