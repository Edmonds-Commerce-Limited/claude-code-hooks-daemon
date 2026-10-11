# Batch B (N364, N341): sensitive_content scope

Both reproduced on main by calling `matches()` directly (17 of the new 38 test cases failed red), both fixed.

## Change

`src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py`

- `_metadata_commands` splits the line on `||`, `&&`, `|`, `;`, newline (quote-aware, heredoc bodies set aside)
  and scans only the commands that record metadata or publish a gh body. A heredoc body is kept only when its
  opener line belongs to a qualifying command. Message/body files are read per qualifying command.
- `_records_nothing`: `git config` is a write only when it assigns (two operands, `--add`, `--replace-all`);
  `--get*`, `--list`, `--show-origin`, `--unset*` and a lone key are reads. `git branch -d/-D/--delete` records
  nothing. Read-flag exemptions now apply only to `tag`/`branch`/`config`, using shell tokens, so
  `git commit -m 'add --list'` is no longer exempted by the flag word inside its message (a pre-existing
  fail-open found on the way).
- Unchanged: staged-content scan at commit, commit/tag/branch/author/`merge -m` surfaces, gh bodies and body files.

## Tests

`tests/unit/handlers/pre_tool_use/test_sensitive_content_metadata_scope.py`, fixture word list in `tmp_path`.
Allow rows: config reads, term in an unrelated `cd`, `grep <term> f`, `git log --grep`, `git show`, branch
delete. Deny rows: config assignment, term in the value of a compound command, flag word in a message,
heredoc message, gh body, body file, `-F` message file. Existing sensitive_content suites: 364 pass.

## Gate rows

No dangerous-invocation corpus or QA-rule rows exist for this handler; nothing to update.

## Residual

A `#` comment after a metadata write is still scanned (safe direction). A command nested in `$( )` or a
subshell is segmented only at its top-level separators.
