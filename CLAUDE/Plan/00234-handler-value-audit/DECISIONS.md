# Plan 00234 — Technical Decisions

Extracted from `PLAN.md` to keep it under the size tiers. These are the
judgement calls a reader would otherwise question. Per-handler verdicts are in
[VERDICTS.md](VERDICTS.md); the evidence is in the seven `RESEARCH-*.md`
dossiers.

## Decision 1: Overturn, don't inherit, researcher suspicion

**Context**: Researchers were told not to soften findings; several over-flagged.

**Decision**: Seven SUSPECT/STRONG-SUSPECT signals were downgraded to KEEP with
recorded reasons — `pipe_blocker`, `security_antipattern`,
`error_hiding_blocker`, `current_time`, `daemon_stats`, `git_repo_name`,
`critical_thinking_advisory`. The recurring grounds: complexity that earned its
keep through real fixed bugs is not a removal case; an already-fixed
documentation defect does not indict a sound mechanism; and zero-fire evidence
is inadmissible by this plan's own rule.

Two signals moved the other way — `remind_prompt_library` and `cleanup` were
upgraded to REMOVE after direct filesystem verification, and `plan_workflow` was
upgraded from SUSPECT to the actionable FIX. Full table in VERDICTS.md.

**Date**: 2026-08-13

## Decision 2: "Leave it" is a real verdict — removal is not free

**Context**: Plan 00233 proved a removal degrades every client whose config
still names the handler (DEGRADED MODE) until the retired-handler registry
absorbed it, and each removal still costs a registry entry, manifests and docs.

**Decision**: Cheap, slightly-redundant handlers stay. `current_time` is the
canonical case: it duplicates the terminal clock at zero cost, and the machinery
of removing it costs more than the handler ever will. The 10 proposed removals
all clear a higher bar — no consumer, cannot fire, or a recurring context cost
for information already present.

This cuts against the instinct that a smaller handler count is self-evidently
better. It is not: the count is not the cost.

**Date**: 2026-08-13

## Decision 3: Merge preserves duty — and one merge has a hidden side effect

**Context**: `plan_completion_advisor` and `validate_plan_number` duplicate
plan_qa checks that are more complete. But `validate_plan_number` is not pure
advice: on a *correct* number it advances the git plan counter
(`_record_allocation`) — the only non-mkplan path that does.

**Decision**: Both are MERGE, not REMOVE, and the merge plan must relocate the
counter-advance (into the commit gate, or by declaring `mkplan.bash` the sole
allocation path) before the handler is retired. Also noted: with
`commit_gate_mode: warn` project-wide, the "more authoritative" plan_qa checks
are advisory in practice today, so the merge should weigh flipping that mode to
`block` — otherwise the merge trades a weak early-warning layer for a weaker one.

**Date**: 2026-08-13

## Decision 4: Keep the Stop-side language detectors, cut nitpick's stop leg

**Context**: The dismissive/hedging pattern sets are a single source of truth,
but two registered handler families both fire them at Stop.

**Decision**: The dedicated Stop handlers keep the resident CLAUDE.md guidance
and the advisory dedup; nitpick's unique justification (Plan 00081) was mid-plan
PreToolUse coverage, never Stop. The fix is one trigger change — drop
`stop:1/1` — with zero client blast radius. A FIX, not a removal of either
implementation.

**Date**: 2026-08-13

## Decision 5: The guards that failed, per class (DBF)

**Context**: Engineering standard 15 requires naming the blind guard, not just
the defect. This is the most important section of the audit: the individual
removals are small, but the reason nobody noticed them is systemic.

**Decision**:

- **Writer-with-no-reader** — no instrument asks whether artefacts are
  *consumed*. Plan 00181 audited *bounds*, not consumers, which is why it
  tabulated `subagent_completion_logger` and `notification_logger` as
  `Consumer: NONE` and then capped them rather than removing them; bounding an
  unread log yields a fixed-size unread log. The same plan certified `cleanup`
  as "the one functioning reaper" without checking whether anything writes to
  the directory it reaps. Guard: the verdict-log fix (Task 4.1) for firing-rate
  visibility, plus a convention that any handler-written artefact names its
  consumer at introduction. Cohort D's artefact ledger is the seed of that
  register.
- **Enabled-but-cannot-fire** — nothing relates config `enabled:` to structural
  fireability, so a config entry can assert a lie about runtime state. Guard: a
  mechanical lint forbidding a registered handler whose `matches()` is a
  constant `False` (catches `usage_tracking` exactly). `yolo_container_detection`'s
  nested-flag variant is not mechanically catchable and needs the review
  convention instead.
- **Guidance-drift** — `get_claude_md()` text is hand-maintained beside the
  pattern tables it describes, and bit twice in Cohort A alone (`pipe_blocker`'s
  whitelist claims, `security_antipattern`'s SQL-injection overclaim). Guard:
  guidance-truth tests deriving claims from the tables, as LESSONS.md already
  proposes for `pipe_blocker`.
- **Redundant-advisory accretion** — no mechanical guard is proposed. This class
  genuinely needs judgement, and pretending otherwise would produce a guard that
  fires on every legitimate advisory. `VERDICTS.md` is the mitigation: it makes
  the next audit cheap by recording the keeps as well as the removals.

**Date**: 2026-08-13
