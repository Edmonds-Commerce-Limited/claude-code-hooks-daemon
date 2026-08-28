# Plan Lifecycle

See [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md) for full planning workflow, templates, and standards.

## Plan Sources

Plans come from two sources:

1. **GitHub Issues** — Some plans originate from GitHub issues. These have a `**GitHub Issue**: #N` field in the PLAN.md header. When completing these plans, update the issue with implementation details and close it.
2. **Internal plans** — Created directly in `CLAUDE/Plan/` without a corresponding GitHub issue. These are tracked entirely through the plan files and README.md.

## Directory Structure

```
CLAUDE/Plan/
  README.md              # Index of all plans (active + completed)
  CLAUDE.md              # This file - lifecycle instructions
  NNNNN-description/     # Active plans (5-digit zero-padded)
    PLAN.md              # Current plan document
    PLAN-v1.md           # Superseded versions (if revised)
    CRITIQUE-v1.md       # Review documents (if plan was critiqued)
  Completed/
    NNNNN-description/   # Completed plans (moved here when done)
```

## Plan Lifecycle

### 1. Create

- Create folder: `CLAUDE/Plan/NNNNN-description/`
- Write `PLAN.md` following the template in [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md)
- Add entry to `README.md` under **Active Plans**
- If from a GitHub issue, include `**GitHub Issue**: #N` in the header

### 2. Execute

- Work through tasks following TDD workflow
- Update task status in `PLAN.md` as you go
- Run QA before commits: `./scripts/qa/llm_qa.py all`
- Reference plan in commits: `Plan NNNNN: Description`
- **Always commit the plan folder alongside the work it tracks.** `CLAUDE/Plan/*`
  files are tracked source, not temporary artifacts. Before every commit, check
  `git status` for untracked plan folders and include them — never let a plan
  folder linger untracked across commits or through a release.

### 3. Review & Revise (if needed)

If a plan is reviewed and superseded:

- Rename original: `PLAN.md` -> `PLAN-v1.md`
- Write critique: `CRITIQUE-v1.md`
- Write revised plan: `PLAN-v2.md` (or `PLAN.md` for the current version)
- Cross-reference between documents

### 4. Complete

When all tasks are done and QA passes:

1. **Update plan status** to `Complete` (NO completion date — git is the source of truth for "when"; cite the delivery commit hash(es) in the "Delivery & Milestones" section instead). See [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md) "Plan Completion Checklist".
2. **Move folder** to `CLAUDE/Plan/Completed/NNNNN-description/`
3. **Update `README.md`**:
   - Remove from **Active Plans**
   - Add to **Completed Plans** with a summary and the delivery commit hash(es) (not a date)
   - Update link to point to `Completed/` path
   - Update plan statistics
4. **If GitHub issue exists**:
   - Comment with implementation summary
   - Close the issue with `--reason completed`
5. **Commit and push** the move

### 5. Cancel (if needed)

If a plan is abandoned:

- Update status to `Cancelled` with reason
- Move to `Completed/` (cancelled plans are still preserved)
- Add to **Cancelled Plans** section in `README.md`
- Close GitHub issue if applicable

## Quick Reference

```bash
# Move completed plan
git mv CLAUDE/Plan/NNNNN-desc CLAUDE/Plan/Completed/NNNNN-desc

# Close GitHub issue
gh issue close N --reason completed --comment "Completed in Plan NNNNN"

# Update README.md links after move
# Old: (NNNNN-desc/PLAN.md)
# New: (Completed/NNNNN-desc/PLAN.md)
```
