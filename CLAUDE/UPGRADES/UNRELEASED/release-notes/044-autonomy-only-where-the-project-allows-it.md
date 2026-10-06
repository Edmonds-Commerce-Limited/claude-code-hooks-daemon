# Callout: a project can turn off everything that drives a session onto work nobody asked for, per environment

**Plan**: 00498
**Audience**: client projects

A new top-level `autonomy:` config block lists the environments where the daemon's work-driving machinery may run: `environments` takes any of `host` (a desktop session, where no container is detected), `docker`, `podman`, `lxc` and `generic`, and `hosts` takes role aliases or globs (`HOOKS_DAEMON_HOSTNAME`) that may run it anywhere. Where autonomy is off, nothing is scheduled and nothing pushes the session onto other work: declared `persistent_crons` and their Stop and SubagentStop enforcers, the failsafe-recovery cron advice at session start and on plan edits, goal injection, the goal-ledger challenge on a stop, the stand-in cron an `[awaiting-human]` stop must schedule, the idle-housekeeping advisory, the routine sweep and the session-actions directive are all silent. Guards are never gated, and the plain `STOPPING BECAUSE:` explanation still applies.

The default is every environment, so a project without the block behaves exactly as before. Where autonomy is off, a new `autonomy_notice` SessionStart advisory says so once, naming the environment and the config to change, and the status line's environment segment carries a `no autonomy` marker.

A config that cannot be loaded keeps the default (autonomy on), so a broken config never silently turns the machinery off.
