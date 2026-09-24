# Callout: `enforce_llm_qa` no longer blocks a prose mention of the denied runner

**Plan**: 00466
**Audience**: handler authors

The project-local `enforce_llm_qa` handler (`.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`,
part of this repo's own self-install/dogfood setup, not something the
installer ships to client projects) denied any Bash command whose text
contained `run_all.sh` anywhere, including inside a quoted argument to an
unrelated command — for example a `mkplan.bash --title "... run_all.sh ..."`
journal entry, or a `gh issue comment --body "... run_all.sh ..."`. It now
recognises a real invocation (the script at a command's own head, or handed
to `bash`/`sh`/`env`/`timeout`/`nice`/`exec`, including `-c` subshells and
`$(...)`/backtick substitutions) and leaves a bare prose mention alone.
