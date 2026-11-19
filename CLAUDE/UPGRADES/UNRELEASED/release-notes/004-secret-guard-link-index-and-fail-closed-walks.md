# Callout: computed `cd` moves in large projects are judged from a link index

**Plan**: 00623
**Audience**: client projects

Behaviour change (usability): release note 003 made a `cd` whose target bash computes (`cd "$D"`, `cd -`, a bare `cd`, `cd ~/x`, `cd "$TMPDIR"`) deny any later relative word once the project held more than 512 directories, because the per-call link scan could not finish. That was most real repositories. The daemon now keeps an in-memory index of the project's directories and links. It is built in the background when the daemon starts and checked against the filesystem before each use, so such commands are judged on what the project really holds: allowed when no link reaches a protected path, denied when one does. Until the index is built (the first seconds after a restart), the old bounded scan is used and may still deny.

The index is never written to disk, so no file in the project can forge it. It fails closed: a project past 200,000 directories, a check that has to re-list more than 4,096 changed directories or that runs past 2 seconds, a project root that cannot be stat-ed, a directory anywhere in the project that cannot be listed, or a link whose target cannot be told all deny the computed move followed by a reader, and a rebuild starts in the background. `.git` directories are indexed too. A project past 200,000 directories (for example a checkout that holds many other worktrees or large scratch trees) therefore denies every computed move followed by a reader.

When the index names more than 512 link-holding directories (a `node_modules/.bin` in every package), a word read after a computed move is judged by link name instead of from each directory: it denies when any leading part of it spells the end of a link path anywhere in the project (`cat .bin/tool`, `cat l*` when a link `late` exists), or when it holds `..`. Words that name no link (`cat README.md`, `ls -la`, `npm test`) are allowed. A relative or globbed `cd` after such a move, a relative glob, and a recursive search that could reach a protected file anywhere in the project still deny. The move still denies when the project holds more than 512 links to directories or more than 65,536 links in all.

Behaviour change: a move to `~`, `$HOME` or `$TMPDIR` (with an optional literal path after it) that lands outside the project is placed there, using the daemon's own value of the variable, instead of being judged as an unknown move. It is placed only when the command names the variable nowhere else. Placement does not excuse a link scan that stopped: until the index is built, or when it fails closed as above, such a move followed by a reader still denies. The same holds for `cd "$(git rev-parse --show-toplevel)"`.

Security fixes, each of which was allowed before:

- A relative word that fits PATH_MAX on its own but not once joined to the project directory (`cat plain/../plain/../…/link`) is now denied when it cannot be stat-ed.
- A path through the daemon's own process view (`/proc/self/…`, `/proc/thread-self/…`, `/dev/fd/…`) is now denied in Bash, Read and Grep, because the daemon would resolve it from its own working directory rather than the shell's. Behaviour change: ordinary reads such as `cat /proc/self/status` and `ls /dev/fd` are denied too.
- `cd "$(git rev-parse --show-toplevel)"` is no longer placed at an ancestor of the command's directory when git config in the repository, user or system config names a worktree or an include, or a `GIT_` relocating variable is set for the daemon.
- A recursive search or a directory change nested more than four `bash -c` levels deep is now denied when the nested body could read or move; a harmless nested body is still allowed.
- A globbed or relative `cd` taken from more than 17 directories, and a wildcard whose parent directory exists but cannot be listed, now deny instead of dropping the directories not looked at.
- The quarantine-artefact guard, the flaggable-content guard and payload capture now treat a command whose words cannot be placed as a finding (deny, or excluded from capture) instead of an unjudged allow.
