# Plan Lifecycle

Full planning workflow, templates, status tokens, QA enforcement and the Plan
Completion Checklist: [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md).
Journalling: [CLAUDE/PlanJournalling.md](../PlanJournalling.md).

Directory shape: `NNNNN-description/PLAN.md` (+ supporting docs and
`JOURNAL/`), indexed in `README.md`, archived under `Completed/`.

## Local conventions (this directory only)

- **Plan sources**: a plan may originate from a GitHub issue — record
  `**GitHub Issue**: #N` in the PLAN.md header. On completion, comment an
  implementation summary and close it
  (`gh issue close N --reason completed`). Internal plans are tracked
  entirely through the plan files and `README.md`.
- **Always commit the plan folder alongside the work it tracks.**
  `CLAUDE/Plan/*` files are tracked source, not temporary artifacts — check
  `git status` for untracked plan folders before every commit; never let one
  linger untracked across commits or through a release.
- **Superseded revisions stay in the folder**: rename the original to
  `PLAN-v1.md`, record the review as `CRITIQUE-v1.md`, write the revised plan
  as `PLAN.md`, and cross-reference between the documents.
- **Archive moves are atomic**: a terminal status flip (Complete, Cancelled,
  Superseded) ships the `git mv` into `Completed/` plus the README row and
  statistics update in the SAME commit — see the Plan Completion Checklist in
  [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md).
- **Completed rows age out**: the main `README.md` keeps only the 30
  highest-numbered completed rows; on archival, add your row, then move any
  rows beyond that window verbatim into `Completed/README.md` in the same
  commit — enforced by
  `tests/integration/test_plan_index_navigability.py`.
