# Plan 00375: `plan-qa` and `docs-qa` JSON disagree on the severity key

**Status**: Not Started
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Main Thread

## Overview

Two sibling CLI verbs emit the same concept under two different names.
`docs-qa --sweep --json` gives each finding a `"severity"`; `plan-qa --sweep --json` gives it a `"level"`. Nothing else differs — same finding shape, same
values (`block` / `advise`), same purpose.

This is not cosmetic. It produced a real defect within an hour of first being
met: Plan 00373's new QA wrapper counted `severity`, so every plan finding
fell out of the severity split while still counting toward the total, and the
tool printed `3 findings (0 block, 0 advise)` — a summary contradicting itself.
That was fixed at the reading end (`run_corpus_qa._severity_of` tries both
keys, with a class guard asserting the split always sums to the total), so
nothing is currently broken. The trap is still there for the next reader.

Deferred rather than fixed inside Plan 00373 because `--json` is documented
public API — CHANGELOG, `RELEASES/v3.32.0.md` and
`docs/guides/HANDLER_REFERENCE.md` all advertise it as "machine-readable
output" — so renaming a key is a breaking change for anyone parsing it in CI,
and belongs in a release with an upgrade note rather than smuggled into a QA
plan. No in-repo consumer reads either key except the wrapper above, which
handles both.

## Goals

- One name for one concept across both verbs.
- No silent break for an existing consumer parsing `plan-qa --json`.

## Non-Goals

- Changing the finding shape beyond the severity key.
- Removing `run_corpus_qa._severity_of`'s tolerance. It should keep working
  against an older installed daemon, and its class guard is the thing that
  catches a future third name.

## Tasks

### Phase 1: Converge, additively

- [ ] ⬜ **Task 1.1**: Decide the surviving name. `severity` is the
  recommendation: it is what `docs-qa` already emits, it is the more common
  term across tooling, and `Level` is the plan-QA *enum's* internal name
  rather than a description of the field.
- [ ] ⬜ **Task 1.2**: Emit BOTH keys from the verb that has to change, so no
  existing consumer breaks. Record the old key as deprecated in the upgrade
  notes for that release.
- [ ] ⬜ **Task 1.3**: A test asserting both verbs' `--json` findings carry
  the same severity key, so the two cannot diverge again.

### Phase 2: Retire the old key

- [ ] ⬜ **Task 2.1**: In a later release, drop the deprecated key, with the
  removal recorded in `CLAUDE/UPGRADES/`.

## Success Criteria

- [ ] Both verbs' `--json` output carries `severity` with the same values.
- [ ] A consumer parsing the old key still works during the deprecation
  window.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Found by Plan 00373: the QA wrapper it added printed a severity split that
  contradicted its own total.
