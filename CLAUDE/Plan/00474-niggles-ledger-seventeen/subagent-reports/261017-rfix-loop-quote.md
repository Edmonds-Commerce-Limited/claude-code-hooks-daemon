# rfix-loop-quote: write_protected_paths for-loop unroll left a stray quote (reviewer D, D1)

## Assumptions

None needed.

## Reproduction (red)

Rows added before the fix, in `tests/unit/handlers/pre_tool_use/test_write_protected_paths.py` (loop-denied list) and
`tests/unit/utils/test_simple_commands.py` (`TestUnrollForLoops`). Run with `-k "Loop or loop"`:
`14 failed, 53 passed, 535 deselected`. The handler rows were the reviewer's `rm "$f.local"`, `rm "$d/ccy.env.local"`
and `rm "${d}/ccy.env.local"` shapes, each fail-open (ALLOW).

## Fix

`src/claude_code_hooks_daemon/utils/simple_commands.py`: `_unrolled` no longer uses a regex that ate an opening quote
but not the closing one. The new `_spelled` scans each body part tracking quote state and replaces only the
`$VAR` / `${VAR}` text:

- unquoted context: the loop word as the header spelled it (as before);
- inside double quotes: the word's value with `\ " $` and backtick escaped, glob characters (`* ? [`) stepping out of
  the quotes (`".claude/ccy/"*"/x"`) so a glob word still reads as a pattern;
- inside single quotes: left alone (literal text in the shell);
- a double-quoted word that is only the reference (`"$f"`) keeps the old behaviour of dropping its quotes, so the
  existing wildcard and glob rows are unchanged.

## Tests

Green after the fix: `602 passed` over the two test files. New unit rows cover `"$f.local"`, `"$d/x"`, `"${d}/x"`,
`"pre-$d-post"`, unquoted `$d/x`, quoted words with spaces, single-quote literal, glob word in double quotes, and a
`"` in a word. New handler rows cover the three reviewer shapes plus first/middle/last position in multi-word lists,
a redirect write, and a glob word. No existing test changed.

## Other consumers

`unroll_for_loops` has one consumer, `handlers/pre_tool_use/write_protected_paths.py:779`. `_unrolled` is private to
`simple_commands.py` and used only by `unroll_for_loops`. No other loop unrolling exists in `src/`.

## Release note

No existing callout in `CLAUDE/UPGRADES/UNRELEASED/` mentions for-loop unrolling; none edited, none added (defect
never shipped).
