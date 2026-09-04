# Plan 00330: hooks daemon skill surface coherence

**Status**: Not Started
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The `hooks-daemon` skill is the surface a HUMAN touches, and it has drifted
from the daemon behind it. Owner ruling: it "MUST be fully up to date and
coherent for every release".

Three asks, one theme.

**Coverage.** `optimise` scores handlers from a hardcoded list across five
areas rather than enumerating the registry: **21 of 110 configurable handlers**
are named. It therefore cannot be current by construction — every new handler
must be added by hand and nothing requires it. Plan 00323 added a contract test
that every name in the checklist RESOLVES to a live handler, so the checklist
cannot recommend a retired handler; the untested direction is the other one,
whether it names enough of them. In this repo all 89 uncovered handlers happen
to be enabled, so the blind spot is invisible here — a client on defaults is
where it bites, which is exactly why dogfooding did not surface it.

**Surface size.** The skill exposes subcommands a human never types. Some are
capabilities that should be documented rather than routed. A smaller surface
is easier to keep coherent, so this is not only tidiness.

**One command.** The human wants a single "do all the housekeeping"
invocation — config optimise, skills scan, docs QA, plan QA, the rest — rather
than remembering which subcommand does what.

A worked example of the drift shipped in `8bbd5bec`: `/hooks-daemon optimise`
was documented in three places, including as a MANDATORY upgrade step, while
missing from the routing table entirely. The entry point existed; only the
route did not. A test now pins both directions, and that test is the model
this plan generalises.

## Goals

- `optimise` derives its handler set from the registry, so a handler cannot
  ship without being considered.
- One skill invocation performs the full housekeeping pass.
- The routed subcommand surface is only what a human actually invokes.
- A release cannot proceed while the skill surface disagrees with the shipped
  handlers, config, or CLI.

## Non-Goals

- **Not** auto-enabling handlers. `optimise` recommends and applies on
  confirmation; wider coverage must not become wider automatic change.
- **Not** deleting capabilities when trimming the subcommand list. A command a
  human does not type becomes documentation, not a removal.
- **Not** re-litigating `daemon.exclude_paths` versus
  `documentation.qa.scope_exclude_globs` (see Task 1.4 — recorded, not fixed
  here).

## Tasks

### Phase 1: Establish the true surface

- [ ] ⬜ **Task 1.1**: Inventory every routed subcommand against evidence of
  human use. Classify each: routed, documented-only, or retire. Evidence
  before opinion — the owner reports never using several, and which ones is a
  question for the data.
- [ ] ⬜ **Task 1.2**: Inventory what `optimise` covers against the handler
  registry. The headline is 21 of 110, but the fair denominator is smaller:
  status-line components and always-on handlers are not things it should
  score. Produce the real actionable gap.
- [ ] ⬜ **Task 1.3**: Confirm the five scored areas are still the right
  taxonomy for a registry-derived checklist, or replace them. A hardcoded
  list can carry an arbitrary grouping; a derived one needs a rule that
  assigns any new handler to an area without human judgement.
- [ ] ⬜ **Task 1.4**: Record — do not fix — that neither docs QA nor plan QA
  consults the project-wide `daemon.exclude_paths`, which many other handler
  families honour via `utils/path_exclusion.py`. Found during the Plan 00329
  scope-exclusion audit. Distinct, pre-existing, and needs its own plan.

### Phase 2: Make optimise registry-derived

- [ ] ⬜ **Task 2.1**: Drive the checklist from the registry, so a new handler
  appears without anyone remembering to add it.
- [ ] ⬜ **Task 2.2**: Decide how a handler declares it is NOT optimise's
  business. A derived list needs an opt-out at the handler, not a subtraction
  list in the skill — the subtraction list would rot exactly like the
  hardcoded list it replaces.
- [ ] ⬜ **Task 2.3**: Keep the output readable as coverage grows. A review a
  human abandons because it is too long fails the same way Plan 00329's report
  does.

### Phase 3: One housekeeping command

- [ ] ⬜ **Task 3.1**: Define what "full housekeeping" runs, and in what
  order. Some steps mutate (`optimise` edits config; the format check
  auto-fixes), so ordering and re-entrancy are load-bearing.
- [ ] ⬜ **Task 3.2**: Decide which steps are report-only and which may act
  without confirmation. The safe default is report-everything, act-on-request;
  a single command that silently changes many things is worse than several
  explicit ones.
- [ ] ⬜ **Task 3.3**: Orchestrate independent steps as subagents, each
  returning what it CHANGED rather than what it read, so the coordinator's
  context does not accumulate every step's full output.

### Phase 4: The release-time guarantee

- [ ] ⬜ **Task 4.1**: A QA gate failing when a configurable handler is
  invisible to `optimise`, generalising the dispatchability test from
  `8bbd5bec`.
- [ ] ⬜ **Task 4.2**: Extend it to the rest of the surface: a documented CLI
  command that does not exist, a skill doc naming a removed capability, a
  config key the skill references that the schema does not define.
- [ ] ⬜ **Task 4.3**: Wire the gate into the release pipeline's blocking QA
  step so a drifted skill surface cannot ship.

## Success Criteria

- [ ] Adding a handler with no skill change fails the gate.
- [ ] `optimise`'s covered set is derived, and any exclusion is declared at
  the handler rather than listed in the skill.
- [ ] One invocation runs the full housekeeping pass and reports what it did.
- [ ] Every routed subcommand is one a human invokes; the rest are documented
  capabilities.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00330-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — the real surface and the real coverage gap are measured.
- Milestone B — `optimise` is registry-derived and cannot silently omit a
  handler.
- Milestone C — a single housekeeping invocation exists.
- Milestone D — the release gate blocks a drifted skill surface.
