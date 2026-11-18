# Callout: branch-sweep prints a remote delete only when the guard would allow it

**Plan**: 00594
**Audience**: client projects

`hooks-daemon branch-sweep` and `branch-sweep --clean` used to print a `git push <remote> --delete <name>` line for any merged or patch-equivalent branch whose remote copy it saw, using its own inventory test, and the remote-delete guard (`R-GIT-PUSH-DELETE-REMOTE`) could then refuse that very command, for example when the remote branch had moved after your last fetch or the shared proof could not establish the merge. The sweep now asks the same proof the guard uses (`core/remote_branch_proof.py`) before it prints a delete: a branch the proof accepts gets the runnable line, and any other branch gets owner-only wording ("remote delete of <remote>/<name> is for the owner: <reason>") that is advice, not a command. Both the report's remote-only entries and the `--clean` follow-up commands (including `--dry-run`) follow this rule, and the `--json` `action` field carries the same text. The proof contacts the remote with one bounded `git ls-remote`, only when a branch with a remote copy is being judged. The `--clean --remote` deletion itself is unchanged.
