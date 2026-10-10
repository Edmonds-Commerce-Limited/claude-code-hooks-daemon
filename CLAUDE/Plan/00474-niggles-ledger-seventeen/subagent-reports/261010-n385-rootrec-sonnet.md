# N385 root_recursion_guard part

Branch agent-a8a71702237637e77-712d8f8b.

## Changes

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/root_recursion_guard.py`: segment is read past `time`, assignments and `peel_command_wrappers`; `bash -c` bodies recursed (3 levels) via `is_shell_command_option` and `SHELL_NAMES`; quote-aware split (`split_unquoted_spans`); clustered options read up to the first value letter; `du` and `ls -R` added; the current user's HOME value is the home tree.
- `src/claude_code_hooks_daemon/utils/command_position.py`: `_SHELLS` renamed to public `SHELL_NAMES` (no other users).
- Tests: `tests/unit/handlers/pre_tool_use/test_root_recursion_guard_careless.py`. Red first: 30 failed, 30 passed (allow rows). Then all 187 root_recursion tests green.
- Gate: seven `root-recursion-*` rows in `scripts/qa/dangerous-invocation-corpus.yaml`; checker passes.

## Decisions

- du and ls -R: scope extended deliberately. The harm is the whole-disk walk, not the tool being a searcher. `du` depth options limit printing only. `ls /`, `ls -la /`, `ls -r /` stay allowed.
- `rg x /home/user`: rg is already a walker; `/home` is an exact root and a directory below it is a project root by design. Only this user's HOME is now treated as the home tree. Left open: other users' home directories.
