# Callout: branch-park says plainly when the push was refused, and a merge clears the park visibly

**Plan**: 00594
**Audience**: client projects

`hooks-daemon branch-park` writes the park first (the trailer commit, plus a local record in git config under `branch.<name>.hooksDaemonParked*` holding the commit, reason, time and owner), then pushes. A project pre-push gate may refuse that push, for example one that wants a fresh full-QA verdict. The park then stands locally and the command now prints `WARNING: parked locally, not pushed`, git's own reason, and the exact `git push <remote> <name>` to run later. It exits with status 3 instead of 0, so a script can tell a half-done park from a full one. A branch that only the remote holds still parks nothing on a refused push, because no local ref can carry the park.

A merge of a parked branch ends its park. `branch-park --clear`, the post-merge cleanup, `branch-sweep --clean` and the worktree-removal cleanup now remove the local record and print `Park cleared: <name> (<reason>)` (`Park record cleared: ...` for `--clear`), so a park never ends silently. Pool caps are unchanged.
