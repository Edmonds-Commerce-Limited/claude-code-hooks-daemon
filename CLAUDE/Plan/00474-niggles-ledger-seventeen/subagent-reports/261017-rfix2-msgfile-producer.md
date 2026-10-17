# rfix2-msgfile-producer: producer text of a commit message file is now judged

## Assumptions

- A producer whose text is not on the command line (`cat other.txt | git commit -F -`) is unknowable at PreToolUse time. It is left to the file reader, as an unreadable file already is. Only text that sits in the command is judged.
- An unbalanced `{` / `(` group is treated as running to the end of the command (more text kept, fail closed).

## Red (before the fix)

`pytest` on the two handler test files after adding the new cases: `13 failed, 130 passed`. The failures were the producer rows:
`echo T | tee m.txt && git commit -F m.txt`, `{ echo T; } > m.txt && ...`, `( echo T ) > m.txt && ...`, `echo T | git commit -F -`, `--file=-`, `--body-file -` (sensitive_content, plus the matching github_auto_close_keywords rows).

## Fix

`src/claude_code_hooks_daemon/utils/message_files.py`, `message_file_writers`:

- The command is split into top-level statements on `&&`, `||`, `;`, newline. A pipeline and a `{ }` / `( )` group stay whole (`_statements`, group depth counted on quote-masked text).
- A statement that writes a named message file is returned whole, so its producer travels with the writer.
- For a recording command that reads stdin (`-F -`, `--file=-`, `--body-file -`) and sits after a pipe, the earlier pipeline stages are returned (`_stdin_producers`).
- Heredoc bodies are still attached to a returned statement.

`github_auto_close_keywords.py` and `sensitive_content.py` both call this one function, so both are fixed with no change to either handler.

## Tests

- `tests/unit/handlers/pre_tool_use/test_sensitive_content_message_file_same_command.py`: `TestProducerOfTheMessageText` (10 deny rows, 7 allow rows).
- `tests/unit/handlers/pre_tool_use/test_github_auto_close_keywords.py`: `TestProducerOfTheMessageText` (5 deny, 3 allow).
- `tests/unit/utils/test_message_files.py`: `TestMessageFileWriters` (direct returns, unclosed group).
  No existing test changed.

## Sibling code checked

`message_file_writers` has exactly two callers (the two handlers above). `read_message_files` is unchanged; it reads files on disk.

## Callouts

No UNRELEASED/ callout or release-notes file mentions this behaviour (searched CLAUDE/UPGRADES for `message_file_writers`, "segment that writes", "message file"); nothing for the coordinator to edit.
