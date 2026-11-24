# Callout: ci-state reading tells GitHub "queued" from stuck on a coordinator seat

**Plan**: 00636
**Audience**: operators

The new `ci_state_reading` PostToolUse handler reads the output of `gh run list`, `gh run view --json` and `gh pr checks` on a team coordinator seat and labels each run that has not started. A run queued for less than `options.stuck_after_minutes` (default 30) is QUEUED: normal waiting for a runner, not stuck. At or past it, it is STUCK, with the `gh run view` check to make before saying so. `gh pr checks` folds queued and running into `pending`, so those rows read PENDING and name the `gh run list --json` command that can tell. A status or creation time it cannot read is UNKNOWN, never either. The block also carries the rule never to tell the team what another seat's code does without asking that seat first.

It is advisory, never denies, and runs no command or network call of its own. A declared worker, a session with no team and a sub-agent are untouched. The upgrade adds the handler's config entry; nothing else needs changing.
