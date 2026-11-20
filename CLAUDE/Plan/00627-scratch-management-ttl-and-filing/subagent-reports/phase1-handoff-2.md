# Plan 00627 Phase 1: handoff after Task 1.4

Branch `agent-acff915e4bf3b86e6-0a26f829` (worktree `.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`), pushed. Not merged to main. `origin/main` is merged in (the carried `utils/bounded_walk.py` and `utils/resolution_failure.py` are now identical to main's). The `CLAUDE/Plan/README.md` conflict was the 00627 row on both sides; it was resolved to ONE row (the branch's newer wording), not two.

Read [phase1-handoff-1.md](phase1-handoff-1.md) first: its venv, test-helper and Tasks 1.5 to 1.7 notes still hold.

## Done

- Task 1.2: `ScratchConfig` and its nested models in `config/models.py` (after `BranchesConfig`), field `Config.scratch`. Tests `tests/unit/config/test_scratch_config.py`. `tests/config/test_models.py` and `tests/integration/test_skill_surface_coherence.py` still pass.
- Task 1.3: `core/scratch_walk.py`: `walk_entry(root, name, *, now, budget, scandir) -> Bounded[EntryStats]`, `list_entries(root) -> Bounded[tuple[str, ...]]` (skips the root's `.gitignore`), `WalkBudget(seconds, max_inodes, clock)` shared across a whole sweep, `NodeKind` (DIRECTORY, FILE, SYMLINK, SPECIAL, UNREAD for an entry root that could not be `lstat`ed). `EntryStats.nodes` holds every inode (directories too, `empty=True` for a listed empty directory), paths relative to the scratch root with the entry name first, so an entry named `__pycache__` matches P2. Multi-link counts are per (dev, ino), non-directories only. Uses `os.lstat` for every inode (a test monkeypatches it to fake a second device).
- Task 1.4: `core/scratch_clock.py`: `entry_age(stats, *, now, ttl_hours, max_lifetime_hours, birth=None) -> EntryAge(age_seconds, due, lifetime_exceeded, notes)`; with no birth, `lifetime_exceeded` is None and `NO_BIRTH_NOTE` is in `notes`.

## Remaining: Tasks 1.5, 1.6, 1.7 (see handoff 1, plus these)

- Verdicts: DISPOSABLE only from a COMPLETE walk. P1 matches a regular FILE's own basename only (a directory named `qa-*` covers nothing). Coverage is judged over non-directory nodes plus empty directories.
- Carry the `.git` marker as its own field on every row (table and JSON), even when LIVE or STUCK wins first, so "repository, not judged" (R7 awaits the owner) is always visible.
- CLI: one `WalkBudget` for the whole run (the real tree is about 230k directories); the report states when it is incomplete; inject the clock for tests. The snapshot test should run both the table and `--json` over a tree with a link to outside, a FIFO and a refused directory.
- CLI memory and budget: judge each entry and drop its `nodes` before walking the next, and size the inode cap from the measured tree; otherwise a real run holds the whole tree in memory or reports incomplete.
- For Task 3.9 (not Phase 1): the walker lists a directory by path after `lstat`, so a directory swapped for a link in between would be followed. Harmless while nothing acts on the result; the removal path must use descriptors.
- QA state: pytest, black, ruff and `mypy --strict` pass on every changed file, as do the config drift tests (`tests/unit/config`, `tests/config`, the init-config, example-config and config-key tests) and `test_plan_index_navigability.py`. `./scripts/qa/llm_qa.py changed` has NOT run: two attempts queued behind another worktree's host-wide QA lock and never started. Run it first.
