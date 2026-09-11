# Plan 00375: `plan-qa` and `docs-qa` JSON disagree on the severity key

**Status**: Complete
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

`--json` is documented public API — CHANGELOG, `RELEASES/v3.32.0.md` and
`docs/guides/HANDLER_REFERENCE.md` all advertise it as "machine-readable
output" — so renaming the key is a breaking change and is declared as one.

**No deprecation window, by owner's decision.** The original plan emitted both
spellings for a release. That was wrong on its own terms: two live names for
one concept IS the defect, so a window makes the bug correct by policy for the
duration and invites a new reader to key on the spelling about to disappear. It
does not avoid the break either — removing the key later is the same breaking
change, deferred. Under this project's own semver guidelines
(`CLAUDE/development/RELEASING.md:966`, "Breaking API changes, removed
features" = MAJOR) the deferral changes nothing about the version owed.

The dual-key emission never shipped — it was staged in `UNRELEASED/` and
removed before release — so released history goes straight from `level` to
`severity`, with no version in which both were valid.

## Goals

- One name for one concept across both verbs, with no interval in which two
  are live.
- The break declared honestly under semver and carried by an upgrade-time
  migration rather than by a delay.

## Non-Goals

- Changing the finding shape beyond the severity key.
- Removing `run_corpus_qa._severity_of`'s tolerance. It reads whichever key it
  finds, so it still works against an OLDER installed daemon, which is a real
  configuration — the wrapper is versioned with the repo, the installed daemon
  is not.
- Building the pre-upgrade migration surface itself. That is Plan 00376; this
  one only supplies the breaking change that motivates it.
- **Waiting for the release.** Struck as out of the definition of done per the
  Plan Completion Checklist: a release is a human scope decision gated on the
  state of main, never on a plan. This plan's release-bound consequences are
  written into the holding area instead, where the release picks them up
  mechanically.

## Tasks

### Phase 1: Converge on one name

- [x] ✅ **Task 1.1**: Decide the surviving name. `severity` wins: it is what
  `docs-qa` already emits, it is the more common term across tooling, and
  `Level` is the plan-QA *enum's* internal name rather than a description of
  the field. The enums agree on their values (`advise`, `block`), so only the
  key name ever differed.
- [x] ✅ **Task 1.2**: `plan-qa --json` emits `severity` and nothing else;
  `docs-qa` is untouched. Declared BREAKING in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/27-plan-qa-json-now-names-severity-like-docs-qa.md`,
  which states the migration. No doc quoted either key name, so there was no
  doc truth to correct.
- [x] ✅ **Task 1.3**: `tests/unit/daemon/test_cli_qa_json_severity_key.py`
  drives both verbs and asserts they agree on the one name. Its class guard
  enumerates every severity-VALUED key and requires the set to be exactly
  `{"severity"}`, so a second spelling fails here instead of silently halving
  a reader's count.

### Phase 2: Hand the break to the release, and stop waiting for it

- [x] ✅ **Task 2.1**: ~~The release carrying this change is a MAJOR bump~~ —
  **struck as release-shaped.** A plan cannot perform a version bump; a human
  starts a release and it bundles whatever is on main. What this plan owes is
  that the break is *declared where the release reads it*, which callout 27
  does in its title (`BREAKING`) and body. The release pipeline's own
  breaking-change gate takes it from there.

- [x] ✅ **Task 2.2**: The migration is written and staged, not deferred:
  `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/01-rewrite-plan-qa-json-level-to-severity.md`
  instructs the upgrading agent to rewrite `level` → `severity` at any call
  site parsing `plan-qa --json`, marked `critical` because the failure mode is
  silence — a consumer using `.get("level")` reports a clean tree that is not
  clean.

  It is a POST-upgrade task because that is the channel that exists today.
  Running it BEFORE the upgrade lands is strictly better and is Plan 00376's
  work; that plan will move this task earlier rather than change its substance,
  so nothing here waits on it.

## Success Criteria

- [x] Both verbs' `--json` output carries `severity`, and only `severity`.
- [x] No released version exists in which two spellings are simultaneously
  valid.
- [x] Full QA passes and CI is green — `plan_qa` reports
  `0 findings (0 block, 0 advise)`, a split that agrees with its own total.
- [x] The break is declared where the release reads it, rather than this plan
  waiting for a release to happen.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/27-plan-qa-json-now-names-severity-like-docs-qa.md`
  (the BREAKING declaration) and
  `UNRELEASED/post-upgrade-tasks/01-rewrite-plan-qa-json-level-to-severity.md`
  (the call-site migration).

## Delivery & Milestones

- Found by Plan 00373: the QA wrapper it added printed a severity split that
  contradicted its own total.
- Phase 1 delivered at `3e1b9fc6` (with the `**Audience**` fix at `5a3c6730`)
  and verified at `85083625`; the deprecation window was dropped at `6e4731f0`.
- Closed without waiting for a release, per the Plan Completion Checklist's
  "Definition of done: merged into main, never released". The substance the
  release must carry is in the holding area; Plan 00376 will move the migration
  from post-upgrade to pre-upgrade.
