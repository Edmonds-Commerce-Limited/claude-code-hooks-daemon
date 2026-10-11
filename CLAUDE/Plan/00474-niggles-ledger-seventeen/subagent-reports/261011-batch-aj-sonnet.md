# Batch AJ: N53 (WorktreeCreate exit 127), Sonnet

## Finding

Status 127 in the WorktreeCreate failure has two origins that the old message could not tell apart:

1. `run_git` (`utils/git_repo.py:229`) turns any `OSError`/`SubprocessError` at spawn into a synthetic
   `CompletedProcess` with returncode 127 and `str(exc)` as stderr (git not on PATH, for example).
2. Git itself exits 127 when a hook it runs cannot find a command.

## What I tried (scratch repo, `untracked/scratch/n53/repro.sh`)

| Probe                                          | Result                                                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `post-checkout` hook running a missing command | `git worktree add` exits 127, prints `nonexistent-cmd-xyz: not found`; the worktree and branch ARE created |
| hook with `#!/nonexistent/interp`              | exit 1, `fatal: cannot run ...post-checkout`                                                               |
| `env -i /usr/bin/git worktree add`             | exit 0                                                                                                     |
| `core.hooksPath` naming a missing directory    | exit 0                                                                                                     |
| `PATH=/nonexistent git ...`                    | shell reports 127 (`git: command not found`); the handler's equivalent is origin 1                         |

`/workspace/.git/hooks` holds no hooks, no `core.hooksPath` is set, and no `.githooks` exists, matching the original
report ("the repo has no post-checkout hook"). So origin 1 (daemon cannot spawn git) is the likelier live cause, but it
is NOT confirmed; I could not reproduce the daemon's own environment without touching the live daemon.

## Change

- `handlers/worktree_create/worktree_create_handler.py`: `_WorktreeAddError.__str__` appends, for status 127, a hint
  naming both origins and the PATH the daemon searched.
- `tests/unit/handlers/worktree_create/test_worktree_create_handler.py`: three tests (hint names both origins and the
  PATH; other statuses carry no hint; a real repo with a failing `post-checkout` reproduces 127 through the handler
  with the hook's stderr quoted). 34 tests pass; ruff, black, mypy, pyright clean.

## What the next occurrence shows

Stderr plus the hint. `[Errno 2] No such file or directory: 'git'` means origin 1 and the PATH quoted is the daemon's.
Hook text such as `<cmd>: not found` means origin 2; the worktree exists and a retry reuses it.

## Not done

No handler behaviour change (for example, tolerating a failed hook when the worktree registered): that would hide a
hook failure, and the live cause is unconfirmed.

## Docs updated

N53 row and counts in `00474/STATUS-INDEX.md` and `00474/PLAN.md` (open 1 to 0; 🟡 2 to 3); the 00466 `STATUS-INDEX.md`,
`PLAN.md` and `STATUS-2026-10.md`.
