# Batch A report: N124 and N242

Plan 00474, branch agent-a147ced05d3582025-c3abf459. Both entries live in
[CARRIED-REFIX-BRANCHES.md](../CARRIED-REFIX-BRANCHES.md) (inside 00474), so they were
edited in place; no archived 00466 history was touched.

## N124: `find -regex` / `-iregex` operand read as a path

- Reproduced on main: 7 new cases in `TestTextOperandsAreNotJudgedAsGlobs`
  (`tests/unit/utils/test_quoted_text_not_enumerated.py`) failed with
  R-SECRET-BASH-MENTION on glob `.vault-pass*` (`find . -regex '.*decision:.*'` and variants).
- Fix: `recursive_search.find_regex_operand_indexes` (new, public, built on
  `FIND_EXEC_ACTIONS`) names the operand words; `secret_file_matching._find_regex_spans`
  turns a literal-quoted one into a text operand, so the existing placeholder mechanism
  blanks it. No parallel parser.
- Still judged (pinned by new deny tests): `find` with `-exec`/`-execdir`/`-ok`/`-okdir`,
  a region naming `xargs`, a protected root operand, `-name` beside it, an unquoted
  operand, a `$( )` operand, and a later `cat` of the file.
- `-name`/`-iname`/`-path`/`-wholename` were NOT relaxed: they are globs matched against the
  tree, and the existing contract test (`find . -name '<protected prefix>*'` is denied)
  requires them judged. The write-protected handler's `_FIND_PATH_FLAGS` is a different
  question (which files a write touches) and was left alone.
- Import note: `secret_file_matching` imports `recursive_search` lazily, because
  `recursive_search -> protected_file_index -> git_repo -> secret_file_matching` is a cycle at
  load time (same lazy pattern `protected_file_index` already uses toward this module).
- Unit tests for the new reader added to `tests/unit/utils/test_recursive_search.py`.

## N242: `python -m` dotted module name

Fixed already. On main, before any source change, the existing
`TestDottedModuleNamesAreNotPaths` passed and the two new handler-level cases
(`python3 -m pkg.<stem>_x`, and with `-I`) were ALLOWED by the full handler chain. Recorded as
dismissed-as-fixed (N136 merge 9b2e15be1). Added as regression pins: the two allow cases, and a
deny set showing `-m` exempts only the module name (later `cat` of the name, file operand after
the module, `python -m pytest <file>`).

## Verification

- `test_quoted_text_not_enumerated.py`, `test_secret_file_matching.py`,
  `test_secret_file_guard.py`: 1072 passed. `test_recursive_search.py`: 133 passed.
- Targeted QA line: see the coordinator reply.
