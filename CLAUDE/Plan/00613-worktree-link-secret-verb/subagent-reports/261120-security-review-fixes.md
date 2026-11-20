# Plan 00613: fixes for the two security reviews, handoff

Branch `agent-a4419afc45dbc6663-82565567`. Not merged. Follows
[261120-read-gap-closed.md](261120-read-gap-closed.md).

Reviews:

- F-BYPS: `/workspace/untracked/agent-reports/00613-F-BYPS-seeded-link-review.md` (F1 to F6; probes in `/workspace/untracked/scratch/fbyps-probe/`)
- D-PATH: `/workspace/untracked/agent-reports/auto/261120-161320-security-reviewer-a384830a047e5508c.md` (2 findings)

## Commits

- `10ac27973`: merge of origin/main (release note 015's Plan line)
- `4f360c8f7`: release note renumbered 018 -> 019 (018 is taken on `fix/branch-guard-worktree-proof`; 019 is free on every ref)
- `cb84a5916`: D-PATH 1, D-PATH 2, F6

## Closed

- **D-PATH 1.** `seed_existing_worktree(worktree, *, project_root)` refuses a worktree whose main checkout is not the main checkout of the daemon's project root (`_refuse_another_project`, via `GitRepo.resolve_for(project_root).main_worktree_root()`). A worktree-root daemon still matches. The CLI passes `get_project_path()`.
- **D-PATH 2.** `seed_worktree` wraps each placement: an `OSError`, or an audit-write failure, raises `SeedPlacementError(WorktreeSeedError)` carrying `placed`, with a message naming the failed entry, the placed entries and the unplaced entries by position (never by path). `seed_existing_worktree` converts it to `SeedApplyRefused(placed=...)`, and turns any other `OSError` (ENAMETOOLONG) into a refusal. The CLI prints `placed:` lines after `REFUSED:`. Unreadable working `secret_file_guard` options now refuse `seed-worktree` explicitly (previously a raw `ProtectedSetUnreadable` traceback).
- **F6.** `refuse_uncommitted_protected_links` (public, in `utils/worktree_seed_apply.py`) is the one check both routes run before anything is placed: the `worktree_create` handler (before `git worktree add`) and `seed-worktree`. It judges with the shipped defaults, the working set (when readable) and the committed set; committed guard options that cannot be read refuse every unlisted entry. A committed config whose `worktree_create` handler is disabled is an empty baseline. Parity test: `test_both_routes_refuse_the_same_uncommitted_protected_entry` asserts identical messages.
  - **No declared invariant pair added.** `scripts/qa/declared-invariant-pairs.yaml` extractors compare literal sets (dict keys, tuples, regex alternations); none expresses "both callers call function X". Sharing one function plus the parity test is the defence here.
  - **Behaviour change at creation:** a protected link entry (including one protected only by the shipped defaults, such as `.vault-pass`) is now refused at creation unless the config committed at HEAD lists it. A client that never commits its daemon config loses protected-link seeding at creation; recorded in release note 019.

## Left (F1 to F5)

See the next section of this file once that work lands.
