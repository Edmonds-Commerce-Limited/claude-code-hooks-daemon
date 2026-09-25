# Blast-radius policy decision — cross-reference for Plan 00396

The standing policy, its evidence and the reasoning for this plan's
sub-decision live in one place:

[`../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md`](../Completed/00394-failsafe-cron-coverage-starts-at-first-plan-write/fable-blast-radius-policy-decision.md)
— section "Plan 00396 — how a topic maps to its owning docs".

## This plan's sub-decision

**Option 1** (`PLAN.md:58-61`): a config-declared `plan_grounding.topics`
table, in a handler that ships enabled but `CanBeDormant` — silent and not
announced in the generated `CLAUDE.md` — until a project declares at least one
topic. This repository declares its own table as project config, hand-derived
from `CLAUDE/CLAUDE.md`'s routing table; the routing table is the *source* for
that one-off derivation, never parsed by the handler.

Why not the others, in one line each:

- Option 3 (directory proximity) would have missed the motivating incident
  (`PLAN.md:66-69`) — a detector that misses its own case is not a detector.
- Option 2 (parse the routing table) makes a shipped handler depend on the
  shape of one project's prose table that no client has.

Precedent the decision rests on: `sensitive_content` registered enabled but
inert until configured, "a guard nobody knows about protects nobody"
(`src/claude_code_hooks_daemon/daemon/init_config.py:147-152`); `command_hints`
as one config-driven handler rather than one per entry.

**Human gate: none.** Task 1.1 can be closed by recording the linked document
as the pick.
