# Plan 00434: dedupe scout count checked externally

**Status**: Complete
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Ledger [00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N13 recorded a
dispatch of `hooks-daemon-plan-dedupe-scout` that answered "Checked 0 live
plans. The plan directory contains no active plan folders" about a directory
holding dozens, and a second dispatch against the same unchanged tree that
answered correctly — except by one, reporting 28 where 29 folders exist. The
dramatic zero does not reproduce; the quiet miscount is the finding.

The agent definition already asks for the count, explains why it matters, and
tells the agent to reconcile it against its own enumerated list. That is the
vacuous guard one level up: a reader that miscounted cannot audit its own
count. N13's revised remedy is that the number must be checkable from OUTSIDE
the agent — the caller states how many plan folders exist, so a disagreeing
report is visibly wrong instead of quietly trusted.

The same entry found a second, smaller defect on the way: step 3b instructs a
`grep -ril ... Completed/*/PLAN.md` shell command, while the definition's
frontmatter declares `tools: Read, Glob, Grep` — no Bash. The `## Prior art`
section it produces is compulsory ("an omitted section is indistinguishable
from a skipped check"), so an instruction naming an idiom the agent cannot run
invites either a dropped section or a `Grepped N archived plans.` line that was
never measured.

**Prior art**: [Plan 00216](../Completed/00216-plan-duplicate-source-detection/PLAN.md)
built the scout and measured this exact variance — 34, then 32, then 17 plans
reported against an unchanged tree of 34 — then closed deliberately without
fixing it, on the grounds that the check is advisory. This plan closes only
that gap.

The dedupe dispatch filed before this plan demonstrated the problem a third
time, and more sharply than a wrong number would have: it reported `Checked 30 live plans.` while the tree held 29 folders when it was dispatched and 30 by
the time it answered, because this plan's own folder was created mid-run.
Nothing in the report distinguishes a correct count from a stale one. A number
the CALLER states at dispatch time does.

## Goals

- `mkplan.bash` prints the live plan-folder count beside the reminder to
  dispatch the scout, so the caller holds a number the agent did not produce.
- `plan_number_helper`'s guidance states the reconciliation rule: a report
  whose `Checked N live plans.` disagrees with that count is wrong, and the
  action is to re-dispatch rather than to trust the verdict.
- Step 3b is written in terms of the Grep tool the agent actually has.
- A test fails when any shipped agent's instructions contain a shell fence its
  frontmatter does not declare `Bash` for — the general form of the step 3b
  defect, with the docs-qa agent (which DOES declare Bash and DOES carry a
  shell fence) as the control that keeps it from passing vacuously.

## Non-Goals

- **Making the scout's count trustworthy from the inside.** It cannot be. The
  remedy is an external cross-check, not better self-auditing instructions.
- **Blocking on a mismatch.** The dedupe check is advisory by design; a loud
  disagreement is the whole ask.
- **Re-litigating N13's verdict.** The zero-plan run did not reproduce and the
  entry already records that.

## Tasks

### Phase 1: the external count

- [x] ✅ **Task 1.1**: RED — a test asserting `mkplan.bash`'s scout reminder
  states the number of plan folders in the plan root, driven against a real
  temporary repository with a known number of folders (so the assertion is
  about a count, not about wording).

- [x] ✅ **Task 1.2**: GREEN — count the root plan folders in `mkplan.bash` and
  print the number with the reminder.

- [x] ✅ **Task 1.3**: `plan_number_helper.get_claude_md()` carries the
  reconciliation rule, with a test that it names both the sentence the agent
  must emit and what to do when it disagrees.

### Phase 2: instructions the agent can actually follow

- [x] ✅ **Task 2.1**: RED — a test over every shipped agent template: a
  ```` ```bash ```` fence in the body requires `Bash` in the frontmatter `tools:`
  line. It fails on the dedupe scout today and passes on docs-qa, which is the
  control.

- [x] ✅ **Task 2.2**: GREEN — rewrite step 3b in Grep-tool terms, bump the
  template's version marker and its `AgentAssetSpec`, ledger the outgoing md5
  as a historic revision, and redeploy the copy under `.claude/agents/`.

## Success Criteria

- [x] ✅ Every new test is observed RED against the pre-fix code and GREEN
  after, with the docs-qa control green in both directions.
- [x] ✅ `llm_qa.py all` passes (34/35, then 35/35 after `llm_qa format`).
- [x] ✅ A release note lands in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, because both the agent template
  and the scaffolder are client-facing.
- [x] ✅ N13 in ledger 00422 records the outcome, and its Phase 4 task is
  ticked.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00434-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
