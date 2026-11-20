# Callout: a stack of dependent branches counts once against the open-work cap

**Plan**: 00594
**Audience**: operators

A stack of dependent pull-request branches (each branch's tip a strict ancestor of the next one's) now counts once against `branches.wip.cap`, up to `branches.wip.stack_max_depth` links (default 5); each link past that counts one more, so a five-deep stack no longer uses half of a cap of 10 and a too-deep stack is still pressed. Grouping reads branch tips only, local or remote-tracking, so stacks pushed as separate pull requests are recognised with no forge call; a fork ends the chain, and parked, merged, park-carried and foreign branches never join a stack. The sweep, the preflight, the creation guard, the stop guard and the warning ladder all read the one count, and the sweep and the preflight print each stack as one line naming its depth and its bottom branch, with "land the bottom first".
