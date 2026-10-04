# N339: bash_safe_mode reads compound-command syntax

Branch: worktree-n339-compound.

## Cause

`bash_safe_mode` counted `split_statements(command)`, which cuts at every `;` and newline. Inside `{ …; }`, `for … ; do …; done`, `if …; then …; fi` and `case` many of those cuts are the construct's grammar, so a fully gated command reached the two-statement threshold.

## Fix

New `sequenced_statements()` in `src/claude_code_hooks_daemon/utils/bash_flags.py`. It starts from `split_statements` and folds grammar breaks into the statement they belong to:

- a closer (`}`, `done`, `fi`, `esac`) is dropped when it matches the innermost open construct;
- a continuation (`do`, `then`, `else`, `elif`) is merged;
- the statement after a bare opener (`do`, `then`, `else`, `{` alone on a line) is merged;
- a case clause start (`a)`, `a|b)`, `*)`) inside an open `case` is merged.

Openers are recognised only in command position (word-level, quote-aware, via `iter_shell_words`), so `echo for; echo done` and `echo a; 'done'` still count two. A real `a; b` in a body stays two statements. Subshells need no handling: `( a && b )` has no `;`, and `( a; b )` still counts two.

Fail closed: a word hidden by `$( )`/backtick/unterminated quote, a closer with no matching open construct, a continuation with nothing open, or a construct left open all return the plain `split_statements` result, which is the old behaviour. `f() { a; b; }` and `for x in $(ls); do a; b; done` therefore still deny (the second is a known limit: gated loops over a `$( )` word list are still denied).

Only the threshold check in `BashSafeModeHandler._missing_flags` uses the new function. Flag detection and the mutator check still use the full statement list, and `split_statements` (shared by four other handlers) is unchanged.

## Tests

- `tests/unit/utils/test_bash_flags.py::TestSequencedStatements`: both reproductions, while/until/if/elif/else, newline layouts, case, subshell, nested loops (one statement); ungated body sequencing, trailing `; echo after`, case clause bodies (still counted); unbalanced and unparseable shapes (equal to the plain split); non-command-position and quoted keywords.
- `tests/unit/handlers/pre_tool_use/test_bash_safe_mode.py::TestCompoundCommandSyntaxIsNotSequencing`: allowed and still-denied shapes through `matches`/`handle`, plus the new acceptance fixture.
- Acceptance fixture added: "Bash safe mode - a gated compound command is exempt" (allowed in both modes).

## Verification

- Touched test files plus `tests/unit/utils`, the false-positive corpora and the dangerous-invocation checker tests: 6801 passed, 1 skipped.
- `./scripts/qa/llm_qa.py dangerous_invocation_corpus`: 0 violations (29 rows).

## Other changes

- `CLAUDE/UPGRADES/UNRELEASED/release-notes/006-bash-safe-mode-reads-compound-command-syntax.md` (callout).
- NIGGLES.md: N339 Status set to fixed on this branch (the table formatter realigned the column).

## Note

The live daemon still runs the old code, so a `{ …; }` group or a `for … ; do` loop in this session's own Bash calls was denied until restart.
