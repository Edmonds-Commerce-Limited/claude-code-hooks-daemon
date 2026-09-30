# Integration batch B2

Branch `worktree-integration-b2`, forked from main at `954922b7`. The six
branches are merged `--no-ff` in the order the brief gave. Main's later
ledger-only commits are merged last, up to `652c9800`. The work is complete at
`1166d17d`. The commit that adds this report sits on top of it and is the
branch HEAD. Nothing was pushed and nothing was merged into main.

## Merges and conflict resolutions

| #   | Branch (tip)                           | Merge commit | Conflicts and resolution                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | -------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `worktree-n422-guards` (0694a51b)      | `fb76d640`   | `run_all.sh`: kept main's generated-doc drift check as step 31 and made the branch's unreachable-handle-branch check step 32. `project_containment.py` and `sed_blocker.py`: kept main's `acceptance_path` import (`scratch_path` no longer exists on main) and added the branch's `command_evasion` import.                                                                                                                                                     |
| 2   | `worktree-d-00449` (28abcf6e)          | `ba9ee6a9`   | `recovery_cron_advisor.py`: kept main's `acceptance_path` import and added the branch's `BoundedFifoMap` import. The 00466 NIGGLES.md and PLAN.md are the union of both sides, with the branch's N16 renumbered N23 (see below). `write_clobber_guard.py` merged with no conflict, and both behaviours hold: the `BoundedFifoMap` session store and n422-guards' Read/Edit/Write recording. The guard's three test files and the contention tests pass together. |
| 3   | `worktree-n466-docs-corpus` (e9d318c1) | `a319318e`   | 00466 PLAN.md: N8 (main) and N9 (branch) are both Remedied. 00466 NIGGLES.md: kept the branch's N9 remedy paragraph and main's Remedied N8 heading. N9's heading now carries the same "✅ Remedied" marker. The JOURNAL day-files for 00466 and 00468 have their entries interleaved in timestamp order.                                                                                                                                                         |
| 4   | `worktree-n422-owner-a` (faeb3c0a)     | `d28b25fa`   | No textual conflicts. 00422 PLAN.md Task 2.1 said "Six rows remain". It now names the plan behind each remaining N5 row, is ticked, and links the owner-a report, which checked every row against the code.                                                                                                                                                                                                                                                      |
| 5   | `worktree-d-cron` (3ffd713c)           | `cdf8eb46`   | `recovery_cron_advisor.py` imports: 00449's `BoundedFifoMap`, the branch's `config_cache` and `cron_tick`, and main's `acceptance_path`. Both bodies merged with no conflict. The three per-plan maps are `BoundedFifoMap`s, and `CANONICAL_CRON_PROMPT` carries `[tick:failsafe]` and the declared-cron completion note.                                                                                                                                        |
| 6   | `worktree-n422-owner-b` (2fc4a049)     | `63dea9f0`   | Both sides kept, as the two owners agreed. `persistent_cron_assertor.py`: `handle()` drops a paused job from the create list, and `_render_job` renders every remaining job with its `[tick:job:<id>]` line. `cron_enforcement.py`: both import blocks are kept. `render_missing_crons_reason` keeps the sentinel, and `verdict_for_missing_crons` renders the unpaused jobs through it for both stop enforcers. truth-changes: union of both sides.             |
| 7   | `main` (652c9800, ledger only)         | `1166d17d`   | 00466 PLAN.md and NIGGLES.md are the union of both sides. Main's N24-N29 go above N23 in NIGGLES.md (newest first) and after it in the table (number order).                                                                                                                                                                                                                                                                                                     |

Other integration commits:

- `35950150` adds two tests that exercise the pause and the sentinel together.
  In `test_persistent_cron_assertor.py`, a paused job gets no sentinel and no
  create instruction, and the job still asked for keeps its sentinel. In
  `test_cron_stop_enforcer.py`, the deny hands over only the unpaused job's
  sentinel. These tests guard the merge. They are not a behaviour change, so
  they passed on first run.
- `08c4be0e` fixes a doc_truth defect (see "Found at integration").
- There are five renumbering commits, listed below.

The generated `CLAUDE.md` block and `.claude/HOOKS-DAEMON.md` merged with no
conflict. `regenerate-docs` and `generate-docs` produced no diff, and
`generated_doc_drift` passes.

## Renumbering map

00466 niggle: d-00449's **N16 → N23**. The heading moved to the top of
NIGGLES.md, and the PLAN.md row now sits after N22. The 00449 journal line and
the 00449 report were updated to match. The other N16, filed on
`worktree-n466-guard-defects`, is untouched.

Release notes follow on contiguously from main's 01-20, in merge order:

| Branch                        | Old                                              | New |
| ----------------------------- | ------------------------------------------------ | --- |
| n422-guards                   | 20-guards-now-see-a-command-behind-do-then-...   | 21  |
| n422-guards                   | 21-rewriting-a-file-you-created-or-edited-...    | 22  |
| d-00449                       | 54-concurrent-requests-no-longer-crash-...       | 23  |
| n466-docs-corpus              | 13-docs-qa-and-doc-truth-now-respect-gitignore   | 24  |
| n466-docs-corpus (00468 T3.1) | 29-format-markdown-and-find-comment-blocks-...   | 25  |
| n422-owner-a                  | 23-a-fresh-config-now-ships-...                  | 26  |
| n422-owner-a                  | 24-a-journal-correction-is-now-its-own-category  | 27  |
| n422-owner-a                  | 25-subagent-reports-now-default-to-...           | 28  |
| d-cron (00388)                | 48-awaiting-human-now-survives-other-crons-...   | 29  |
| d-cron (00394)                | 49-the-failsafe-recovery-cron-now-covers-...     | 30  |
| n422-owner-b                  | 26-a-declared-cron-can-be-paused-for-one-session | 31  |
| n422-owner-b                  | 27-the-supervisor-no-longer-undoes-an-effort-... | 32  |

Every note was renamed with `git mv`. References were updated in the 00449,
00388 and 00394 PLAN.md files, in the 00466 journal, and in the subagent
reports of n422-guards, d-00449, n466-docs-corpus, owner-a, owner-b and
d-cron. No release note links to another note.

## QA (targeted, from the worktree, own venv)

- `llm_qa.py format lint type_check pyright shell_check error_hiding shell_audit capture_corruption semgrep plan_qa docs_qa british_english sensitive_content repo_hygiene generated_doc_drift handler_reference doc_truth`:
  17/17 PASSED after the six merges. After the doc_truth fix and the main
  merge, `format lint plan_qa docs_qa british_english sensitive_content repo_hygiene generated_doc_drift handler_reference doc_truth`
  passed 10/10, and doc_truth scanned 1788 docs.
- pytest ran 49 files: every test file the branches added or changed (from
  `git diff --name-only 954922b7...HEAD -- tests/`), plus the tests for every
  module where a conflict was resolved or two branches merged: project
  containment, sed_blocker, reference_repo_freshness,
  idle_housekeeping_advisor, the llm_qa/run_all wiring, init_config, the
  handler reference, auto_continue_stop and shell_segmentation. Result:
  **2127 passed, 1 xfailed**. The xfail is the known Plan 00260 sed_blocker
  marker, which is on main already.
- YAML: truth-changes v3.67.0, config-changes v3.67.0, truth-changes v3.59.0,
  `.claude/hooks-daemon.yaml`, `.yaml.example` and
  `declared-invariant-pairs.yaml` all load with the venv Python.
- The worktree daemon was restarted and reported RUNNING before every commit.

## Exclusion audit

I read every line added under `git diff 954922b7...HEAD -- 'scripts/qa/*exclusion*' '*exclusions*.json' '*.yaml'`.
None of it adds a QA exclusion, suppression or skip. The additions are these:

- rows in `declared-invariant-pairs.yaml`, which make checks stricter;
- the new semgrep rule. Its `pattern-not-inside: with $LOCK:` narrows what
  the rule matches. It is not a path exclusion;
- config entries for the new handlers and the declared failsafe cron;
- manifest entries.

A wider scan of added code lines found no `noqa`, `type: ignore`, skip or
xfail markers.

**One item for your judgement.** n466-docs-corpus adds
`tests/unit/qa/test_qa_corpus_git_visibility_audit.py`. It is a ratchet table
with eight `ALLOWLISTED` corpora, each with a reason: walkers that
deliberately do not go through `git_visible_paths`. It exempts nothing from
an existing gate. It declares where a new class rule does not apply, and it
has the same shape as `test_qa_package_dependency_direction.py`. I kept it,
but it is the one addition that reads like an allowlist.

## Found at integration

- **doc_truth scanned 0 docs in every worktree.** Its noise-directory filter
  matched names in the ABSOLUTE path, and every agent checkout lives under
  `untracked/worktrees/`. So the gate passed without reading anything. The
  RED test is `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`.
  Fixed in `08c4be0e`: the count went from 0 to 1785 docs, with 0 violations.
  This is the class main already filed as 00466 N26 (for skill_references).
  N26 now records the cause and these instances.
- **shell_audit is vacuous from a worktree for the same reason.** It is not
  fixed. I ran it by hand over the relative `scripts/` and skill-scripts
  directories: 52 files, no violations. `check_skill_references.py` very
  likely has the same cause, and `check_github_urls.py` should be checked.
  Both are noted on N26.

## Not resolved here, left for the coordinator

- The ledger rows the owner-a report asks the coordinator to record: the
  00422 N1 and N3 rows, N5 Task 2.2, and the N4/N7 rows for owner-b. Only
  Task 2.1 was in my brief.
- Plans 00388, 00394 and 00449 were not archived, as the brief asked.
