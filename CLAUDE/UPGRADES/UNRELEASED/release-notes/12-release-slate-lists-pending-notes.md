# Callout: the release slate check lists what the release will say

**Plan**: 00360
**Audience**: operators

A plan that changes something a release should announce now leaves a short
callout in the pending-release holding area
(`CLAUDE/UPGRADES/UNRELEASED/release-notes/`) as part of closing, instead of
relying on the release session to rediscover it from commit history.
`hooks-daemon release-slate-check` lists those callout titles under
"This release will say" (JSON key `pending_release_notes`) without changing
its verdict, and the release pipeline folds them into the release notes and
moves them into the version's upgrade folder, aborting if any are left
behind.
