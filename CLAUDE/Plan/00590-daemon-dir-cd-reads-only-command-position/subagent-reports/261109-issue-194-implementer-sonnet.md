# Plan 00590 Task 1.1 implementer report (GitHub #194)

## RED

Four new allow tests failed before the change (`assert True is False`): the two WRONG rows from the brief,
`grep -c 'cd ' .claude/hooks-daemon/x && echo ok` and `rg "pushd " .claude/hooks-daemon/ | wc -l`.
The 14 executing-twin deny tests already passed (they pin the behaviour to keep).

## GREEN

- `utils/command_position.py`: new `SEARCH_HEADS` (grep, egrep, fgrep, rg) and an opt-in
  `data_heads` parameter on `command_position_view` (threaded through `_narrow`/`_narrow_shell_body`).
  Default stays `DATA_HEADS`, so every other caller is unchanged.
- `daemon_location_guard.matches()`: `_path_text(command_position_view(command, data_heads=SEARCH_HEADS))`
  replaces `strip_inert_spans`. The view calls `strip_inert_spans` itself.

## Disagreement with the brief

The first attempt used the default view (all DATA_HEADS). It broke 61 existing tests
(`TestAnInertHeadNamingADirectoryChangeIsNotOne`: wrapped/rebound `echo`/`printf`, `echo '..' | bash`
shapes), because this guard deliberately keeps judging those (see the `is_plain_data_command` comment).
So blanking is restricted to the search heads via the opt-in. `echo`/`printf` behave as before.

## Safety notes

Blanking applies only when the segment has no expansion marker and its output is not piped to a
non-inert stage. `bash -c` bodies are narrowed recursively (same rule); `eval`, `$( )`, backticks,
`( )`, executing heredocs and `echo "cd ..." | sh` are untouched and still deny (one test each).
Residual: a rebound `grep` (alias/function) is out of scope under the threat model in ARCHITECTURE.md.

## Other

Release note 024 added. Targeted QA: see the final reply.
