## 06:37 · action · —

Tasks 2.2, 2.3, 2.4 and the two Task 2.1 follow-ups built.

Task 2.2 (audit line). `seed_worktree` takes a REQUIRED keyword `audit: LinkAudit` (log path, protected-set loader, session id). Decisions, each pinned by a test in `tests/unit/utils/test_worktree_seed_link_audit.py`:

- Classified at PLACEMENT, only for links actually placed (a skipped or absent-optional entry is not read), so validation of a link-only config still never reads the protected set (Task 2.1 pin intact). The set is read once per creation.
- Log: `worktree-seed-protected-links.jsonl` under `install_layout.get_untracked_dir(<main checkout>)`, append-only, owner-only (`private_io`). Keys pinned exactly: at, verb, outcome, check, worktree, path, pattern, unclassified_reason, session_id. No numeric field, so no size can creep in.
- A linked DIRECTORY is judged on every path reachable through it (the copy walk, following links).
- Unreadable protected set: links are NOT refused (link mode behaves as before); every placed link is logged `linked-unclassified` with the reason. Same for a directory that cannot be walked in full.
- The line is written BEFORE the link. A log that cannot be appended refuses that link and raises `WorktreeSeedError` (entry named by position). This runs after `git worktree add`, so the worktree exists and entries placed earlier stay placed: a loud failure, not a half-seeded silent one. Not changed: the handler does not undo the worktree on a seeding failure (pre-existing behaviour for any placement error).
- The copy refusal text no longer says "seed it with mode: symlink" (the Q5 gate forbids advising a link).
- RED d53f3f31d (collection failure: names absent), GREEN bb55b1f61. Two handler wiring tests were added after green and were not seen failing.

Task 2.3: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_worktree_link_pin.py`, 20 cases (from the main checkout, from inside a worktree, chained) asserting deny AND `R-SECRET-BASH-MENTION`. A pin cannot fail first without breaking the guard; it passed on first run (2f6d2e6d6).

Follow-up 1: `check-worktree-seed` now reports `refused_copies` (JSON and a REFUSED text section; counts as drift) using the executor's own `protected_copy_refusals` over the guard options of the config FILE it was given, read strictly via the shared `protected_patterns_from_options` (also used by `load_protected_patterns_strict`). Unreadable options refuse every copy entry. RED cacb88a18 (11 failing), GREEN f9ea6da53.

Follow-up 2: the copy-mode example in `core/worktree_seed.py` and `.claude/hooks-daemon.yaml.example` now names `.claude/settings.local.json` (checked against the default globs: unprotected); the example comment says a protected path is refused in copy mode. Parse-only tests that still spell the old name in copy mode were left: they never run the protected-set check.

Task 2.4: callout `CLAUDE/UPGRADES/UNRELEASED/release-notes/009-worktree-seed-protected-copy-refused-and-links-audited.md` (remove the copy entry; link mode is not refused; it does not recommend linking).

Left for the coordinator: `worktree_seed_suggestions` still proposes protected-name candidates (the `*.secret*` shapes) and the report renders them in the default mode (symlink). That is shipped behaviour that eases seeding a protected file, which the Q5 gate frowns on; changing it is a separate decision (drop protected candidates from suggestions, or list them without a mode).
