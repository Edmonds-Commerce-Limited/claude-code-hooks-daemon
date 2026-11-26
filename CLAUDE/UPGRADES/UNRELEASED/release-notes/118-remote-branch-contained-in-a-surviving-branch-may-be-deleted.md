# Callout: A remote branch held by another surviving branch may be deleted

**Plan**: 00474
**Audience**: everyone

The remote-delete guard, `delete-branch --remote-only` and `branch-sweep --clean --remote` now also accept a remote branch whose every commit is an ancestor of another remote branch that still exists, on the owner's ruling that such a branch loses nothing when it goes. The proof is the guard's own: the other branch is read from the remote-tracking refs, is never one the same command deletes, and its live tip is confirmed against the remote before anything is pushed, so a branch that is the only holder of its commits is still refused. Integration lines are judged as before, by the default branch only.
