# Callout: the deny text no longer claims batched tool calls were cancelled

**Plan**: 00511
**Audience**: everyone

Every PreToolUse denial used to end with "Any tool calls batched with this one were CANCELLED", and the `lint_on_edit` and `validate_eslint_on_write` guidance said the same about sibling calls. That has been false since Claude Code 2.1.161, which answers each parallel tool call on its own: a denied Write sat beside a Bash call that ran. An agent that believed the text re-issued work that had already happened, such as a commit. The suffix now says batched calls "may ALREADY HAVE RUN" and to check their results before re-issuing anything, and it still ends with "adapt and continue". The two linter handlers' guidance and the handler-development guide say the same (reported as issue #81). No handler's decision changed.
