# PR 231 QA (docs or code tier) failure

Failing steps in the job: "Format (black)" and "Targeted QA (code tier)". CI logs were
unavailable while the run was in progress, so the step names came from the jobs API.

Cause: two files were not black-formatted: one over-long call in
tests/unit/supervise/test_rate_limit_dialog.py and the `render_startup_banner`
signature in .claude/ccy/claude-supervise.py (black wants it on one line).

Fix: ran black on both files (formatting only, no behaviour change). Black now reports clean.
Targeted QA step failure was not separately visible; it most likely repeats the same
black check. Re-check CI after the push.
