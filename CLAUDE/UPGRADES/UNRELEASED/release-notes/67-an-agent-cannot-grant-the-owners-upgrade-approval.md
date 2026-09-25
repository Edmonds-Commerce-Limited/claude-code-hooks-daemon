# Callout: an agent cannot grant the owner's upgrade approval

**Plan**: 00376
**Audience**: operators

The breaking-upgrade approval needs your terminal and a typed phrase. The new `upgrade_approval_guard` denies an agent every other way to that result: running `approve-upgrade` itself, forging the approval marker or a venv's version stamp, moving `.claude/hooks-daemon` to another version by hand, or steering an upgrade with `PATH`, `HOOKS_DAEMON_PYTHON`, `GIT_*`, `LD_*` or the other variables `hooks-daemon explain-rule R-UPGRADE-APPROVAL-ENV-BYPASS` lists. The guard recognises the upgrade however its script is named, and the pre-deploy gate itself takes nothing from the caller's environment, so if an upgrade genuinely needs one of those variables the agent asks you to run it.
