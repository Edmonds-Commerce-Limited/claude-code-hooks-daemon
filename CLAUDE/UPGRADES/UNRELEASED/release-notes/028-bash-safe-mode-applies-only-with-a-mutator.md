# Callout: `bash_safe_mode` applies only to chains that contain a mutator again (`only_with_mutator: true`)

**Plan**: 00483
**Audience**: operators

The shipped default of `bash_safe_mode` is `only_with_mutator: true` (owner ruling A3, reversing the earlier block-everything default). A `;`- or newline-sequenced Bash command with no `set` prelude is denied only when it contains a mutator such as `git add`, `git commit`, `git push` or `git tag`; a read-only chain like `grep x a; grep y b` or `cat f && ls` is allowed. The handler is still on and still blocks. To restore the strict scope, set `handlers.pre_tool_use.bash_safe_mode.options.only_with_mutator: false`.
