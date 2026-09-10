# Callout: a fully completed plan is closed, and both human gates are keys now

**Plan**: 00367
**Audience**: everyone

The deployed `PlanWorkflow.core.md` told every agent to "ask user for
approval before marking plan complete". Nothing in the daemon enforced that,
and everything it did enforce (the holding-area criterion, the
terminal-placement hint, archive atomicity, the supervisor's "work until
complete" goal) drove an agent straight through to Complete. An agent either
stalled finished work on a human who never asked for the gate, or learned to
ignore the document.

The document now says what the daemon does: a fully completed plan is closed
by the agent that completed it, in the same commit that archives it. A
project that does want a human in the loop turns on
`plan_workflow.close_requires_human_approval` (default `false`). With it on,
the new `plan_close_approval` handler denies an agent's Write/Edit that flips
a `PLAN.md` `**Status**:` to Complete, Cancelled or Superseded, and names the
human's route: edit the header themselves, or run
`hooks-daemon approve-plan-close NNNNN`, which records a one-shot marker under
the daemon's untracked directory that the very next terminal flip of that
plan consumes. Only the flip is gated; a plan a human already closed stays
editable.

This was handled Defence Before Fix. The net is the docs-QA check
`unenforced-approval-gate`: a daemon-owned core document may prescribe a
human approval gate only when the same paragraph names, in backticks, the
config key that enforces it. It blocks a NEW unenforced gate at edit and
commit time and reports pre-existing ones in the sweep.

The eleven instances in `Worktree.core.md` (the parent-to-main merge
approval) got the same treatment. A project that wants a human in that loop
turns on `worktree.merge_to_main_requires_human_approval` (default `false`).
With it on, the new `merge_to_main_approval` handler denies a `git merge`
(or `gh pr merge`) run in the MAIN checkout while it is on the default
branch, and names the human's route: run
`hooks-daemon approve-merge <branch>`, which records a one-shot marker under
the daemon's untracked directory that the very next merge of that branch
consumes. A merge run inside a linked worktree (child into parent) is never
gated either way. With the key off (the default), the parent-to-main merge
happens once verification passes, unchanged from before. `Worktree.core.md`
now describes the toggle instead of prescribing an unenforced "ask a human"
step, so `docs-qa --sweep` reports zero `unenforced-approval-gate` findings
across both core documents.
