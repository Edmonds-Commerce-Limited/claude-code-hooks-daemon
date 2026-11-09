# Report: Plan 00588 / GitHub #169 implementer (Sonnet)

## RED

New class `TestStdinGrepAndGitGrepAreNotLookups` in `tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py`.
Before the fix: `11 failed` in `test_not_a_lookup` (every stdin and git grep shape: `| grep -v`, `2>&1 | grep -n`,
`| rg`, `<<<`, `< file`, `git grep` with/without ref, code and `'CLAUDE/*.md'` pathspec, `git -C dir grep`, each
`AssertionError: assert True is False`). Three more failures were my own wrong guards (below), removed.

Guards that already passed and stay passing: `grep -rn some_identifier src/`, `rg some_identifier`, `grep -rn some_identifier`, `grep some_identifier` (no target, first command), `cmd | grep -rn some_identifier src/`,
`grep -rn some_identifier src/ | grep -v x`, `cmd | xargs grep some_identifier`, and the Grep tool.

## Corrections to the brief

- `grep -n some_identifier src/x.py` is NOT a lookup today: the existing single-file exemption already lets it
  through. Unchanged; not asserted as a lookup.
- A command mixing a skipped grep with a real one (`cmd | grep -v x; grep -rn some_identifier src/`) is still
  judged by the FIRST grep's pattern (existing `_extract_bash_grep_pattern`), so it can pass unenforced. That is
  pre-existing and outside the identifier-heuristics boundary; not changed, not asserted.

## Decision: git grep without a ref

I disagree with the coordinator's view and never judge `git grep`. Reasons: the plan's Goals say `git grep` is not
judged; telling "has a ref" from "pathspec" in `git grep` arguments needs git revision parsing (a bare word after the
pattern may be either), which is a second parser; and `git grep` searches tracked content through git, not the
language-server workspace. Cost: `git grep some_name -- src/` is no longer steered to LSP.

## GREEN

`handlers/pre_tool_use/lsp_enforcement.py`: `_has_lookup_grep` and `_reads_only_stdin`, built on
`git_commit_parsing.simple_commands` (no new parser, shared module untouched). `matches()` returns False when every
grep in a Bash command is a `git grep` or a grep/rg that names no file and is fed by a pipe (`|`, `|&`) or an input
redirect/here-string. `grep -r` with no target in a pipe stays judged (it searches cwd). A command with no
recognised grep (`xargs grep`) or any real grep stays a lookup. The `get_claude_md` guidance gained a sentence.

## Delivery

Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/021-lsp-enforcement-stdin-greps-and-git-grep.md`.
Both handler test modules: 137 passed. QA verdict and sha are in the reply.
