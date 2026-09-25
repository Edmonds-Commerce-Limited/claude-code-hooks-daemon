# Callout: a configured secret word list path now reaches log and payload redaction

**Plan**: 00466
**Audience**: client projects

If you set `handlers.pre_tool_use.sensitive_content.options.secret_word_list_path`
to anything other than the default `.claude/block-words.secret`, the daemon's
own outputs ignored it. Payload capture, the PreToolUse debug log, the error
log, the server response log and the model-fallback advisory all redacted
against the default list, or against no list at all. Blocking was unaffected,
because the `sensitive_content` handler reads its own option. They now read
the configured list. If your list lives somewhere else, follow post-upgrade
task `02-audit-daemon-outputs-for-secret-terms-under-a-non-default-word-list.md`
to find and delete anything written before the upgrade. Every daemon reader of
a handler's `options` now goes through one accessor that accepts both shapes a
handler block can take, and a test fails if code reads the key any other way.
