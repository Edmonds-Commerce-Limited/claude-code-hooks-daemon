# Fix: git grep negations read as value-taking (older-holes loosening review, Finding 1)

## Finding

The `_GIT` table in `src/claude_code_hooks_daemon/utils/grep_option_grammar.py` listed
`--no-after-context`, `--no-before-context`, `--no-context`, `--no-max-count` and
`--no-threads` as value options. In git (2.47 `git grep -h`: `--[no-]context <n>`) the negated
form takes no argument. The parser ate the pattern as the value, read the real root as the
pattern, and fell back to the cwd, so `git grep --no-context x ../deep` from a subdirectory never
judged `../deep`. The same parser feeds `flaggable_content_channel_guard`.

## Change

- Red tests first (separate commit): `TestGitNegations` in
  `tests/unit/utils/test_grep_option_grammar.py` (each of the five names plus `--no-cont`:
  consumes no word, is a flag; positive forms still take a value) and
  `test_git_grep_negation_does_not_hide_a_parent_root` in
  `tests/unit/utils/test_recursive_search.py` (synthetic repo, `../tracked` root from a
  subdirectory).
- Fix: the five names moved from `value_long` to `flag_long`.

## Sibling audit

Every other `--no-*` entry in `_GIT` was compared with `git grep -h`. All are in `flag_long`
except `--no-color` and `--no-open-files-in-pager`, which are `optional_long`. Optional never
consumes the next word, so they cannot hide a root; git rejects an attached value on them, so
no command runs either way. They are pinned by a test and left as they are. No other table
carries `--no-*` value entries.

## Differential

A copy of the reviewer's harness was run over the same corpora (`corpus`, `corpus_absent`,
`corpus_sub`, `corpus_git`, `corpus_git2`) against main and the branch. All seven negation
cases from the review now deny. The remaining main-deny to branch-allow rows are the ones the
review already judged correct narrowing; nothing new appeared.

## check_tables.py

That file is the reviewer's scratch script, not tracked in the repository. It uses `Arity`,
`_Table`, `_GNU` and `_RG`, all of which the branch defines. The pyright diagnostic comes from
resolving the import against a tree without the module (main), so there is nothing to fix in
the source.

## QA

Targeted pytest (grammar, recursive search, git grep roles, compound grep, every
secret_file_guard test file, flaggable_content_channel_guard): 1917 passed. ruff, black --check
and mypy are clean on the touched files.
