# Plan 00234: handler value audit

**Status**: In Progress
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Fable (judgement) with Sonnet research agents
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00233 removed `transcript_archiver`. It had been in the tree since the
initial commit, copying every session transcript before every compaction, and it
protected nothing: nothing ever read a copy, and the durability it claimed was
already provided by the original file on the same physical disk. It cost 422 MB
and nobody noticed for the project's entire life.

One instance is an anecdote. This plan asked whether it is a pattern, across 97
handler rows in 16 event types. **Answer: it is a small pattern, not a rot.**
The tree is broadly sound — 74 of 97 rows are clean keeps — but the
transcript-archiver shape recurs in a handful of places, two of which prior
plans had already flagged by name without anyone removing the writer.

This is an **audit and planning** exercise. It produces evidence and a
prioritised proposal. It does not remove anything — each removal that survives
judgement becomes its own scoped follow-up, so that a removal is never bundled
with the reasoning that justified it.

## Goals

- A per-handler evidence dossier covering every handler in the tree ✔
- A defensible verdict per handler, distinguishing *"never fires"* from
  *"cannot fire"* from *"fires and is not worth it"* ✔ (`VERDICTS.md`)
- A prioritised proposal of removals, merges and de-scopings, each with the
  specific evidence that supports it ✔ (Phase 4 below)
- A fix for the instrument that should have caught this class and did not ✔
  (proposed; see Findings #1)

## Non-Goals

- **No code changes in this plan.** Audit and plan only.
- Not a rewrite of handlers judged worth keeping — behaviour changes are
  separate work. In particular, `pipe_blocker` and `markdown_organization`
  complexity concerns are noted, not actioned.
- Not a re-litigation of Plan 00233; that removal is delivered and closed.

## Findings summary

**Verdicts** (full tables with per-row basis in [VERDICTS.md](VERDICTS.md);
evidence in the seven `RESEARCH-*.md` dossiers):

| Verdict       | Count | Handlers                                      |
| ------------- | ----- | --------------------------------------------- |
| KEEP          | 74    | everything not listed below                   |
| FIX           | 11    | named per follow-up in Tasks 4.5–4.6 below    |
| REMOVE        | 10    | named per follow-up in Tasks 4.2–4.3 below    |
| MERGE→plan_qa | 2     | plan_completion_advisor, validate_plan_number |

The findings that matter, ranked:

1. **The instrument built to answer this audit's question is blind.** The Plan
   00209 verdict log retains **65 minutes** because 99.43% of its 10 MiB cap is
   status-line `allow` records carrying zero bits (a renderer has no other
   verdict). Excluding `status-*` records would stretch the same cap to ~8
   days. This is the DBF fix and it goes **first**, so every later removal can
   be verified against a working instrument. See
   `RESEARCH-verdict-log-is-blind.md`.
2. **The writer-with-no-reader shape is now at four instances, and a prior
   audit walked past three of them.** Counting `transcript_archiver`, the tree
   has produced this shape four times. Plan 00181 looked directly at three:
   it tabulated `subagent_completion_logger` (3.4 MB) and
   `notification_logger` as `Consumer: NONE` — then **capped them instead of
   removing them** (a bounded unread log is still an unread log) — and
   certified `cleanup` (SessionEnd) as "the one functioning reaper" without
   checking the producer side; `temp/hooks/` is written by nothing and does
   not exist. That makes this finding bigger than any individual removal:
   nothing in the project continuously asks "does anything consume this?" —
   Phase 3 names the guard (Decision 5, DECISIONS.md).
3. **Two handlers are structurally unable to act.** `usage_tracking` has
   `matches()` hardcoded `False` while config says `enabled: true` (confirmed
   against live firing data: 0 of 44,180 records); `yolo_container_detection`
   ships with a nested flag off in every install so `matches()` cannot return
   True by default. Both are the vacuous-guard shape with a config entry that
   misleads readers.
4. **Nagging advisories that repeat what is already in context.**
   `bash_error_detector` (the most active behavioural handler, 110 fires/65
   min) tells the agent its own tool output contains the word "error";
   `task_tdd_advisor` injects ~30 lines already resident via CLAUDE.md's eager
   `@`-imports; `task_completion_checker` restates on every Stop what
   `auto_continue_stop` actually enforces; `remind_prompt_library` recommends a
   command and a doc that **do not exist** (verified);
   `post_clear_auto_execute` survives its own Cancelled plan, which rated it
   "marginal". `git_context_injector` is the same cost shape (~460 tokens ×
   every prompt, no change-detection) but its duty is real — FIX, not remove.
5. **Two real broken features (fix, not delete).**
   `background_process_tracker` writes records without the `pgid` key its own
   harvester reads — the designed wall-TTL breach can never fire.
   `lsp_enforcement`'s single-file exemption misses multi-line Bash commands —
   a live-reproduced false positive in the exact path built to fix the previous
   one.
6. **Confirmed structural duplication at Stop.** The nitpick pseudo-event fires
   `dismissive_language`/`hedging_language` on `stop:1/1` while the dedicated
   Stop twins also run — two advisories for one finding, traced through
   `controller.py`'s non-deduplicating merge. The pre_tool_use leg is justified
   coverage; the stop leg never was. In the plan family,
   `plan_completion_advisor` demonstrably co-fires with plan_qa's
   `terminal-placement-hint` on the same tool call, and `validate_plan_number`
   never denies while `counter-sanity` re-implements its check with teeth.
7. **The status line is a cost story, not a value story.** `git_branch`'s 2.0s
   TTL against a ~1.15s render interval provably locks a 50% cache-miss rate ⇒
   ~6,200 git subprocess spawns/hour from one handler. A never-ccy project pays
   `supervisor_indicator`'s full `/proc` walk every ~5s of rendering, forever.
   Small tuning, large multipliers (~3,130 renders/hour).

Cross-cutting: the project's dominant failure mode is **not** vacuous guards —
it is (a) guidance text drifting from the mechanism it describes (twice in
Cohort A alone, both since fixed), and (b) artefacts/advisories introduced
without a consumer or a stated need surviving because nothing continuously asks
whether they are consumed. The keeps are genuinely healthy: dense false-positive
fix histories, negative acceptance tests, and measured calibration (Plan 00208's
zero-false-positive self-scan) are the norm, not the exception.

## Context & Background

### The shapes worth looking for

Derived from the 00233 post-mortem and the Plan 00196/00230 vacuous-guard
lessons. A handler is suspect when it shows one of these:

| Shape                  | Test                                                                                                         |
| ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| **No consumer**        | It writes an artefact — file, log, cache, sidecar — that nothing in the repo reads. The 00233 shape exactly. |
| **Vacuous guard**      | Its condition cannot be true for realistic input. Registered, running, blind — indistinguishable from clean. |
| **Duplicated**         | Another handler, a QA script, a linter, or Claude Code itself already enforces it.                           |
| **Cost exceeds value** | An advisory that fires often, injecting context tokens for advice CLAUDE.md already carries.                 |
| **Never justified**    | Introduced with no stated need, and no evidence since that it has ever helped.                               |

### The trap in this audit

The daemon's own `hooks-daemon verdicts` report prints a **"Never-fired
handlers"** list, and it is tempting to read that as the answer. It is not. The
list is drawn from a rolling sample that currently retains **65 minutes**, and it
names handlers such as `prevent-destructive-git` whose entire value is that they
fire rarely and catastrophically. Rarity is what success looks like for a safety
handler.

"Never fires" is therefore not evidence of pointlessness. Only "**cannot** fire",
established from the code and its tests, is. **No verdict in this plan rests on
a firing count** — see `RESEARCH-verdict-log-is-blind.md`.

## Tasks

### Phase 1: Evidence gathering (parallel, read-only)

- [x] ✅ **Task 1.1**: Split ~100 handlers into seven cohorts and dispatch one
  Sonnet research agent per cohort against a shared evidence rubric
- [x] ✅ **Task 1.2**: Measure the live verdict log directly — the one input no
  cohort agent can obtain — and record the anti-inference warning above
- [x] ✅ **Task 1.3**: Collect all seven cohort dossiers into this plan folder

### Phase 2: Judgement

- [x] ✅ **Task 2.1**: Fable read every dossier plus the verdict-log evidence,
  independently verified the removal-grade claims (PromptLibrary absence,
  `temp/hooks` producer absence, `bash_error_detector` mechanism,
  `validate_instruction_content` config), and assigned a verdict per handler
  in `VERDICTS.md`
- [x] ✅ **Task 2.2**: Separated verdicts into 10 removals, 2 merges, 11 fixes
  and 74 keeps; overturned seven researcher SUSPECT signals to KEEP, and
  upgraded three the other way, with recorded reasons (see VERDICTS.md
  "Overturned researcher findings")
- [x] ✅ **Task 2.3**: Ranked by confidence and blast radius (Phase 4 proposal
  below, safest first)

### Phase 3: Defence before fix

- [x] ✅ **Task 3.1**: Named the guard that failed for each confirmed class —
  see Technical Decision 5
- [x] ✅ **Task 3.2**: Proposed the instrument fixes: verdict-log status-\*
  exclusion (continuous firing-rate visibility), a lint forbidding
  `matches(): return False` on registered handlers, and guidance-truth tests
  deriving `get_claude_md()` claims from pattern tables

### Phase 4: Proposal (follow-up plans, ranked safest first)

Each follow-up removal inherits the Plan 00233 costs: a `RETIRED_HANDLERS`
entry, a config-changes manifest entry, doc updates, and daemon restart
verification. None of these tasks is executed inside this plan.

- [ ] ⬜ **Task 4.1**: Follow-up A — fix the instrument first: exclude
  `status-*` handlers from verdict recording (or give them a separate cap),
  extending the retained window from 65 minutes to ~8 days so later removals
  are verifiable against real firing data
- [ ] ⬜ **Task 4.2**: Follow-up B — dead-code removals (high confidence, zero
  behavioural surface): `usage_tracking` + `stats_cache_reader`, `cleanup`
  (SessionEnd), `subagent_completion_logger`, `notification_logger`,
  `remind_prompt_library`; delete accumulated `untracked/logs/hooks/*.jsonl`
- [ ] ⬜ **Task 4.3**: Follow-up C — advisory removals (medium confidence,
  human sign-off per handler): `bash_error_detector`,
  `task_completion_checker`, `task_tdd_advisor`, `post_clear_auto_execute`,
  `yolo_container_detection`
- [ ] ⬜ **Task 4.4**: Follow-up D — plan-family consolidation: retire
  `plan_completion_advisor` and `validate_plan_number` in favour of the plan_qa
  checks, **relocating `_record_allocation`'s counter-advance side effect
  first**; dedupe `plan_workflow`'s size-tier guidance with `plan_qa_edit`'s;
  consider flipping `commit_gate_mode` to `block` as the enforcement
  prerequisite
- [ ] ⬜ **Task 4.5**: Follow-up E — broken-feature fixes: emit `pgid` in
  `background_process_tracker` records (or drop the dead TTL path); fix
  `lsp_enforcement`'s multi-line single-file exemption and verify LSP tool
  reachability; drop `stop:1/1` from nitpick triggers; add decay cache to
  `suggest_status_line`
- [ ] ⬜ **Task 4.6**: Follow-up F — cost tuning (lowest urgency): widen
  `git_branch` render TTL past the resonance point; bound
  `supervisor_indicator`'s negative-path `/proc` walk; mtime-gate
  `account_display`; change-detect `git_context_injector`; rate-limit
  `daemon_restart_verifier`
- [ ] ⬜ **Task 4.7**: Hand this proposal to the human for scope decisions
  before any follow-up plan is created

## Technical Decisions

Recorded in full in **[DECISIONS.md](DECISIONS.md)** — extracted to keep this
document lean. In brief:

1. **Overturn, don't inherit, researcher suspicion** — seven SUSPECT signals
   downgraded to KEEP, two upgraded to REMOVE, one to FIX.
2. **"Leave it" is a real verdict** — removal is not free, so a cheap redundant
   handler stays; `current_time` is the canonical case.
3. **Merge preserves duty** — and `validate_plan_number` hides a counter-advance
   side effect that must be relocated before it is retired.
4. **Keep the Stop-side language detectors**, cut nitpick's `stop:1/1` leg.
5. **The guards that failed, per class (DBF)** — the most important section: why
   nothing was continuously asking whether artefacts are consumed.

## Success Criteria

- [x] Every handler in the tree carries a recorded verdict — including the
  keeps, so the next audit starts from a baseline rather than from scratch
- [x] Every removal proposal cites specific evidence, not a firing count
- [x] No handler is proposed for removal on "never fired" evidence alone
- [x] The instrument gap is identified and a fix proposed
- [ ] Zero code changes in this plan (holds so far; verified at close)

## Risks & Mitigations

| Risk                                                      | Impact | Probability | Mitigation                                                                           |
| --------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------ |
| "Never fired" misread as "pointless", deleting safety net | High   | High        | Anti-inference rule enforced; every REMOVE grounded in cannot-fire/no-consumer       |
| Removal degrades clients with stale config keys           | High   | Low         | Plan 00233's retired-handler registry + manifests are a hard requirement per removal |
| Merge loses the counter-advance side effect               | Medium | Medium      | Named in Decision 3 as a blocking precondition of Follow-up D                        |
| Audit becomes a rewrite                                   | Medium | Medium      | Non-goal stated; pipe_blocker/markdown_organization complexity explicitly deferred   |

## Delivery & Milestones

- Seven cohort research agents dispatched; verdict-log evidence note landed
- Judgement complete: `VERDICTS.md` (97 rows) + this revised plan
