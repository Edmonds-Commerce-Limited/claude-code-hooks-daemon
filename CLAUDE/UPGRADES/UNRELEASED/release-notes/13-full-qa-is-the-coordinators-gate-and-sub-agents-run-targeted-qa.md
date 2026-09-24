# Callout: full QA is the coordinator's gate, and sub-agents run targeted QA

**Plan**: 00463
**Audience**: operators

A new opt-in handler, `subagent_full_qa_blocker`, denies a sub-agent's full-suite
QA run and names the targeted commands to run instead. The coordinator runs the
full gate on the delivered branch head, one run at a time, so the suite runs
once per delivery rather than once per agent per fix round. The main thread is
never affected. You declare which commands count as full (`full_qa_patterns`).
Commands are parsed, not substring-matched, so a commit message or `grep` that
mentions one is never denied. Nothing ships by default, and enabling the
handler with no patterns is reported by `hooks-daemon check` instead of passing
silently.

In this repository, `./scripts/qa/llm_qa.py changed` is the new targeted
command. It runs the fast static tools, the project handlers' own tests, and
pytest on the tests mapped from files changed since the merge base. When
nothing maps to a test, it says that it ran no tests.
