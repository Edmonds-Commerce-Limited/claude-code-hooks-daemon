# rfix3-msgfile-groups

Fixes MINOR 2 and MINOR 3 of the second delta review against the N496 fix in
`utils/message_files.py` (used by `sensitive_content` and `github_auto_close_keywords`).

## Fix

- `_leaves` / `_unwrap`: a `( )` / `{ }` group (and now `if`/`for`/`while`/`until`/`case`/`select`
  compounds, closed by `fi`/`done`/`esac`) stays whole only when what FOLLOWS its closer is the
  write or the recording (`{ ...; } > m.txt`, `{ ...; } | tee m.txt`, `{ ...; } | git commit -F -`).
  Otherwise its inner statements are judged one by one, recursively.
- `_group_tokens` replaces `_group_balance`: openers and closers of both group kinds and compound
  keywords (command-position only, so `echo if for` is not a compound); a `case` pattern `)` is blanked.

## Evidence

- Red: with the old `message_files.py`, the new `test_message_files.py` rows give 9 failed, 29 passed.
- Green: 434 passed across test_message_files, test_sensitive_content_message_file_same_command,
  test_github_auto_close_keywords, test_sensitive_content.
- Probe `/workspace/untracked/scratch/rv2-probe/msg.py`: no MISMATCH, no CRASH.
- `./scripts/qa/llm_qa.py changed`: exit 0, all checks clean.

## Checked, same shape

- stdin producers (`( cd /tmp/T && echo msg | git commit -F - )`) had the same wrong denial; fixed by the same path.
- No release-note callout describes this behaviour; none edited.
