# Callout: full QA is the coordinator's gate, and sub-agents run targeted QA

**Plan**: 00463
**Audience**: operators

A new opt-in handler, `subagent_full_qa_blocker`, denies a sub-agent's full-suite
QA run and names the targeted commands to run instead. The coordinator runs the
full gate on the delivered branch head, one run at a time, so the suite runs
once per delivery rather than once per agent per fix round. The main thread is
never affected. You declare which commands count as full (`full_qa_patterns`).
Commands are parsed, not substring-matched, so a commit message or `grep` that
mentions one is never denied. Only a path-like word targets a run, so a flag's
value is never mistaken for a path, and `option_grammar: pytest` supplies
pytest's own value-taking options. Nothing ships by default. `hooks-daemon check`
reports a handler enabled with no patterns, and a `scope` other than SUB, which
would deny the coordinator's own run.

The handler recognises a sub-agent by the `agent_id` field in its hook
payload. That is proven for Agent-tool sub-agents and in-process teammates. A
Workflow-tool agent's payload has not been measured, so the handler is not
claimed to cover one.

In this repository, `./scripts/qa/llm_qa.py changed` is the new targeted
command. It runs the fast static tools, the project handlers' own tests, docs
and plan QA, shellcheck, and pytest on the tests mapped from files changed since
the merge base. A changed file that maps to nothing fails the run and is named.
`llm_qa.py --read-only` now fails a result recorded for a different commit or
working tree, so an old green run never reads as a pass.
