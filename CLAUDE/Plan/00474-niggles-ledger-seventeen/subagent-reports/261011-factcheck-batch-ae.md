# Fact check, Plan 00474 batch AE (HEAD 203a21653)

## REFUTED

1. PLAN.md: "96 rows are fixed, dismissed, remedied or closed (✅)". Counted the status column of the 121 rows of STATUS-INDEX.md (last field of each row, since N306's row holds an escaped pipe): 100 rows carry ✅. Taking out the 2 rows that are "✅ Fixed; ⬜ Owner decision" (already counted in the 14) leaves 98. The old figure of 93 was also 2 short (old index 120 rows, same method gives 95). Correction: 98 (or 100 if overlaps are included, with a note).
2. NIGGLES.md N414 item 2: `get_written_file_paths` is "used by lint_on_edit, validate_eslint_on_write, sed_blocker and sensitive_content-style guards". Real users (grep src): lint_on_edit, sed_blocker, validate_eslint_on_write, plan_fact_check_feed. No sensitive_content use. Correction: replace with plan_fact_check_feed.

## Counts verified (PLAN.md)

- 121 rows: VERIFIED (121 table rows).
- 3 open (N417, N280, the 42 entries): VERIFIED (3 rows with ⬜ Open, exactly those).
- 14 owner decision, "including three fixed or part-fixed rows": VERIFIED (14 rows contain ⬜ Owner decision; 2 are ✅ rows, 1 is 🟡).
- 5 deliberate limit (🚫): VERIFIED (5 rows; 4 are mixed ✅ rows). The "rest (🔄, 🟡, ↩️)": 3, 2, 1 rows.

## Code claims, VERIFIED

- N416: `_INLINE_CODE_FLAG_TEXT_TOOLS` (subagent_full_qa_blocker.py:877) holds set, echo, read, declare, uniq, rm, cp, ls, diff, tr, cat, stat, du, pip, gcc/g++/cc/clang, make, zip/unzip/tar/gzip, scp/rsync/wget, less, mysql, psql. docker, perl absent as claimed. Exact basename match at :944. Test class `TestInlineCodeFlagIsNotReadOnSearchAndTextTools` at test file :3210.
- `_first_full_run` (:5177): positive match wins, first unseen returned otherwise (docstring and loop).
- N415: `_operands_run_in_process` (:4235) is an explicit-stack source-order pass with opened/texts tracking, AugAssign keeps, parameter shadowing and restore. `compile` handled in `_file_read_by`. Tests `_EDIT_AND_EXEC_FULL_RUNS` (:3916), `_REBOUND_TEXT_ALLOWED` (:3987), linearity test (:4036, 3000 bindings).
- N414: "needs update"/"needs merge" in staging_simulation.py:165-166, stdout+stderr read at :311-312. `_git_output_files` in core/utils.py handles diff/format-patch `--output`, `-C` joining, `authored=False`. `get_bash_write_targets` is used by project_containment, installed_plugin_edit_advisor, git_commit_parsing `_written_names` (:844). `SimpleCommand.reads_input` and `_reads_input` (git_commit_parsing.py:1125), `stdin_fed = fed or piped` (:837).
- N417: probe scripts `untracked/scratch/review-batch-x/run_ae_shell2.sh` and `ae_cmds2.txt` exist. N409 literal-as-command logic exists in the blocker (:3575, :3691, :3859).

## UNVERIFIABLE-HERE

- Batch AE report test totals (7507 / 2996 / 1662 / 2376 passed, black clean): needs running the suites.
- N417 "Main already denies the identical script" and "on main the same text was hidden behind an earlier unseen verdict": needs running the blocker on main against the probe script.
- N414 "Known limit: a lone quoted `'<'` word lexes like an operator": needs a lexer run.
