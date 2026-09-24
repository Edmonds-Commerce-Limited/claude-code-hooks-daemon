# Task: audit daemon outputs for secret terms under a non-default word list

**Type**: audit
**Severity**: recommended
**Applies to**: all versions before this fix (Plan 00466 N14), in projects whose
`sensitive_content` `secret_word_list_path` is set to anything other than the
default `.claude/block-words.secret`
**Idempotent**: yes

## Why

The daemon redacts secret-list terms from its own outputs: payload-capture
files, its log files, and the PreToolUse debug log. The resolver behind that
read the handler's options as a plain dict, but the loaded config holds a
`HandlerConfig` model, so a configured `secret_word_list_path` was never read.
Redaction used the default list instead, or no list when the default file does
not exist. The `sensitive_content` handler read its own option correctly, so
writes were still blocked. But a term that reached the daemon in a hook payload
could be written verbatim to these files.

## How to detect if this applies to you

Look at `handlers.pre_tool_use.sensitive_content.options.secret_word_list_path`
in `.claude/hooks-daemon.yaml`. If it is unset, or equal to
`.claude/block-words.secret`, this task does not apply.

Otherwise, check the daemon's untracked directory for the files the redaction
guarded. That is `.claude/hooks-daemon/untracked/` in a normal install and
`untracked/` in a self-install checkout. A configured `payload_capture.dir`
moves the capture files elsewhere under it.

- `payload-capture/*.jsonl`, present only if payload capture was enabled
- `daemon*.log` and `errors.log`

## How to handle

Do NOT open the word list or print its terms. Search the files for each term
without echoing the matching lines, and list only the file names. Matching
is case-insensitive, as the daemon's own is (sample):

```bash
grep -rliFf <your-word-list> <daemon-untracked-dir>/payload-capture <daemon-untracked-dir>/*.log
```

The daemon also matches a hyphenated term in its underscored spelling and the
reverse, so search for those spellings too if your terms contain either.

Delete or truncate every file named. They are runtime artefacts and nothing
depends on their history. If any of them was copied elsewhere, for example
attached to a bug report or pasted into an issue, tell the user which ones so
they can retract them.

## How to confirm

Run the same `grep -rliFf` again and check that it names no file.

## Rollback / if this goes wrong

Nothing to roll back: the files are regenerated as the daemon runs, and the
upgraded daemon now redacts them against the configured list.
