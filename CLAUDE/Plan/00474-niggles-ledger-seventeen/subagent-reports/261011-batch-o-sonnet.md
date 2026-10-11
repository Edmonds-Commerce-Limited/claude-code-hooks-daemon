# Batch O: N380 and N410

## N380 (triage group J)

Triage row: items 2-3 unchecked in QA.md. Checked: QA.md had the sub-agent/coordinator split table, but not the
lock exception for agents (item 2) nor that a bare `changed` refuses on main so the coordinator needs
`--range <pre-merge head>..HEAD` (item 3). Added a short two-bullet block after the split table in
`CLAUDE/QA.md`. No owner decision needed. Status flipped to Fixed. N397 (other half of group J) not touched.

## N410

Fix in `src/claude_code_hooks_daemon/handlers/pre_tool_use/upgrade_approval_guard.py`:
`_variable_program_is_upgrade(program, arguments, ...)` plus `_program_is_literal_tool`. A variable-led program word
whose last path component is a literal name that is not a shell, wrapper or python, with no `$`/backtick in its
arguments, no longer reads "cannot tell" as the upgrade under a steering variable. Upgrade-shaped arguments
(`--project-root`, `.claude/hooks-daemon`) still deny; a readable script operand is still judged by content.

Judgement call (unknown variable program that could be the upgrade): a bare `$V`, `$V/python`, `$V/bash`,
`$V/env`, or any expanded operand keeps the old deny (unresolvable). `$V/<literal-name>` with no finding against it
is allowed, relying on owner ruling B5: "A guard denies only on a positive finding" (OWNER-RULINGS-261006.md).
Residual: a renamed copy of the upgrade script reached as `$V/<name>` with an unreadable or absent operand and no
upgrade-shaped argument is now allowed (the entry-point names are caught earlier by name).

Tests: `TestVariableToolUnderSteering` (renamed from `...IsPinned`) flipped to allow, plus operand-less, still-denied
and readable-script cases; corpus rows `n410-*` appended at the end of `tests/fixtures/ordinary_command_corpus.yaml`.

Red: 6 failed (3 flipped pins, 3 operand-less), 14 passed. A first draft was over-broad and also failed 3
still-denied cases, fixed. Green: 1661 passed in `tests/unit/handlers/pre_tool_use`, the ordinary-command gate tests.

QA: `llm_qa.py` could not run (no venv for the worktree). ruff, black py311, mypy on the touched source: clean.
