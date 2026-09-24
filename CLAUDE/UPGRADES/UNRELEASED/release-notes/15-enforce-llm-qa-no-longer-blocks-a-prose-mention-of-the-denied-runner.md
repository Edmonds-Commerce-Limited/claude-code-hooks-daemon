# Callout: `enforce_llm_qa` no longer blocks a prose mention of the denied runner

**Plan**: 00466
**Audience**: handler authors

The project-local `enforce_llm_qa` handler (`.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`,
part of this repo's own self-install/dogfood setup, not something the
installer ships to client projects) denied any Bash command whose text
contained `run_all.sh` anywhere, including inside a quoted argument to an
unrelated command — for example a `mkplan.bash --title "... run_all.sh ..."`
journal entry. (A `gh issue comment --body "... run_all.sh ..."` prose
mention was already allowed before this fix — `gh` was already exempt as a
data-consuming command.) It now recognises a real invocation — the script
named as any shell word in the command, at any position, unless the
command's head is a recognised data consumer (`cat`/`grep`/`head`/etc.,
`git`/`gh`) that could not execute it — and leaves a bare prose mention
alone. A quoted multi-word argument tokenises as ONE word, so it is never
mistaken for the script's own path.
