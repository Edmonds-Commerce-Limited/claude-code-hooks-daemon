# Plan 00463 gate fix 3 (Sonnet 5)

## Task 1: merge main

Merged `main` (`fe14348e7`) into `worktree-plan-463-full-qa-gate`
(`git merge --no-ff FETCH_HEAD`). Conflicts:

- Rename/rename on the plugin-agents release note: our branch had renamed
  `34-claude-code-plugin-agents-...md` to
  `95-claude-code-plugin-agents-...md`; main had independently renamed the
  same original file to `034-claude-code-plugin-agents-...md` (three-digit,
  ledger N109, already on main). Content identical. Kept main's `034-...`
  file and dropped our `95-...` duplicate.
- Everything else auto-merged (the `CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`
  ledger table included: our branch's own earlier N2 row edit
  ("Remedied by Plan 00463") was the only change relative to the merge
  base, so git took it cleanly with no conflict — `merge_ledger_table.py`
  was not needed).

Renumbered this branch's own four release notes (the code-file-reader
parser, the full-QA-gate note, find -exec/merge-base, and
eval-of-shell-setup) from their colliding `34`/`94`/`96`/`97` numbers to
three-digit `130`-`133` (main's highest is `110`). Ran
`bin/hooks-daemon regenerate-docs`: no diff (already deterministic),
and it fixed failure 1
(`test_every_earning_handler_has_a_section_in_claude_md`) as a side
effect of the merge bringing in main's CLAUDE.md content.

Merge commit: `16eea2aff`.

## Task 2: the three enumerated failures

1. `test_every_earning_handler_has_a_section_in_claude_md` — fixed by the
   merge + `regenerate-docs` (no separate action needed).

2. `test_every_blocking_without_safety_handler_is_audited[pre_tool_use/subagent_full_qa_blocker]` —
   `subagent_full_qa_blocker` is BLOCKING but carries no SAFETY/ADVISORY
   tag. Read the handler: it denies a sub-agent's own declared full-suite
   QA run so the coordinator's batched gate is the only full run — a
   scheduling/resource-contention gate, not a dangerous-action guard (same
   shape as `tdd_enforcement`/`plan_qa_edit`, already in the audited-blocking-only
   list). Added a row to `_AUDITED_BLOCKING_ONLY_REASONS` in
   `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py` explaining
   the call; did not add `HandlerTag.SAFETY`.

3. `test_a_lone_long_star_run_collapses_to_near_zero_cost` —
   `TestInteriorWildcardDpIsBounded` — ran 10x on the branch (10/10 pass,
   0.13-0.31s) and 3x on main (3/3 pass, one at 0.09s against a 0.1s
   budget — a close margin). Not a regression: a fixed 0.1s wall-clock
   assert flakes under host contention (concurrent worktree gates, per the
   brief's own "gate went 37/39" context), independent of whether the DP
   cost bound holds. Replaced the absolute-second assert with a
   scaling-ratio one per the standing no-wall-clock-asserts rule: min of 5
   trials for a short `"a*a"` baseline vs. min of 5 trials for the
   60,000-`*` token, asserting the long token costs at most
   `max(baseline * 20, 0.05)`s — the floor absorbs the constant-factor
   cost of handling a 60 KB string at all (which a 3-byte baseline never
   pays), the ratio is what would actually catch a collapse regression
   (an uncollapsed run costs orders of magnitude more once the DP grid
   scales with the star count, not a fraction more). Re-ran 8x: 8/8 pass.

## Task 3: a fourth failure surfaced by the merge

`tests/unit/qa/test_llm_qa_main_moved.py::TestTheReviewExamplesAgainstThisRepository::test_a_ledger_or_journal_entry_is_docs_only[.../NIGGLES.md]`
started failing (`'tested' != 'docs'`) after the merge — not listed in the
brief, not present pre-merge (gate fix 2's report confirms both
parametrised cases passed before). Traced it: this test's own
parametrisation hardcodes the currently-open ledger's real path
(`CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md`). Main's N24 fix to
`budget_exhaustion_detector.py` cites that exact path as rationale
(`` `CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md` (N46) for why ``)
— a legitimate practice this project uses elsewhere for rationale
comments. `run_changed_tests._Mapper._refers` (by design, for its general
purpose) reads any literal path citation as a real dependency, so it pulls
`budget_exhaustion_detector.py`'s own test into the ledger file's coverage,
flipping the verdict from docs to tested. The JOURNAL variant in the same
parametrize list still passed (no code happens to cite that exact
filename).

This is a structural collision, not a one-off: any currently-open ledger
will accumulate "see NIGGLES.md N`n`" citations over time as other niggles
land, so a real, live ledger path is not a stable test fixture. Verified
with the same real mapper (via a debug harness) that the two archived
ledgers under `Completed/` have the *same* problem for different reasons
(`00413` is cited as a worked-example plan number in
`plan_links.py`'s own docstring; `00419` is cited pervasively as an
unrelated numeric literal). Switched the parametrised paths to an
invented, non-existent plan number
(`CLAUDE/Plan/00000-example-ledger-for-tests/...`) that no source will
ever cite — confirmed via the same debug harness that both classify
`docs`, and confirmed the file does not need to exist on disk for the
mapper to judge it (mirrors the existing
`docs/a-page-nothing-names-yet.md` synthetic case two tests above it in
the same file).

## Task 4: verification

- `tests/unit/qa/` (whole directory): **1218 passed** (two runs; the first
  had 2 failures that were both re-run-clean in isolation — a 60s
  subprocess timeout from host contention, and the NIGGLES.md case above).
- `tests/unit/handlers/` (whole directory): **10278 passed**, 4 pre-existing
  unrelated collection warnings (`TestType` `__init__`, present before this
  branch).
- `ruff check`, `black --check`, `mypy`, `pyright` on the three files I
  edited (`test_pretooluse_fail_closed_tagging.py`,
  `test_llm_qa_main_moved.py`, `test_secret_file_matching.py`): all clean.
- Daemon restarted from this worktree: `Daemon: RUNNING`.

## Commits

- `16eea2aff` — merge main (task 1).
- `3b5c28029` — the three fixes (tasks 2-3).
- This report's commit.

Gate queued DETACHED per the brief at HEAD `3b5c28029`; team-lead cancelled
it before it landed.

## Task 5: N123, team-lead follow-up

Team-lead flagged that the ratio-based fix for
`test_a_lone_long_star_run_collapses_to_near_zero_cost` still asserted on
wall-clock time (a `max(baseline * 20, 0.05)` floor), still exposed to the
same host-contention flake main itself shows (0.09s against a 0.1s budget).
Replaced it with a deterministic WORK count instead of time: added
`dp_cell_counter()` to `secret_file_matching.py`, a `contextvars.ContextVar`-backed
context manager that counts the DP grid cells `_globs_can_intersect`
visits (a `ContextVar`, not a module global, per the no-per-request-state
rule — no state leaks across concurrent calls, production pays nothing
beyond a `None` check). The test now asserts the 60,000-`*` token's cell
count EQUALS a literal `a*a` baseline's — after the star-run collapse the
two are the identical 3-character string, so the grids are identical in
size, deterministically, on every host, not merely small.

RED: proved on a `git archive` scratch copy of the current (uncommitted)
working tree with the collapse substitutions short-circuited
(`if False and "**" in a: ...`) — the length cap fires and skips the DP
entirely, dropping the long token's cell count to 0 against the
baseline's 9, failing the equality assertion as expected.

Logged as ledger N123 (NIGGLES.md write-up + PLAN.md table row, both
✅ Remedied). `tests/unit/utils/test_secret_file_matching.py` (whole file):
335 passed. `tests/unit/plan_qa` (ledger/PLAN.md edits): passed within the
1181-test run. `ruff`, `black`, `mypy`, `pyright` on the two touched files:
all clean. Daemon restarted: `RUNNING`.

Commit: `a99332d4d`.

Gate queued DETACHED per team-lead's instruction, only after this commit
and this report:
(`setsid -f bash /workspace/untracked/scratch/gate.sh worktree-plan-463-full-qa-gate`).
