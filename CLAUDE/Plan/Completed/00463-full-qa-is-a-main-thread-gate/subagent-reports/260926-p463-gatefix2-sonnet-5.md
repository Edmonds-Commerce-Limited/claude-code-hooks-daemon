# Plan 00463 gate fix 2 (Sonnet 5)

## Task 1: merge main

Merged `main` into `worktree-plan-463-full-qa-gate` (`git merge --no-ff main`).
Conflicts:

- `CLAUDE.md`: the whole file is the auto-generated `<hooksdaemon>` block;
  took main's version (identical span markers, both sides regenerated),
  then restarted the daemon to confirm it stays deterministic.
- `CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`: resolved with
  `merge_ledger_table.py`, which reported `rows=97 differs_from_main=['N1'] only_on_branch=[]` and merged the ledger table cleanly. Made the trivial
  N1 row edit (`| N1 |` → `| N1  |`) as instructed; a formatter hook
  subsequently re-aligned the table's pipes.
- `CLAUDE/Plan/00466-niggles-ledger-sixteen/JOURNAL/00466-Journal-26-09-25.md`:
  both sides had appended a new entry (ours: 19:32 N2 re-append; main's:
  23:22 journal-ordering correction). Kept both, in chronological order,
  using an `Edit` that only *removed* the conflict-marker lines (add-line
  count and heading count both stayed at or under the pre-edit total), which
  `plan_journal_guard` allows without going through `mkplan.bash --journal`
  (that guard denies added lines/headings, not a deletion/reordering).

Renumbered this branch's four colliding `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
files (main runs 01-93; this branch's own commits `f20de39a3`/`42be098d6`
had independently claimed 33-36) to 94-97 via `git mv`:
`33-full-qa-is-the-coordinators-gate-...` → `94-...`,
`34-claude-code-plugin-agents-are-now-recognised-...` → `95-...`,
`35-find-exec-and-a-merge-base-listing-are-now-followed.md` → `96-...`,
`36-eval-of-shell-setup-output-runs-no-qa-and-is-allowed.md` → `97-...`.
No other file referenced the old numbers.

Merge commit: `6a9884a66`.

## Task 2: why the two 00466 files were judged `tested`

**Cause**: `scripts/qa/changed_tests_map.yaml` declares
`path_glob: "CLAUDE/**/*.md"` → `tests/integration/test_documented_hook_probes_are_marked.py`.
That declared rule is over-broad: the real test globs `CLAUDE/**/*.md` but
then drops everything under `CLAUDE/Plan/` and `CLAUDE/UPGRADES/`
(`_EXCLUDED_PREFIXES`, except `CLAUDE/UPGRADES/upgrade-template/` which
`_INCLUDED_DESPITE_PREFIX` puts back) — the test never actually reads a
plan ledger or journal file. Because the declared rule didn't mirror that
exclusion, `run_changed_tests.select_tests` credited any `CLAUDE/**/*.md`
path, including the two 00466 files, with a "test that reads it", so
`llm_qa.py`'s `judge_path` returned `tested` instead of `docs`.

**Verdict**: the classifier is wrong, not the test's expectation. A plan
ledger/journal is documentation; the declared-rule DSL just had no way to
express "this glob, minus that subtree" before this fix, matching the
brief's own framing: *"A plan ledger that a test cites by path is still
documentation."*

**Fix**: added `path_exclude` (a list of `Path.glob`-style patterns) to the
declared-rule schema in `scripts/qa/run_changed_tests.py`
(`DeclaredRule.excludes`, `_KEY_PATH_EXCLUDE`, `parse_declared_rules`).
`DeclaredRule.matches()` now returns `False` for any path also matched by
an `excludes` pattern, before checking the main glob. TDD: added RED tests
in `tests/unit/qa/test_run_changed_tests.py` first (malformed-`path_exclude`
cases, an exclusion test, and a re-inclusion test mirroring
`_INCLUDED_DESPITE_PREFIX` via two ORed rules), confirmed they failed
against the unmodified module, then implemented.

Updated `scripts/qa/changed_tests_map.yaml`'s `CLAUDE/**/*.md` rule to add
`path_exclude: ["CLAUDE/Plan/**", "CLAUDE/UPGRADES/**"]`, and added a
narrower rule for `CLAUDE/UPGRADES/upgrade-template/**/*.md` (same test) to
mirror `_INCLUDED_DESPITE_PREFIX`'s re-inclusion.

Both previously-failing parametrised cases now pass:
`test_a_ledger_or_journal_entry_is_docs_only[.../NIGGLES.md]` and
`[.../JOURNAL/00466-Journal-26-09-24.md]`.

## Task 3: verification

- `pytest tests/unit/qa/` (whole directory): **1218 passed**.
- `ruff check` on `scripts/qa/run_changed_tests.py` and
  `tests/unit/qa/test_run_changed_tests.py`: clean.
- `black --check` on both: clean (target-version parse warning only, no
  reformat needed).
- `mypy` on both: 2 pre-existing `no-any-return` errors in
  `tests/unit/qa/test_run_changed_tests.py` (confirmed present in the
  pre-merge `HEAD` copy of the file, unrelated to this change, line numbers
  only shifted because of the new tests inserted above them).
- `pyright` on both: 0 errors, 0 warnings.
- Daemon restarted from this worktree: `Daemon: RUNNING`.

## Commits

- `6a9884a66` — merge main (task 1).
- This report's commit — the `path_exclude` fix (task 2) plus this report.

Gate queued in the background per the brief
(`bash /workspace/untracked/scratch/gate.sh worktree-plan-463-full-qa-gate`);
not waited on.
