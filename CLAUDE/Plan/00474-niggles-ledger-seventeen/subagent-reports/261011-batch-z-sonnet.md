# Batch Z: N403 residuals in `_walk`

Source: `src/claude_code_hooks_daemon/utils/git_commit_parsing.py`.

## Changes

1. A later COMMAND word that is a `$` expansion (`$g`, `${g}`, `$@`, `$1`; the lexer has already stripped quotes) counts
   as a possible call of every defined function: the body's `cd` applies with `uncertain=True`
   (`_calls_through_expansion`). Arguments (`echo "$@"`) and assignments (`g=$h`) are not calls.
2. Pipeline last stage: `_walk` keeps a `pipelines` stack of `(depth, start state)` marks, depth being
   `len(stack) + len(groups)` taken at the first non-paren character of the operator word (so `|(` records the depth
   before the `(`). The start state is restored only when a non-pipe operator arrives at the same depth
   (`_pipeline_ended_by_operator`) or a closer returns the nesting to it (`_pipeline_ended_by_closer`, used for `)` and
   for group closers). A case pattern's `|` records no mark (found by the probes: `case a in a|b) cd /tmp; …` had
   become an allow).
3. Ledger: N403 residual lines updated; never-run loop bodies recorded as a deliberate limit.

## Probe diff (main vs branch, all six probes)

Branch is stricter or identical on every row except these intended last-stage rows, which now place the write at the
pipeline's start directory:
`x | cd /tmp && echo > y`, `x | cd /tmp; echo > y`, `x |& cd /tmp; …`, `cd /tmp && x | cd /workspace && echo > y`,
`cd /tmp && echo | cd /workspace; echo > y`, `cd /tmp; true | cd /workspace; echo > y`,
`true | { cd /tmp; } ; echo > y` (group closed, then a later write), `cd /tmp; true | while read l; do cd /workspace; done; echo > y`,
`cd /tmp; true | { cd /workspace; }; echo > y`, `git log | cd sub && git commit -m x`, `echo hi | cd sub && git commit -m x`.
The `/tmp` part of the earlier cd is kept in each; only the last stage's own cd is dropped.
Newly denied: `f() { cd /tmp; }; "$@"; echo > x` and `…; g=f; $g; echo > x`. The required deny rows
(`ls | { cd /tmp; cat > y; }` etc., `true |(cd /tmp; echo x > y)`) are deny on both.

## Round 2 (bypass fix)

`_pipeline_ended_by_closer` popped marks recorded inside the subshell being closed and returned the inner pipeline's
start, replacing the subshell's own restore (`(cd src && ls | cat)&& echo x > ../y` allowed). It now drops marks deeper
than the depth the closer returns to and restores only from a mark at exactly that depth. New tests cover every shape
reported, with and without a space before `&&`, the two git-directory cases, a containment deny list and a corpus row.
Probes (batch T set plus `probe_z`, `probe_z2`, `probe_z3`): the only rows allowing on the branch where main denies are
last-stage rows (`x | cd …`, `x | y | cd …`, `true | while …; done; echo`, `true | if …; fi && echo`). Unit utils plus
`pre_tool_use`, the corpus gate, containment and write-blindness integration: 18686 passed, 1 skipped. black, ruff,
mypy, pyright clean.

## Tests

- Utils plus all of `tests/unit/handlers/pre_tool_use`: 18075 passed, 3 failed first run. The three were pinned
  behaviour for `x | cd … && …` and are updated: two in `test_git_facts_command_directory.py`, one in
  `test_project_containment.py`. Re-run after the edits: `tests/unit/utils`, `test_project_containment.py`, the corpus
  gate, `test_out_of_root_write_containment.py` and `test_bash_write_blindness_coverage.py` are green. The extra
  `tests/unit/qa` directory I included had 25 failures, all in `tests/unit/qa` (llm_qa venv resolution and main-moved
  tests, environment related; none touches the parser).
- New tests in `test_git_commit_parsing.py` (compound last stage, bare last stage, case pattern bar, expansion calls),
  `test_project_containment.py`, `test_git_facts_command_directory.py`; two corpus rows `n403-last-stage-cd-*`.
- black, ruff, mypy and pyright clean on the changed source.
