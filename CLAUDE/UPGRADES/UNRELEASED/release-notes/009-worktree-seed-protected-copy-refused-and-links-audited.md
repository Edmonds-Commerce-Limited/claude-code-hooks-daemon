# Callout: a worktree seed may no longer copy a protected file, and seeded links to one are logged

**Plan**: 00613
**Audience**: client projects

Behaviour change: a `worktree_create` `seed` entry in `mode: copy` whose source is, holds or links to a path the `secret_file_guard` protects now aborts worktree creation, before `git worktree add` runs; the refusal names the entry by its position (`seed entry #N`), never by its path. A copy put the protected content under a second path that a project-anchored glob may not cover and that `git add -A` could commit. If the guard config cannot be read, every `mode: copy` entry is refused. To fix a config that now refuses, remove the copy entry; `hooks-daemon check-worktree-seed` lists every such entry under REFUSED, judged against the guard options of the config file it reads. Entries in `mode: symlink` are not refused.

Each link that seeding creates to a protected source (or to a directory holding one) now appends one JSON line to `worktree-seed-protected-links.jsonl` in the main checkout's daemon `untracked/` directory: time, worktree, the repository-relative path, the protecting glob and the session id, never content, size or digest. A link that cannot be classified (unreadable guard config, a directory that cannot be walked in full) is logged as `linked-unclassified`. If the line cannot be written, that link is not created and creation fails.
