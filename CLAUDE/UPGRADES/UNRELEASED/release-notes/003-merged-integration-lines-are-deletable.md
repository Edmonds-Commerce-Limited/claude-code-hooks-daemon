# Callout: a merged release branch can now be deleted; release-branch workflows should declare it as an integration line

**Plan**: 00474
**Audience**: client projects

If you merge feature branches into a release branch (`release/*`), set `branches.integration_lines: ["release/*"]` in `.claude/hooks-daemon.yaml`. Feature branches merged into such a line are then treated as merged by the remote-delete guard (R-GIT-PUSH-DELETE-REMOTE), the WorktreeRemove cleanup and the post-merge cleanup, and the line itself is never counted toward the branch caps.

Previously an integration line was refused by name everywhere, so the release branch's own `git push origin --delete release/x` stayed denied even after it was merged. It is now judged by the same proof as any other branch, against the DEFAULT branch only: a line whose remote-tracking tip is an ancestor of the default branch (and whose live remote tip `git ls-remote` confirms) may be deleted by an agent, locally (`delete-branch`, the WorktreeRemove cleanup) and on the remote. A line that is not yet merged into the default branch is still refused, with a message saying so, and being merged only into another integration line does not count. The default branch, `branches.exempt`, `branches.protected_names` and tags are refused exactly as before, and `branch-sweep --clean` still never offers an integration line.
