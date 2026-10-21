# N524 fact-check

Scope: the claims added by the N524 diff (NIGGLES.md entry, STATUS-INDEX row, PLAN.md open-list line). The checking
agent wrote its full table in the worktree `worktree-journal-per-entry`, because its write guard denied the main
checkout. The coordinator copied the verdicts here.

Result: 14 claims; 9 verified, 2 verified by code only (the live events are session facts), 1 partly verified,
2 unverifiable here, and 1 partly refuted.

## Partly refuted

- **N524b, "an Edit removing the four lines".** The working-tree change replaces the four lines with a two-line pointer
  paragraph, a net loss of two non-blank lines. The guard verdict is unchanged. Corrected in NIGGLES.md to
  "replacing".

## Key evidence

- **The guard.** `plan_journal_guard.py:352-356` returns a target only when non-blank lines or entry headings
  increase, and its docstring (lines 32-34) says deletions pass. So a shrinking Edit is allowed, and one that adds
  lines is denied as `JOURNAL_HAND_WRITTEN_ENTRY`.
- **The Bash route.** `_bash_target` (358-380) denies a redirect or copy into a day-file. Only `git` relocations are
  exempt.
- **The open direction is deliberate.** The docstring cites conflict-marker removal, so "deny a shrinking edit" changes
  a designed behaviour. Plan 00543's new layout must keep a route for resolving conflict markers in legacy day-files.
- **The duplicate check.** `duplicate_block.py` has no journal or path filter (lines 96-158). Other docs_qa checks
  already exempt journals (`pointer_resolves.py:136`), so there is precedent.
- **The duplicate itself.** 00529 journal lines 39-42 equal 00542 HEAD lines 44-47, as the QA json says.
- **The ledger counts.** STATUS-INDEX has 229 rows, 41 of them open.

## Unverifiable here

- That both entries were journalled from one body file.
- That the coordinator integrated Plan 00476 Task 2.2 and ran QA on that head.

Both are session facts.
