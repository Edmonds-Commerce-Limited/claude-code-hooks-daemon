## 16:57 · decision · —

**Owner ruling: unblocked.** A worktree whose only leftover is a seeded copy is fine to remove. A seeded copy cannot be lost, because its source is in the main checkout. The guard confirms the copy has not diverged from that source: a diverged copy might hold work that would be lost, so it still blocks the removal and is named in the deny.

Planned (Plan 00579): the worktree-removal check reads the `worktree_create` seed list directly, so no path is listed twice, and treats a copy-mode seed as not losable only while it is byte-identical to its source. A missing source counts as diverged. Symlink seeds, `regenerable` globs and every other ignored entry behave as before. #173 stays a separate issue.
