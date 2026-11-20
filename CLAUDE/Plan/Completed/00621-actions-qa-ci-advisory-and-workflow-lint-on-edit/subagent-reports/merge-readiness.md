# Plan 00621 merge readiness

- Branch `agent-aac077842fc4cd262-5b95f273`; merged main (v3.76.0). One conflict: the
  generated `.claude/HOOKS-DAEMON.md` header date/version line, resolved to main's line.
- The handoff's Tasks 2.2 and 2.3 were already done by later commits; PLAN.md success
  criteria are all ticked.
- Owner decision open (DESIGN.md section 4.1, not decided here): whether `staged_lint_gate`
  also runs `actions-qa` on staged workflows at `git commit` (current build: yes, in
  `mode: warn` an advisory, in `mode: block` a deny on exit 1; other exits only logged).
  Alternative: exclude the workflow strategy from the commit gate. Other flagged items in
  4.1: nested workflow dir refused by the tool, advisory on unlistable directory, "once per
  session" via is_resume_session, advisory fires in this repo.
- QA: see the final report / `untracked/scratch/qa621.txt` in the worktree.
