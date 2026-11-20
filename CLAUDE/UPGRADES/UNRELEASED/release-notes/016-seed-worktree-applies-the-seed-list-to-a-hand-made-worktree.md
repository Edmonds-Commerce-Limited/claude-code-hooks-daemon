# Callout: new command `seed-worktree` applies the configured seed list to a worktree made by hand

**Plan**: 00613
**Audience**: client projects

New: `hooks-daemon seed-worktree <worktree>` places the `worktree_create` `seed` entries into a worktree that was made with a hand-run `git worktree add`, which never fires the creation hook and so is otherwise left without the project's git-ignored files. It takes exactly one argument, the worktree, and no options: what is placed, and in which mode, comes only from the project's config. The worktree must be a linked worktree git lists for its repository (not the main checkout, not a subdirectory, not prunable); the main checkout's config is read strictly, and an unreadable one refuses. The same checks as at creation apply: a protected file in `mode: copy` is refused, each protected link is logged to `worktree-seed-protected-links.jsonl` (verb `seed-worktree`), and an existing destination is never touched, so running it twice places nothing the second time. Exit 0 on success, 1 when refused.

A file the `secret_file_guard` protects, such as a vault password file, may be seeded in `mode: symlink`. The link makes no second copy, and the guard still denies an agent every read through it. No configuration changes are required.
