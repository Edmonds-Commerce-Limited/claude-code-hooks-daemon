# Callout: the deployed core docs name the project's QA gate for the change, not its full suite

**Plan**: 00475
**Audience**: client projects

The deployed `CLAUDE/core/PlanWorkflow.core.md` told every agent that "this project's full QA suite must pass" before any task closed, and its task checklists and Success Criteria carried the same wording; `Worktree.core.md` said the worktree "must pass all QA". Both now say the QA gate this project names for the change, and the QA Integration section says a project may run a targeted gate for everyday work and keep its full suite for a release or another step it names. Nothing about your project's own QA changes, and an agent now follows your QA documentation's tiers instead of running a whole-suite gate on every task. The documents are refreshed on upgrade; if your QA documentation does not yet say which gate applies when, add that and agents will follow it.
