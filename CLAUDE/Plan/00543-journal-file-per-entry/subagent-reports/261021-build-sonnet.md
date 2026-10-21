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
