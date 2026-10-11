# Plan 00474 batch T: N403 residuals in `_walk` (case/esac, pipeline stages, function definitions)

Code: `src/claude_code_hooks_daemon/utils/git_commit_parsing.py` (`_walk` and new helpers).

## Changes

1. `case`/`esac` are a group (opener/closer sets), so `case x in x) cd /tmp;; esac > x` reads the redirect where the case
   opened. The lexer yields a pattern's `)` as an operator that popped the subshell stack; `_walk` now tracks
   `expecting_pattern` (set by a `case` head and by `;;`/`;&`, cleared by the pattern `)` or `esac`) and treats that `)`
   (and an optional leading `(`) as no boundary. Without it `(cd sub && case x in a) true;; esac; echo x > y)` lost the
   subshell's `cd` early, which would have turned a deny into an allow. This was cheap, so it is handled.
2. Pipeline: before the change `|` only marked the chain uncertain, so the directory carried across stages (read both
   ways). `_walk` now keeps `stage_start`, the state where the current pipeline stage began (updated at every non-pipe
   operator, at a subshell `)` and at a group closer), and restores it at `|`/`|&`. A stage's `cd` no longer reaches the
   next stage or the code after the pipeline. `cd /tmp && x | y > z` still runs `y` in `/tmp`.
3. Function definition: `name ()` / `function name ()` is detected from the `()` operator; `function name {` from the
   segment shape. The `{` frame carries the name; at the closing `}` the directory returns to the state where the body
   opened, unless the name appears as a word later in the command. `f() { cd /tmp; }; f; echo x > x` therefore still
   denies. For the `function name {` form the body's first segment is now also read for a `cd` (`_body_of_function_keyword`),
   so a called function-keyword function keeps its move.

Not changed: never-run loop bodies (`while false; do cd /tmp; done`), as instructed. The last-stage `a | cd /tmp` case
is unchanged.

## Callers

`_walk` is reached through `simple_commands` (git gates, `project_containment`, `write_protected_paths`, `host_command_guard`,
`command_journal`) and `git_invocations`/`invocation_directory`. Their tests were run (below).

## Tests

- `tests/unit/utils/test_git_commit_parsing.py`: case redirect, case pattern paren in a subshell, case cd carries on,
  pipeline stage reset (three shapes), stage start kept, pipeline end, function definition (four spellings), called
  function keeps its cd.
- `tests/unit/handlers/pre_tool_use/test_project_containment.py`: `test_a_move_the_shell_never_makes_is_not_carried`
  (allow) and `test_a_move_the_shell_does_make_still_denies` (deny: case then `;`/`&&`, subshell case, `cd /tmp && { } |`,
  called function). Red on the base tree, green now (probe confirmed on base source).
- `tests/fixtures/ordinary_command_corpus.yaml`: four `n403-*` rows (case, group pipeline, subshell pipeline, function).

Results: 7570 passed, 1 skipped (`tests/unit/utils`, command_journal, ordinary-command gate); 4793 passed (selected
pre_tool_use handler, out-of-root containment and write-blindness integration tests); final re-run of the touched tests
plus the gate 964 passed. black (py311), ruff, mypy and pyright on the touched source: clean. No suppressions.

## Ledger

N403 residual list in `NIGGLES.md`: the case, pipeline and function lines are marked "cleared by batch T"; the loop-body
residual remains as a separate open line.
