# N291: secret guard reads a grep regex inside a command substitution as a glob

## Root cause

`_without_text_operands` in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`
(the N269 text-consumer exemption) split the command only on unquoted separators
(`&&`, `||`, `;`, `|`, `&`, newline) and read each segment's command word with
`segment_command_word`. A command substitution, a backtick pair and a process
substitution are not separators. For `x=$(grep '<regex>' f)` the segment's first word is
`x=$(grep`, which `_resolved_segment_words` resolves to `None` (a word a substitution
hides), so the head was not in `_TEXT_CONSUMER_HEADS` and no operand was masked. The
regex's `.*` runs then went through the glob heuristics. The bare `grep "<regex>" f`
resolved head `grep` and was masked.

Same defect for backticks, `<( )`, `>( )`, and a substitution inside double quotes.

## Fix

- `src/claude_code_hooks_daemon/utils/shell_segmentation.py`: new public
  `substitution_inner_spans(text)`, a quote-aware scanner returning the `(start, end)` of
  the command text of every substitution (nested included, delimiters excluded). Openers
  inside single quotes or after a backslash are literal; a process substitution inside
  double quotes is literal; a close paren inside a quoted word or a subshell group does
  not end a span. Raises `UnplaceableSubstitutionError` on an unterminated quote or
  substitution or nesting past 32; the caller catches it (debug-logged) and relaxes the
  top level only, so the guard fails closed.
- `secret_file_matching.py`: `_without_text_operands` now segments the top level AND each
  inner span with the same separator split and head test (new helper
  `_segment_text_operands`), dedupes the operand spans, and masks them. With `None` spans
  it behaves exactly as before (top level only). Only operands the inner consumer
  receives are masked; the literal protected-name check always still runs, so file
  operands, `-f`, `--pre`, `awk -f`, unquoted globs and quoted text for globbing programs
  (find -name, python -c, grep --include, rg -g) are judged unchanged.

## Revision after coordinator review of 2a3347f6a (bypass)

The first commit relaxed echo/printf operands inside a substitution. A substitution's
output becomes words of the outer command and an unquoted result is glob-expanded, so
`cat $(echo 'PREFIX*')` (and printf, backticks, `x=$(...); cat $x`, quoted substitution)
was allowed: a bypass. Reproduced red with the coordinator's shapes in all wrappers
(21 failures), then fixed:

- Inside a substitution only `grep`/`egrep`/`fgrep` operands are relaxed
  (`_SEARCH_HEADS`). Not echo/printf/gh (operand is the output), not `rg` (`-r` prints
  its replacement text), not `awk` (a program prints its string literals).
- An operand is "inside a substitution" when its start lies in any inner span, whichever
  pass found it. This also closes a hole already on main: `x=$(true; echo 'P*'); cat $x`
  was allowed because the outer pass split at the `;` inside the substitution.
- Top-level N269 behaviour is unchanged.
- Tests: new `TestAnEchoingConsumerIsNotRelaxedInsideASubstitution` (echo, printf,
  echo -n, rg -r, awk print literal x 7 outer shapes: bare, double-quoted, backticks,
  assigned, assigned after `;`, `<( )`, nested; all DENIED) plus the top-level
  forms still ALLOWED. The rg/awk pattern cases moved out of the in-substitution
  ALLOWED list (conservative false positive, grep is the N291 case).
- The coordinator's n291_bypass.py now reports deny for all five bypass shapes and
  allow for the grep regex. Targeted run: 3449 passed.

## Tests (tests/unit/utils/test_substitution_text_operands.py, originally 240 cases)

ALLOWED, each of 6 text-consumer shapes (double/single-quoted grep regex, grep -E
alternation, rg pattern, awk pattern, echo of a glob) x 8 wrappers (assignment, bare
substitution, double-quoted substitution, backticks, process substitution, nested
substitution, after `;` inside, piped inside), plus the exact N291 reproduction.

DENIED, each of 18 readers at top level and in all 8 wrappers: cat of the file (bare and
quoted), grep over the file, grep with quoted pattern over the file, `grep -f`,
`grep --file=`, `rg --pre`, `rg --ignore-file`, `awk -f`, awk over the file, unquoted
glob, grep over an unquoted glob, grep over a quoted prefix with glob tail, `find -name`
glob, `grep --include` glob, `rg -g` glob, python glob, `bash -c` glob.

DENIED, no leak out of the substitution: an operand after the closing delimiter (assignment
prefix, `find $(..) -name`, `&& cat`), a substitution spelled inside single quotes, and
unterminated `$(`, backtick and `<(` forms (fail closed).

Scanner unit tests: spans for each opener, nesting, quoted close paren, single/double
quote handling, escaped opener, subshell group, unterminated and over-deep input.

Red confirmed: with the inner spans disabled, 25 ALLOWED cases fail and all DENIED cases
pass; with the fix everything passes.

## QA

- Targeted: tests/unit/utils + tests/unit/handlers/pre_tool_use filtered to secret,
  shell_seg, substitution, quoted_text, heredoc: 3433 passed.
- ruff, black (py311), mypy clean on the three touched files. pyright's only message is
  `Import "pytest" could not be resolved` for the new test file, an environment issue
  (the worktree has no lsp-venv), not a code finding.
- `./scripts/qa/llm_qa.py changed`: 34/37 passed before the error-hiding fix; after it
  error_hiding, magic_values, lint, format, type_check, pyright pass. The remaining
  failures are not from this change: `docs_qa` (3 advisory duplicate-block findings in
  Plan 00479/00480 documents) and `changed_tests` (4141 tests passed, 0 failed, but
  `shell_segmentation.py` is `unmapped [too-broad]`: more than 40 test files import it, so
  any change to it is left to the coordinator's full gate by design; no map rule added).

## Notes

The guard also reads source written by Write/Edit, so a source or test file spelling an
unbalanced substitution opener whole is denied as unreadable (R-SECRET-COMMAND-UNREADABLE);
the new code and tests assemble those openers from parts.

Not covered: `FOO=bar grep '<regex>' f` (an assignment prefix on a top-level grep, no
substitution) was not part of this defect and its handling is unchanged.

Release note: CLAUDE/UPGRADES/UNRELEASED/release-notes/212-a-grep-pattern-inside-a-command-substitution-is-no-longer-read-as-a-glob.md
