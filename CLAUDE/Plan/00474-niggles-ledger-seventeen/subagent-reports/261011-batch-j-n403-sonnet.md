# Batch J: N403, project_containment follows the chain's `cd`

Branch `agent-ad9ffaba8e0cf3c94-0ef7ac7a`.

## Change

- `utils/git_commit_parsing.py`: `SimpleCommand.redirects` keeps each command's file-writing redirections
  (`>`, `>>`, `>|`, `&>`, `>&` to a name), because `words` drops them.
- `utils/git_invocation_directory.py`: `placed_moves(moves, cwd)` reads a `cd` chain as the commit gates do
  (`expand_cwd_references`, `~` made absolute) and reports the first step that cannot be placed. `_steps` now shares
  its inner `_expanded`; behaviour unchanged.
- `handlers/pre_tool_use/project_containment.py`: when a command contains a `cd`/`pushd` and the hook cwd is absolute,
  the whole command is read with relative targets left unjoined, and each simple command is re-read from every
  `landing_directories` of its own chain. No new cd walker.

## Decisions to check

- `cd "$UNKNOWN" && cmd > x` is an ALLOW with an advisory ("relative to a cd the daemon cannot place"), not a deny:
  Plan 00483 A1 (owner ruling) says a guard denies only on a positive finding, and it is how `> "$OUT"` is treated.
  Denying would be a new deny on a shape that was allowed before. One line in the handler flips it if wanted.
- `cd sub; cmd > ../x` and `cd sub && a | tee ../y` still deny: the shared walk marks a `cd` followed by `;` or a
  pipe stage as possibly not taken, so the start directory is also read.

## Tests

Red before the fix: 17 failed, 13 passed in `TestARedirectIsJudgedWhereTheChainsCdLandsIt`. Green after.
Targeted run (containment, utils, pre_tool_use handlers matching contain/git/commit/conflict, ordinary-command gate
with three new `n403-*` rows): 4554 passed, 1 skipped. ruff, black (py311) and mypy on the touched sources clean.
`llm_qa.py changed` could not run (no venv under the worktree), so the checks were run by hand with the workspace venv.
