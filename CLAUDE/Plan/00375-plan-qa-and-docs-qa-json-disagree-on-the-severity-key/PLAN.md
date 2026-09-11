# Plan 00375: `plan-qa` and `docs-qa` JSON disagree on the severity key

**Status**: In Progress
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
- Building the pre-upgrade migration surface itself. That is its own plan; this
  one only supplies the breaking change that motivates it.

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

### Phase 2: Release consequences

- [ ] ⬜ **Task 2.1**: The release carrying this change is a MAJOR bump
  (`CLAUDE/development/RELEASING.md:966`). A human starts the release; an agent
  never does.
- [ ] ⬜ **Task 2.2**: Ship a pre-upgrade migration task instructing the
  upgrading agent to rewrite `level` → `severity` at any call site parsing
  `plan-qa --json`, BEFORE the new version is installed. Blocked on the
  pre-upgrade surface existing (see the pre-upgrade plan); until then the
  release-notes callout is the only channel.

## Success Criteria

- [x] Both verbs' `--json` output carries `severity`, and only `severity`.
- [x] No released version exists in which two spellings are simultaneously
  valid.
- [x] Full QA passes and CI is green — `plan_qa` reports
  `0 findings (0 block, 0 advise)`, a split that agrees with its own total.
- [ ] The break is declared as MAJOR in the release that carries it.
- [ ] A pre-upgrade migration rewrites affected call sites rather than
  announcing the change to them.

## Delivery & Milestones

- Found by Plan 00373: the QA wrapper it added printed a severity split that
  contradicted its own total.
