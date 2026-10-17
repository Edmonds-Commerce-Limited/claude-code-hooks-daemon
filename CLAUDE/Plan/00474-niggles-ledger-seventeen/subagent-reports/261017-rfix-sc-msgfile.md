# rfix-sc-msgfile: message/body file written earlier in the same Bash command

Assumptions: none needed.

## Defect (code-review-a D1)

`sensitive_content._metadata_commands` kept only the recording segment, and the file a
`-F`/`--file`/`--body-file` names does not exist at PreToolUse time when an earlier segment
writes it, so `read_message_files` skipped it. Four inputs were allowed that v3.69.0 denied.

## Red

New `tests/unit/handlers/pre_tool_use/test_sensitive_content_message_file_same_command.py`
before the fix: `6 failed, 4 passed` (the six deny rows: the reviewer's four plus `--file=m.txt`
and `./sub/m.txt`; the four allow rows, including the N364 `cd /tmp/<term> && git switch -c clean`,
passed). Sibling probe before the fix: `cat > m.txt <<'EOF' / Fixes #12 / EOF / git commit -F m.txt`
and `echo 'Fixes #12' > m.txt && git commit -F m.txt` both returned `matches() == False` in
`github_auto_close_keywords`.

## Fix

- `utils/message_files.py`: new `message_file_writers(command, recordings, cwd)` returns each
  segment that writes a path a recording command names (matched through
  `scan_bash_write_targets`, the shared write-target accessor), plus the heredoc bodies those
  segments open. Also exports `COMMAND_SEPARATORS` (moved from sensitive_content, single source).
- `sensitive_content._metadata_commands` takes the hook cwd and appends those writers; the
  N364 narrowing is untouched, an unrelated segment is never kept.
- Sibling with the same shape, confirmed and fixed: `github_auto_close_keywords._compute_match`
  now also searches the writer segments (same helper). Tests added to
  `test_github_auto_close_keywords.py`.

## Existing tests / release notes

No existing test changed. No release note callout described this behaviour, so none edited
(the defect never shipped).

## Checked

`read_message_files` callers: sensitive_content and github_auto_close_keywords only.
