# Plan System

A quick human orientation to how development work is tracked in this project.
The canonical, in-depth reference is
[CLAUDE/PlanWorkflow.md](../CLAUDE/PlanWorkflow.md) — this page just gives you
the shape of the thing.

## The idea in a nutshell

Work that takes more than a couple of hours gets a **plan**: a numbered folder
under `CLAUDE/Plan/` (e.g. `00042-add-user-auth/`) holding everything about
that piece of work. Numbers are sequential, zero-padded, and never reused.
Smaller jobs don't need a plan — a simple task list is fine.

Each plan folder contains:

- **`PLAN.md`** — the plan itself: goals, task tree with status icons,
  decisions, success criteria. Kept lean and always stating *current* truth;
  it is edited in place, and git holds its history.
- **`JOURNAL/`** — append-only day-files recording what actually happened:
  progress, findings, incidents, hand-offs. Journals grow forever and are
  never trimmed. See [CLAUDE/PlanJournalling.md](../CLAUDE/PlanJournalling.md)
  for the journalling contract.
- **Supporting docs** (optional) — research, analysis, evidence, kept next to
  the plan they belong to.

The split matters: `PLAN.md` is re-read in full every session, so it stays
small and current; the journal is only ever sampled, so it can grow without
cost. Don't turn `PLAN.md` into a progress log.

## Lifecycle

A plan moves from *Not Started* through *In Progress* to a terminal status
(*Complete*, *Cancelled*, *Superseded*). When it reaches a terminal status,
its folder moves into the archive (`CLAUDE/Plan/Completed/`) and the index
(`CLAUDE/Plan/README.md`) is updated — all in the same commit. Archived plans
are a historical record and are not edited to match the present.

The full status vocabulary, task grammar, templates, and the completion
checklist live in [CLAUDE/PlanWorkflow.md](../CLAUDE/PlanWorkflow.md).

## Where things live

| What                 | Where                            |
| -------------------- | -------------------------------- |
| Active plans         | `CLAUDE/Plan/NNNNN-description/` |
| Archived plans       | `CLAUDE/Plan/Completed/`         |
| Index of all plans   | `CLAUDE/Plan/README.md`          |
| Canonical workflow   | `CLAUDE/PlanWorkflow.md`         |
| Journalling contract | `CLAUDE/PlanJournalling.md`      |

## Commands you might actually run

Create a new plan (never hand-`mkdir` a plan folder — the script assigns the
next number atomically from a git-backed counter):

```bash
CLAUDE/Plan/mkplan.bash "descriptive-kebab-name"
```

Check plan-tree health (the daemon also runs these checks automatically at
edit, commit, and session start):

```bash
bin/hooks-daemon plan-qa --sweep            # whole tree; exit 1 on findings
bin/hooks-daemon plan-qa --lint <PLAN.md>   # one file
bin/hooks-daemon plan-qa --check-staged     # what a commit would look like
```

Reference plans in commit messages as `Plan NNNNN: <description>` so work is
traceable back to its plan.

## Automated enforcement

If the hooks daemon is installed, it lints plan documents as they are written,
gates commits on cross-file consistency (index rows, archive moves, number
collisions), and reports drift at session start. The plan system also works as
a plain documentation convention without the daemon — it's just folders and
markdown. Policy and configuration are described in
[CLAUDE/PlanWorkflow.md](../CLAUDE/PlanWorkflow.md) (see "Plan QA").
