# Callout: branch pools now warn well before they refuse a new branch

**Plan**: 00619
**Audience**: operators

Each branch pool (open work, parked, merged) now warns as it fills: at 60 percent of the point where creating a branch is refused, more firmly at 80 percent, and at 90 percent on every tool call and every prompt until the pool drops below it. Session start and the main thread's stop report the same ladder. The warning names the pool, its count, the first branch to finish or remove and its command; the percentages are `branches.wip.ladder`, `branches.parked.ladder` and `branches.merged.ladder`. The block at the limit is unchanged and has no exemption, and no guard denies or allows anything it did not before.
