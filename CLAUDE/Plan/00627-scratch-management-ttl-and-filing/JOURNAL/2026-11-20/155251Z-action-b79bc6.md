## 15:52 · action · —

Tasks 2.1 and 2.2 built test-first in `core/scratch_repos.py` (66 tests in `tests/unit/core/test_scratch_repos.py`, over real repositories: a project pushed to a local bare `origin`).

- Each `.git` marker, and each bare repository (a directory holding `HEAD`, `objects/`, `refs/`), is REGISTERED_WORKTREE, OUTSIDE_POINTING (both PROTECTED), RELATED, STANDALONE or BROKEN (STUCK). Standalone needs every marker standalone; one other kind decides the entry. `Verdict.REPOSITORY` is gone; PROTECTED and P4 are live.
- Related: a remote, a `shallow` file, `objects/info/alternates`, or a root commit or ref tip the project's object database holds (`rev-list --no-walk --ignore-missing` in the project). R6: protected unless no staged change, every edited tracked file's blob is in the verified default tip's tree, no stash, and every ref tip and HEAD is contained by a remote-tracking ref whose sha the live `ls-remote` confirms. Then the git directory and the tracked files the walk saw are P4.
- Untrusted git: the nested config is read from the project with `git config --file ... --no-includes`, and any key outside an allowlist (filters, fsmonitor, includes, hooksPath, partial clone, worktree config...) makes the entry STUCK before git runs inside. Nested calls name `--git-dir`/`--work-tree` (no upward discovery onto the project), with no global/system config, no optional locks, `core.fsmonitor=false`, null hooksPath, `protocol.allow=never`. Sentinel tests: a planted fsmonitor and a clean filter never run; a stat-dirty tracked file leaves the nested index inode unchanged.
- In progress (`*.lock`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `BISECT_LOG`, `rebase-*`) is STUCK, read from the walk with no git.
- Wrong-verdict controls: failure and timeout injected into every git subcommand never yield standalone or P4; garbage output never yields P4.
- Root reach: `--root` outside this project's `untracked/` is refused, and so is any path through an `untracked/repos` or `untracked/scratch-archive` of any checkout. One `git ls-files` per sweep: an entry holding a tracked file is PROTECTED; a failed listing makes due entries STUCK.

Choice for the coordinator: a fake or broken `.git` (no `HEAD`) is now STUCK indefinitely, never ordinary content. Fail-closed, but such entries will never leave on their own.
