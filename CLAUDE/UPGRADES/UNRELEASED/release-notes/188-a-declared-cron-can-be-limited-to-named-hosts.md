# Callout: a declared cron can be limited to named hosts

**Plan**: 00470
**Audience**: operators

A `persistent_crons` job can now carry `hosts:`, a list of exact hostnames or
globs (`*`, `?`, `[...]`). A job with `hosts:` is declared only where the
session's hostname matches one entry, so a session elsewhere is neither told to
create it at start nor stopped for lacking it. The hostname is the first
non-empty of `HOOKS_DAEMON_HOSTNAME`, `CCY_HOST_HOSTNAME` (which ccy sets to the
host machine's name) and the system hostname. Exporting `HOOKS_DAEMON_HOSTNAME`
before launching a session therefore gives it a role, such as `cchd-sdlc-runner`,
without a real hostname entering the tracked config. The session's value reaches
the daemon even over the relay, which never rewrites the payload: the daemon
reads it from the hook process. An empty `hosts:` list is a config error. A job
with no `hosts:` stays global, so a project that adds nothing sees no change.
This repository now limits `issue-sdlc` to `cchd-sdlc-runner` and leaves
`failsafe-recovery` global.
