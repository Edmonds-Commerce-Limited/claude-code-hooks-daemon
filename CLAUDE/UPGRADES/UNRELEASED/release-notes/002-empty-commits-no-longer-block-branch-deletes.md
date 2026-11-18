# Callout: empty commits on a merged branch no longer block its delete

**Plan**: 00622
**Audience**: operators

A branch whose work is already in the default branch, with one or more empty commits on top (a hand-written `Unpark branch`, a note, any commit that changes no file), was refused by `R-GIT-PUSH-DELETE-REMOTE`, `branch-sweep --clean --remote` and `delete-branch` as "not merged". It is now proven with the new evidence tier `empty-commits-only`: every commit the default lacks has exactly one parent and that parent's tree. The commit message plays no part. A commit that changes any file, a merge commit (even one with its first parent's tree), and a root commit still count as content, so no branch carrying content the default lacks gains a pass. What a delete of such a branch loses is the empty commits themselves and their messages; `delete-branch` still prints a `git branch <name> <sha>` restore line. A branch made only of empty commits off the default is deletable on the same rule. The cached remote-delete proofs are recomputed once after the upgrade (the cache key version moved), so a branch refused before the upgrade is judged afresh.
