# Callout: branch pools count only this clone's branches; others are listed as Foreign

**Plan**: 00594
**Audience**: client projects

A client report showed the branch pools filling with branches that other people's clones, earlier containers or bots had pushed, so the creation guard and the stop guard pressed one clone to finish work it never started. Pools are now counted per owner.

A branch is **mine** when, in this order:

1. this clone holds a `hooksDaemonCreator` record for it (the daemon wrote it when the branch was created here);
2. otherwise it has a local ref, or its remote tip's author email equals `git config user.email` (compared without regard to case).

Anything else is **foreign**. A foreign branch:

- is listed in a new `Foreign` group of `branch-sweep` (and `group: "foreign"` in `--json`, with new `author` and `author_email` keys), with its age and author;
- is counted in no pool (open, parked, merged, dormant), so it never fills a cap, never blocks a creation, and is never judged at stop;
- is never cleaned automatically. `branch-sweep --clean --remote` still deletes a foreign branch whose merge is PROVEN, because proof matters more than ownership;
- is never offered as something to rename or delete by any deny or report.

The email check is weak evidence when several seats share one identity, so such seats see each other's pushed branches as mine. `branches.bot_owned` is unchanged; foreign is the general case of it. With no `user.email` set, a remote-only branch without a creator record is foreign.
