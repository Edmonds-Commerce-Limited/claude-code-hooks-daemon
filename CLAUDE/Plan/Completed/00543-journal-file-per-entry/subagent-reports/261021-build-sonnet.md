# Build report, Plan 00543 (#135)

## Tasks 2.1 and 2.4

Done: `mkplan.bash --journal` and the plan scaffold now write one NEW entry file per entry; a test shows two same-day
branches merge cleanly. Both copies of the script (`CLAUDE/Plan/mkplan.bash` and
`src/claude_code_hooks_daemon/install/templates/mkplan.bash`) stay byte-identical.

### Writer (Task 2.1)

- New helpers `_write_journal_entry` and `_journal_day_has_entry_at` in `mkplan.bash`.
- Path: `JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<6 hex>.md`; content is the heading, a blank line, the body. No preamble.
- One `date -u +%Y-%m-%d' '%H%M%S` call gives folder date and time. Hex is 3 bytes from `/dev/urandom` via `od`.
  The file is created under `noclobber`, so a name clash fails loudly. CLI, UTC stamping and validation order unchanged.
- A correction's `--ref` is looked up in that day's legacy day-file AND every file in that day's entry folder.
- Plan scaffold: the template's seeded entry (from `## {{TIME}}` on) is written as an `action` entry file. The
  template preamble is no longer copied anywhere; `_JOURNAL_TEMPLATE_.md` itself is untouched (Task 2.3).
- `--resolve-conflict` untouched (legacy day-files only).

### Red output (tests written first, `tests/unit/scripts/test_mkplan_journal.py`)

Before the script change: `16 failed, 20 passed`, for example
`TestEntryFileLayout::test_an_entry_lands_in_a_dated_folder_with_a_stamped_name - assert 0 == 1`,
`test_no_legacy_day_file_is_created - assert [PosixPath('/...26-10-21.md')] == []`,
`test_a_correction_may_name_an_entry_file_of_an_earlier_day - --ref 26-01-01/10:50 names no entry`,
and the UTC cross-zone tests (`AssertionError: []`, no entry files). After: `36 passed`.
The scaffold-seed test and the Task 2.4 merge tests were written after the script change and passed first time
(the scaffold behaviour is covered by the changed `test_plan_workflow.py` test, which was red before the change).

Old day-file tests were rewritten to the new layout: sentinel and preamble tests became layout tests, append-only
tests became `TestNeverTouchesExistingFiles` (a same-day legacy day-file is not appended to).

### Task 2.4

`TestSameDayJournallingOnTwoBranchesMergesCleanly`: scratch git repo, base commit, two branches each run the real
writer for plan 42 with the SAME category on the same UTC day, then `git merge-tree --write-tree` exits 0 and the
merged tree holds exactly two entry files in one day folder. A second case starts from a base that already holds a
legacy same-day day-file.

### Tests run (pytest, touched files plus neighbours; no llm_qa)

`tests/unit/scripts/test_mkplan_journal.py`, `tests/unit/install/test_plan_workflow.py` (one test updated:
`TestMkplanScaffoldsJournal::test_scaffolds_journal_when_template_present`), plus unchanged and green:
`test_mkplan_template_parity`, `test_mkplan_resolve_conflict`, `test_mkplan_scan_depth_parity`,
`test_mkplan_counter_drift`, `test_mkplan_dedupe_count`, `test_mkplan_worktree_lock`, `test_journal_category_sync`,
`test_journal_sentinel_sync`, `plan_qa` ordering, future-dated, counter-sanity and command-journal tests.
Command note: this worktree's venv imports main's `src`, so pytest needed `PYTHONPATH=$PWD/src` and `--no-cov`.

### For the next agent (Tasks 2.2 and 2.3)

Nothing in the new layout is read by the daemon yet. Not fixed by me, by design:

- `plan_qa/model.py` `_scan_journal` (freshness) and `paths.py` `classify` see only day-files; `journal-freshness`
  will report a plan journalled only through entry files as stale or empty until `_scan_journal` reads the folders.
- `journal-entry-ordering`, `-future-dated`, `-dayfile-naming`, `-dayfile-is-today` ignore entry files (nested files
  are `JOURNAL_OTHER`), so they do not flag them, and they do not yet enforce "never edited" on them.
- `plan_journal_guard` `_dayfile_target` does not yet recognise `JOURNAL/<date>/<file>`, so a hand-written entry in a
  new folder is NOT denied until Task 2.2 lands. Priority item.
- `_JOURNAL_TEMPLATE_.md` still describes day-files and keeps the UTC sentinel (pinned by `test_journal_sentinel_sync.py`).
  The plan-template comment in `mkplan.bash` (about line 866, `JOURNAL/$padded-Journal-YY-MM-DD.md`) is unchanged, as are
  the `--journal` usage text ("today's day-file") and the die message for a dangling correction wording in
  `journal_usage`. `PlanJournalling.md`, `core/PlanWorkflow.core.md`, guard `get_claude_md` are Task 2.3.
- No release note written (not in my scope).
- Other tests that scaffold or read day-files and were NOT run: `tests/unit/handlers/pre_tool_use/test_plan_journal_guard.py`,
  `test_plan_qa_commit_gate.py`, `test_journal_remediations_name_the_tool.py`, `tests/acceptance/test_install_sh_end_to_end.py`.

## Task 2.2 readers and N524a

**N524a done** (`ecfa5a3e3`). `docs_qa/checks/duplicate_block.py` leaves plan journals out of the hash index, so a
journal is never a reporter or a partner, and it skips an EDIT of a journal. It uses
`context.policy.plan_tree.is_journal`, the same call as `pointer_resolves.py:136`. That check ignores depth, so it
covers legacy day-files and per-entry files, in live and archived plans. A folder named `JOURNAL/` outside the plan
tree is still judged (pinned).

Red output, `tests/unit/docs_qa/checks/test_duplicate_block.py`, before the fix:

```
FAILED ...TestPlanJournalsAreNotScanned::test_sweep_ignores_journals_sharing_a_block
FAILED ...TestPlanJournalsAreNotScanned::test_sweep_never_names_a_journal_as_a_partner
FAILED ...TestPlanJournalsAreNotScanned::test_edit_of_an_entry_file_is_not_judged
FAILED ...TestPlanJournalsAreNotScanned::test_edit_of_a_doc_does_not_name_a_journal_partner
4 failed, 22 passed
```

Green: `tests/unit/docs_qa` 652 passed. ruff and mypy are clean on the touched file.

**The plan_qa readers are not started.** I stopped at the subagent context budget before editing any plan_qa file.
The design is worked out file by file, including parity with the guard's conflict-marker and HEAD-restore
exceptions, and the new COMMIT half of `journal-dayfile-is-today`. It is in the handoff
`untracked/scratch/261021-ae87dd9c72ec3433a-handoff.md`. `same-commit-plan-doc` keys on `PLAN.md` and never reads
journals, so it is unaffected and there is nothing to pin.

## Task 2.2 plan_qa readers

Done, one commit each, TDD (red counts quoted):

- `plan_qa/model.py`: `JournalEntryFileName` (`is_valid_time`, `is_valid_date`, `date`, `label`),
  `is_journal_entry_folder_name`, `journal_entry_folder_date`, `parse_journal_entry_path`; `_scan_journal` counts a
  date folder holding a valid entry file, so freshness reads entry folders (handoff item 9's freshness pin is
  `TestPlanFolderJournal::test_entry_folder_*` in `tests/unit/plan_qa/test_model.py`). Red: collection error. `31f2196d0`.
- `plan_qa/paths.py`: `PlanFileKind.JOURNAL_ENTRY`, in `_JOURNAL_KINDS`. Red: collection error. `188c71027`.
- `checks/common.py`: `JournalEditTarget.entry_folder`, `is_entry_file`, `journal_date`; `journal_edit_target` and
  `journal_tree_targets` include entry files (malformed names too). Red: 4 failed, 15 passed. `e3b984a04`.
- `journal_append_only` skips entry files; `journal_dayfile_naming` checks entry grammar, folder date, UTC time,
  category. Red: 6 failed, 22 passed. `3e4eb4579`.

Left: handoff items 6 (`journal_entry_ordering`), 7 (`journal_entry_future_dated`), 8 (`journal_dayfile_is_today`
EDIT reframe and COMMIT half), 9 (`has_staged_journal_entry` pins), then Task 2.3. Handoff:
`untracked/scratch/261021-ab83fba2ca446f2ac-handoff.md`.

## Task 2.2 readers, items 6-9

Items 7, 8 and 9 are done; item 6 (`journal-entry-ordering`) is left, so Task 2.2 is not ticked.
Handoff: `untracked/scratch/261021-a1587e84e888de63f-handoff.md`.

- Item 7, `journal-entry-future-dated`: an entry file takes its date from its folder (`target.journal_date`) and
  is always judged on the UTC clock. Red: 2 failed, 18 passed. `e6b427468`.
- Item 8, `journal-dayfile-is-today`, EDIT half: writing to any journal file that already exists is a finding.
  There are three exceptions: a no-op write, removing only conflict markers, and restoring the HEAD bytes.
  Creating an entry file is clean, and creating a legacy day-file keeps the not-today rule.
- Item 8, COMMIT half: it reports a staged M or D of a JOURNAL_ENTRY path, or an R whose staged text differs from
  the HEAD text of `old_path`. The level comes from the today-only mode, with `level_for_plan` applied when that
  mode is BLOCK. `CHECKS` is now `(EDIT_CHECK, COMMIT_CHECK)` and is registered in `checks/__init__.py`.
- Item 8, shared code: `is_conflict_marker` and `only_conflict_markers_removed` are now public in
  `plan_qa/model.py`, and `plan_journal_guard` imports them. The `WRITE_ACT_ONLY_RULES` reason is updated.
- Item 8, changed tests: two journal tests in `test_plan_qa_edit.py` now expect the new contract, because
  appending to an existing day-file is DENY. The COMMIT count in `test_runner.py` goes from 20 to 21.
  Red: 12 failed, 7 errors, 16 passed. `5485524fd`.
- Item 9: pins show that a staged new entry file satisfies `has_staged_journal_entry`
  (`test_journal_entry_with_progress`, `test_journal_completion_entry`). They pin existing behaviour, so there was
  no red phase. `7fbbd2098`.

Targeted QA passes: `tests/unit/plan_qa` plus `test_plan_qa_edit`, `test_plan_qa_commit_gate` and
`test_plan_journal_guard`, 1310 tests. mypy and ruff are clean on the touched sources.

## Tasks 2.2 item 6 and 2.3

- `5c3696dee`: `journal_entry_ordering` judges entry files by folder and name (Task 2.2 item 6); 42 tests green.
- `c3b463aac`: Task 2.2 ticked in PLAN.md.
- `fa3342b41`: Task 2.3, first part. `mkplan.bash` usage text, correction comments and scaffold comment (both
  copies, byte-identical), the plan and journal templates, and the `PlanJournalling.md` intro, contracts table
  and "Reading a journal" section.
- `5df5ce68b`: Task 2.3, source strings and docs. `JOURNAL_BODY_FILE_HINT` now says the tool writes a NEW file
  under `JOURNAL/YYYY-MM-DD/`; the `journal-dayfile-is-today` statement and remediation say an existing journal
  file is closed; the `journal-completion-entry` and `journal-folder-present` remediations, the `pipe_blocker`
  guidance, the `plan_workflow` table, `plan_qa_edit` text and acceptance tests, `markdown_table_formatter` and
  `plan_time_estimates` descriptions, `docs/PLAN_SYSTEM.md` and `docs/guides/HANDLER_REFERENCE.md` describe
  entry files. No test pinned a changed string. Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/009-plan-journal-is-one-file-per-entry.md`. Targeted pytest (1257
  tests across plan_qa, plan_qa_edit, plan_workflow, pipe_blocker, plan_time_estimates, markdown_table_formatter)
  and `check_handler_reference.py` pass.
- Left for the coordinator: the `<hooksdaemon>` block in CLAUDE.md is rebuilt from the running daemon, so it
  updates on a daemon restart (`regenerate-docs` ran but the loaded code was stale). `comment_changelog` and
  `validate_instruction_content` still say "JOURNAL/ day-file" as a destination for narrative.
