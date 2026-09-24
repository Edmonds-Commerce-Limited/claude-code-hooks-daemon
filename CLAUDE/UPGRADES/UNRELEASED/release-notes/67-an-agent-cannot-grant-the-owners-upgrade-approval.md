# Callout: an agent cannot grant the owner's upgrade approval

**Plan**: 00376
**Audience**: operators

The new `upgrade_approval_guard` handler closes the routes an agent could use to grant its own breaking-upgrade approval instead of waiting for the owner: running `approve-upgrade` itself, forging the `upgrade-approvals/` marker or a venv's `.daemon-version` stamp, or setting `HOOKS_DAEMON_UPGRADE_HANDOFF` to impersonate the upgrade's Layer 1. The approval itself now needs a terminal and a typed phrase naming both versions, and its marker is bound to that upgrade, so the guard is a second line: an agent's shell has no terminal to answer with. The owner's route is `hooks-daemon approve-upgrade <version> --from <installed>`, or the command the gate's stop prints to run the approval from the new release's own code.
