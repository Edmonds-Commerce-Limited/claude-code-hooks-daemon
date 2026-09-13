# Plan 00396: detect a plan written without reading its domain docs

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

An agent filed a plan about the daemon's DEPLOYMENT behaviour having read none of
the documents that own deployment, designed around the first adjacent mechanism
it happened to grep up, and committed a cost measurement and a full design on top
of that foundation before anyone checked it. The owner caught it. Nothing in the
daemon did.

This plan asks whether the daemon can catch that class mechanically. The
detectable signature is deliberately narrow, and is NOT "over-engineering",
which is unjudgeable:

> **A PLAN.md is filled in about domain X, and the session has read none of the
> documents that own X.**

The incident itself is recorded in Plan 00395's CORRECTION section and its
journal. That is the canonical account and it is not repeated here.

## Why this is worth a handler and not just a lesson

A lesson in a document is read by whoever already went looking. The failure here
was that the agent did not know it needed to look, so no document placed anywhere
would have reached it. That asymmetry — the reader who needs the warning is
precisely the one not reading — is what handlers exist for in this project.

There is also direct evidence that this class of nudge works on the agent it
would target. In the same session the `nitpick.hedging_language` stop hook fired
twice and changed the outcome both times: once turning "a few CI runs got
cancelled" into the measured finding that 13 of 20 had (Plan 00393 N2), once
catching an overstated claim about what the source fingerprint covers. Both were
acted on immediately. That is a stronger basis than the usual "an advisory might
help".

## The mechanism exists already — this is not new machinery

| Piece needed                       | Already shipped as                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| "has this session read file F?"    | `write_clobber_guard` keeps `session id -> paths whose contents it has seen` |
| bounded per-session state          | the same handler's caps, with an `<no-session-id>` bucket for id-less input  |
| a PLAN.md write interception point | `plan_qa_edit` / `plan_workflow` already fire on plan writes                 |
| "suggest before you invest"        | `plan_number_helper`'s dedupe-scout suggestion sets the precedent            |
| an inert handler staying silent    | `CanBeDormant` from Plan 00390, so an unconfigured project announces nothing |

One subtlety inherited from `write_clobber_guard` and worth carrying over: a
`Read` that was DENIED must not count as a read. The agent never saw those bytes.

## The open question — how a topic maps to its owning docs

1. **Config-declared table.** `plan_grounding.topics: [{match: [...], docs: [...]}]`.
   Explicit, portable, inert until a project declares it — which suits a check
   whose value is entirely project-specific. Costs the project an up-front
   mapping it may never write.
2. **Parse the routing table.** `CLAUDE/CLAUDE.md` already holds a topic→document
   map, and this repo's version would have named `LLM-INSTALL.md` correctly. But
   it is prose in a markdown table, the format is this project's own convention,
   and parsing it makes the handler depend on a document's shape.
3. **Directory-proximity heuristic.** Infer owning docs from the paths a plan
   mentions. Needs no configuration — and would have FAILED on the real
   incident, because the first revision of Plan 00395 cited `controller.py` and
   `metadata.py` accurately while never naming an install doc at all.

Option 3 is recorded precisely because it is the tempting zero-config answer and
demonstrably would not have caught the case that motivates the plan.

## Considered and rejected

- **Detecting "generalised from one sample".** The sharpest description of the
  actual error — probing one deployment mode and treating it as the model — but
  there is no mechanical signature. A probe that samples the environment looks
  identical whether or not its result is being over-generalised.
- **Detecting disproportionate design.** "A 535-file sweep for a one-file
  problem" requires already knowing the right answer, which is the thing being
  got wrong.
- **Blocking rather than advising.** Whether a plan is adequately grounded is a
  judgement call and this check will produce false positives by construction.
  The dedupe scout is the right precedent: suggest, never block.

## Goals

- A plan filled in about a configured domain, by a session that read none of that
  domain's owning documents, produces an advisory naming those documents.
- The advisory fires once per plan folder, not once per edit.
- A project that has configured nothing gets no advisory and no announced rule.
- A denied `Read` never counts as having read.

## Non-Goals

- Judging whether a plan is CORRECT, or whether its design is proportionate.
  This detects ungrounded plans, not wrong ones — a plan can cite every document
  and still be wrong, and an agent can `Read` a file without absorbing it.
- Blocking a plan write.
- Replacing the dedupe scout, which answers a different question (does this plan
  already exist?) at the same moment.

## Tasks

### Phase 1: Owner decision

- [ ] ⬜ **Task 1.1**: Owner picks the topic→docs mapping — option 1, 2, 3, or
  another. It decides whether the handler ships inert-by-default or tries to
  infer, and it is the whole design.

### Phase 2: Build, once decided

- [ ] ⬜ **Task 2.1**: A failing test first, reconstructed from the real
  incident: a session that reads `controller.py` and `metadata.py`, then fills a
  plan whose body is about deployment and versioning, must be advised to read
  `CLAUDE/LLM-INSTALL.md` and `CLAUDE/SELF_INSTALL.md`.
- [ ] ⬜ **Task 2.2**: A failing test for the negative — the same plan write,
  after those documents HAVE been read, must be silent.
- [ ] ⬜ **Task 2.3**: Implement, reusing the read-tracking shape proven in
  `write_clobber_guard` rather than inventing a second one; a denied `Read` must
  not count.
- [ ] ⬜ **Task 2.4**: Implement `CanBeDormant` so an unconfigured project's
  generated `CLAUDE.md` does not announce this as active policy (Plan 00390).
- [ ] ⬜ **Task 2.5**: Pin that it advises once per plan folder, so filling a
  plan across several edits does not repeat it.

## Success Criteria

- [ ] The real incident, reconstructed as a test, produces the advisory.
- [ ] The same plan write is silent once the owning documents have been read.
- [ ] A project with no configured mapping gets no advisory, and the handler is
  not announced as enforced policy.
- [ ] A denied `Read` does not satisfy the check.
- [ ] The advisory never blocks a write.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Raised by the owner while reviewing the Plan 00395 failure: the transcript is
  a clean example of the failure mode, so the question is whether the daemon can
  catch it rather than only document it.
- Grounded before designing, deliberately, given what this plan is about — the
  read-tracking primitive was confirmed present in `write_clobber_guard` before
  any design was written rather than assumed.
- Filed after `write_clobber_guard` blocked this very document's first write, for
  exactly its stated reason. The guard that catches an unread FILE already works;
  this plan is the same idea one level up, at an unread DOMAIN.
