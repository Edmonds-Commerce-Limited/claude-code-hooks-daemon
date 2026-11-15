# Callout: an agent may delete an unmerged remote branch that holds nothing unique

**Plan**: 00594
**Audience**: operators

`git push --delete` of a remote branch used to be allowed for an agent only when the branch was merged into the default or an integration line. It is now also allowed when git proves the branch holds nothing unique: every file the branch adds or changes, against its merge base with the default, has the same mode and blob at the same path on the default's tip or on an integration line's remote tip. A file the branch deletes is not content, a branch that adds or changes no file proves nothing (a park branch stays human-only), and a branch deleted in the same command never counts as a surviving ref. The agent's own claim is never an input, the proof target stays the default or a declared integration line, and a branch holding even one file found nowhere else is refused with the files named. The tier is judged afresh on each call and is never cached. No configuration is needed.

`bin/hooks-daemon delete-branch --remote-only <name>...` is the leased route to the same proof: it deletes each remote branch the proof accepts under a lease on the proven tip (a commit pushed after the proof makes git refuse), prints `git push <remote> <sha>:refs/heads/<name>` to restore it, and refuses, naming the reason, every branch the proof does not accept. `--protected-ref` and `--dry-run` do not apply to it. The runnable remote-delete lines printed by `branch-sweep --clean` and the post-merge cleanup now name this command instead of a bare `git push --delete`.
