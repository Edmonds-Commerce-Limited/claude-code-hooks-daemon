# Plan 00435: priority band table contradicts shipped handlers

**Status**: Not Started
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

From ledger [00422](../00422-niggles-ledger-fifteen/NIGGLES.md) N5, rows (a) and
(d) — the un-gated documentation corrections in the v3.65.0 release-review
table. Checking them found the same drift twice more in the same table, so this
plan fixes the table rather than the row.

`CLAUDE/HANDLER_DEVELOPMENT.md` carries the single documented statement of the
priority bands, declares `PriorityRange` in `constants/priority.py` as the
source those bands derive from, and is quoted verbatim into `CONTRIBUTING.md`
and `docs/guides/CONFIGURATION.md` under `ssot-quote` markers. Measured against
the code it cites:

| documented                                | shipped                                                                            |
| ----------------------------------------- | ---------------------------------------------------------------------------------- |
| `0-9` — "no built-in handlers ship here"  | `cron_stop_enforcer` 7, `cron_subagent_stop_enforcer` 7, `teammate_reap_advisor` 9 |
| `56-69` — Advisory                        | `PriorityRange.ADVISORY_MAX` is **73**; four handlers ship at 70-73                |
| nothing between `56-69` and `100+`        | that is where those four live                                                      |
| `100+` — "no built-in handlers ship here" | still true; nothing ships at or above 100                                          |

The `0-9` row is the one with teeth, and it is a trap rather than a typo. Those
three handlers are not below 10 by accident: `auto_continue_stop` is terminal,
matches nearly every ordinary stop, and this project overrides it to priority
10, so a Stop handler registered after it is unreachable on the common path. An
author following the documented table puts their Stop handler in the Safety
band at 10+ and it never fires — which is what happened to a handler at 12
before `tests/integration/test_stop_chain_terminal_shadowing.py` existed.

The band table has no guard at all. `quote_drift` keeps the two quoting copies
honest against the SSoT, so all three surfaces say the same wrong thing
together; nothing compares any of them against `PriorityRange` or against the
handlers that actually ship.

Two smaller findings ride along. The `handlers/stop/__init__.py` docstring says
`cron_stop_enforcer` "sits BEFORE it (priority 8)" while the constant is 7 —
and the constant's own comment explains why it is 7 and not 8 (the
`release_blocker` project handler occupies 8). The `hooks-daemon` skill's
`dev-handlers.md` states the Advisory band as `56-65`, a third value, and is
not covered by `quote_drift` because it paraphrases rather than quotes.

## Goals

- The documented band table matches `PriorityRange` and names what actually
  ships in the `0-9` band, including WHY those handlers are there.
- A test fails when the documented bands and `PriorityRange` disagree, and when
  any shipped handler priority falls outside every documented band.
- The stale `priority 8` in the stop package docstring reads 7.
- The skill's paraphrase agrees with the SSoT.

## Non-Goals

- **Moving any handler.** Every priority below 10 is deliberate and argued in
  `priority.py`; the documentation is what is wrong.
- **Re-deciding the band boundaries.** `PriorityRange` is the source of truth
  and this plan makes the prose match it, not the other way round.
- **N5 row (f).** The unit assertion compares against the SHIPPED
  `AUTO_CONTINUE_STOP`, which this project overrides — but the class is already
  guarded by `test_stop_chain_terminal_shadowing.py`, which reads the real
  config. That row needs a ledger correction, not code.

## Tasks

### Phase 1: the guard

- [ ] ⬜ **Task 1.1**: RED — a test parsing the band table out of the SSoT
  document and asserting each row's range against `PriorityRange`, plus a
  second asserting every shipped `Priority` handler constant falls inside a
  documented band. Both must fail today: the first on `56-69` vs
  `ADVISORY_MAX=73`, the second on the four handlers at 70-73.

- [ ] ⬜ **Task 1.2**: A control that the parser is not matching nothing — the
  row count it extracts is asserted, so a table it silently failed to find
  cannot read as agreement.

### Phase 2: the corrections

- [ ] ⬜ **Task 2.1**: Correct the SSoT table: the `0-9` row names the three
  Stop-family handlers and the reason they are there, and the Advisory row
  reads `56-73`. Update both `ssot-quote` copies so `quote_drift` stays green.

- [ ] ⬜ **Task 2.2**: `handlers/stop/__init__.py` — `priority 8` becomes 7,
  naming what holds 8.

- [ ] ⬜ **Task 2.3**: The skill's `dev-handlers.md` (source and deployed copy)
  agrees with the SSoT.

## Success Criteria

- [ ] ⬜ Every new test observed RED before the correction and GREEN after.
- [ ] ⬜ `llm_qa.py all` passes.
- [ ] ⬜ A release note lands in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` —
  the band table is guidance every client handler author follows.
- [ ] ⬜ N5 rows (a) and (d) are marked done in ledger 00422, and row (f) is
  corrected there rather than built.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00435-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
