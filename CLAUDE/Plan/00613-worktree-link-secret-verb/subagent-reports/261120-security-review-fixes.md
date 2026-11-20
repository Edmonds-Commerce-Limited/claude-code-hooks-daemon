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

## F1 to F5 (second unit)

Commits: `e5f486201` (F1, F3), `939ce272c` (F4), `24bc33d2c` (F5), and the commit carrying this section (F2 niggle, release note). Tests: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_seeded_link_bypasses.py` (both daemon-root placements, 140 cases, red first).

- **F1 closed.** `fd`/`fdfind` `-x/--exec/-X/--exec-batch` (clustered, `--exec=`) are modelled as walkers that run a reader per file, judged as following every link below their roots (`_fd_exec_roots`; default root cwd, `--search-path`, `--base-directory`). `bfs` and `gfind` share `find`'s grammar (`_FIND_COMMANDS`). ugrep was already a grep; ag/ack have no exec.
- **F3 closed.** `_reads_of_roots` expands brace operands (`expand_braces`, the file-read expander) before placing roots, so it covers every recursive reader and `find` roots; a group that cannot be listed (cap, quoting) fails closed as a read of everything.
- **F4 closed.** A `link/..` physical root (`Read.physical`) that lies outside the daemon's project fails closed in `protected_reached` (`_outside_project`): the index lists nothing there.
- **F5 closed.** `_MadeLink` records `ln -s`/`--symbolic`, `cp -s`, `hooks-daemon seed-worktree` statements; a later statement that is not content-free and names the destination (at, above or below it; unplaceable names count) is judged as a read of where the link leads. The target is judged as if the link existed, so a link to a tree holding nothing protected stays allowed. `ln -s X y` alone, and later `ls`/`echo`, stay allowed.
- **F2 not closed.** Recorded as N683 in the open ledger `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`: the one-liner route extracts string literals and models no library call's root, so denying `copytree`/`cpSync`/`os.walk` would be a new interpreter model.

Residuals:

- A link whose target is outside the project fails closed for any later reader naming its destination, whether or not the target holds a protected file (also the F4 shape, `link/..` leaving the project). `hooks-daemon seed-worktree wt && <reader of wt>` is denied whenever the project has any protected file, because the seed list is config the hook does not read.
- A worktree-root daemon still allows a direct non-following recursive read of a main-checkout directory (`grep -r x <main>/conf`, `fd . <main>/conf -x cat`): the blind spot the review routed to F-GAP, not fixed here.
- F5 matches by destination path; a link reached through a variable the hook cannot place is covered only when the link's own destination is unplaceable.
