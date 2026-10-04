# Ledger 00474 N345: journal day-file merge conflict

Branch `worktree-n345-jconf`, based on main 8c7378da3.

## Delivered

- `mkplan.bash --resolve-conflict <day-file>` in the template
  `src/claude_code_hooks_daemon/install/templates/mkplan.bash`, with the deployed
  `CLAUDE/Plan/mkplan.bash` kept byte-identical (`cp`, as the repo does).
  Reads index stages `:2:`/`:3:`, falls back to conflict markers, writes the union
  (header once, each entry once, time order, ours first on ties, byte-identical
  entries merged), runs `git add`. Refuses with a message and writes nothing when:
  not a `NNNNN-Journal-YY-MM-DD.md` in `JOURNAL/`; file missing; no conflict; only
  one side present (modify/delete); a side is empty; a side has an unclosed fence,
  a `## ` heading that is no entry, no header; or the two headers differ.
- Guards: neither needed a change to allow the mode. `plan_qa_edit` judges only
  Edit/Write; `plan_journal_guard` finds no write destination in the command
  (pinned by tests and a new acceptance test).
- Decision, ADVISORY not deny, for `git checkout|restore --ours|--theirs` of a day-file.
  Why: the ledger text asks only whether it should be judged at all; the discarded
  entries stay in the other commit (recoverable), and keeping one side is sometimes
  right (duplicate or stale side). A deny would also have no bypass. Implemented in
  `plan_journal_guard` as an ALLOW with context (the chain does not end on a terminal
  ALLOW, so lower-priority git handlers still run), gated on the checkout's
  scaffolder offering `--resolve-conflict`. Covers `git -C`, `--`, `restore`,
  compound commands; named day-files only (not a directory pathspec such as `.`).
- Docs: `CLAUDE/PlanJournalling.md` (new section) plus its install template copy,
  which a drift test requires to be identical. Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/012-a-journal-merge-conflict-has-a-sanctioned-resolution.md`.
  NIGGLES.md N345 marked fixed.

## Tests

- `tests/unit/scripts/test_mkplan_resolve_conflict.py`: real git repos with real
  merge conflicts (past-day, same-stamp, byte-identical dedupe, fenced lookalike,
  add/add, marker fallback, seven refusals). Written red first.
- `tests/unit/handlers/pre_tool_use/test_plan_journal_guard.py`: advisory cases,
  non-cases, worktree script, stand-down, tokeniser helper.

## Notes

- Commit trailer uses `Claude Sonnet 5.5`, per the attribution reminder in this
  session, not the `Opus 5.5` line in the brief.
