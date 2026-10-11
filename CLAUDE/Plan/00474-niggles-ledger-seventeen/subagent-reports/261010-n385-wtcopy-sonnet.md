# N385 worktree_file_copy part (sonnet)

Branch: agent-a6b15aeb31a90918a-939edbf5.

## Change

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/worktree_file_copy.py`: the copy is read from its operands
  (sources, destination, `-t DIR`, recursion). `_effective_command` now peels wrappers with the shared
  `peel_command_wrappers` (it kept its own list, which lacked `nice`) and drops a leading `(`/`{`. `matches()` walks
  `command_position_segments` in order, tracking the cwd from literal `cd`/`pushd`. A copy whose operands were read is
  judged on them; the older text patterns judge what could not be read (`dd of=`, a copy into another worktree).
- Tests: `tests/unit/handlers/test_worktree_file_copy_careless.py`. Written red first: 46 failed, 37 passed (the
  passes were the allow rows). After: all 191 worktree_file_copy tests pass.
- Gate: nine `worktree-copy-*` rows in `scripts/qa/dangerous-invocation-corpus.yaml`, each prefixed `cd /workspace`
  because the gate's hook `cwd` is the checkout it runs from, which is a worktree here (a bare `.` there is allowed).

## How the destination is decided

See the N385 entry in NIGGLES.md and the block comment in the handler. In short: explicit code-dir destinations are
denied whatever the cwd; a bare `.` is denied only in the main checkout for a whole-tree or code-path source; an
unresolvable `cd` leaves `.` undecided (allowed).

## Left open

- `xargs cp` fed from a file rather than the previous pipeline stage; `cd $VAR` then `.`; `cd` inside a subshell
  followed by a copy in that subshell; `find -exec sh -c 'cp "$1" ...'`.
