# Callout: branch-preflight lists every blocker to creating a branch, and the creation deny prints the same report

**Plan**: 00594
**Audience**: client projects

`hooks-daemon branch-preflight [name]` is a new read-only command that answers "can I create a branch now?". It lists every pool that refuses a creation (the open-work cap, dormant branches at the block stage, the parked pool, the merged pool), not only the first rule that trips, and gives each one the exact command that clears it (`branch-park ... --reason`, `branch-park ... --clear`, `delete-branch`, `branch-sweep --clean`, `branch-keep`). It exits 0 when a branch may be created and 4 when one is refused (1 when the directory is not a git repository); `--json` prints `{may_create, blockers: [{rule_id, refuses, fixes, lines}], notices}`. A pool in `warn` mode is listed but does not refuse.

The creation deny (R-BRANCH-WIP-CAP, R-BRANCH-DORMANT, R-BRANCH-PARKED-POOL, R-BRANCH-MERGED-POOL) now renders the same report from the same function, so the two cannot disagree, and ends with a pointer to the command. No verdict changed: what is allowed and what is denied is exactly as before. Two listings gained fix commands they lacked: each open branch in the cap deny now names a command (the snapshot's suggested action, otherwise `branch-park <name> --reason ...`), and each dormant branch names its park and delete commands.
