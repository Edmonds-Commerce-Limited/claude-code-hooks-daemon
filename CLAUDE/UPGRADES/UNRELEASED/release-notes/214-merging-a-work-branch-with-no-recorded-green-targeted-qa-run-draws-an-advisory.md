# Callout: merging a work branch with no recorded green targeted QA run draws an advisory

**Plan**: 00475
**Audience**: operators

A new advisory handler, `merge_qa_advisor`, speaks when a Bash `git merge` names a work branch (`worktree-*`, local or `origin/worktree-*`) whose head has no recorded green `llm_qa.py changed` run. It names the head and the static checks `CLAUDE/QA.md` lists for the coordinator's check (ruff, black, mypy, pyright, the error-hiding and input-contract audits, shellcheck, the touched tests). To make that checkable from the checkout that merges, a passing `llm_qa.py changed` run of the whole selection on a clean tree now records the commit it judged in `refs/integration/changed-green/<branch>`, which every worktree shares; a failing run of the whole selection drops the record. The handler never blocks, and it is silent when the record names the head, for any other branch, for `--abort`, `--continue` and `--quit`, and whenever git cannot answer.
