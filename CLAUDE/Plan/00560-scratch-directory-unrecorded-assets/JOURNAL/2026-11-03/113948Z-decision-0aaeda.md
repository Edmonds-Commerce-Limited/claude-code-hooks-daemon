## 11:39 · decision · —   — plan written; items 6 and 7b left to 00558

Plan written from #155 and its requested-changes comment. Claims about the code were checked first and recorded in CODE-FACTS.md. All four claims hold, and two are wider than the issue says: `markdown_organization` allows markdown anywhere under `untracked/`, not only in the scratch directory, and `dispatch_declaration` accepts any path token as a non-plan destination, including `/tmp`.

A fact the issue did not raise: the Plan 00470 stale-scratch report is a UserPromptSubmit housekeeping advisory, off by default, not a SessionStart report. It suggests `find ... -delete` on age alone, which would delete assets with the scratch. Task 6.3 replaces that suggestion.

Decisions:

- Items 6 and 7b (forced worktree removal, unpushed branches, dirty worktrees) stay with Plan 00558, Goals 10, 2 and 6. They are not duplicated here.
- The two stop gates (00558's branch guard and this plan's scratch gate) share one design for registration, priority, message shape and the never-strand rule. Task 1.3 settles it with 00558 before either gate is built.
- Guidance changes come first (Phases 2 and 3): they are cheap and stop the steering. Then the ledger and gate, the allowlist deny, and finally the sweep.
- `Read` counts as consumption only because the allowlist deny stops a non-scratch shape being created in the first place. The two layers are designed together (DESIGN-QUESTIONS.md D1).

This repository's own backlog at plan time: 90,346 files, 1.4 GB under `untracked/scratch/`, with sub-agent reports in `untracked/briefs/` and `untracked/agent-reports/`. Owner question Q4 proposes a tracked baseline plus a one-off manual triage.
