# Plan 00391: plan close requires proven definition of done

**Status**: Not Started
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Closing a plan is the one moment where an agent grades its own homework. Today
nothing asks it to show its working: the terminal status flip is a Write/Edit
like any other, and the checks around it are structural — `header-body-coherence`
asks that a fully-ticked body match a `Complete` header, `terminal-state-atomic`
that the archive move ship in the same commit. None of them asks *whether the
work is actually done*.

**This is the agent-satisfiable counterpart to Plan 00367's human gate.** The
owner's ruling is that plan lifecycle stays fully agent-driven:

> we absolutely should not be blocking plan close on human — if we have clear
> definition of done which is unambiguously achieved then the plan should be
> closed

So this plan does not add a second thing to wait for a human about. It makes the
close prove itself: the project DECLARES its definition of done in config, the
first attempt to close is denied with that checklist, and the agent satisfies it
by recording evidence per item in the plan's `JOURNAL/` before retrying.

For this repository the owner stated the DoD directly: **fully complete, QA
passing, merged into the main branch, and ready for release.** Explicitly NOT
released — release is a separate human-driven cadence (`/release` is
human-gated) and a plan must never be held open waiting for one.

## The design decision that makes or breaks this

**A "block the first attempt, allow the retry" gate is defeated by retrying.**
That mechanic already exists in this daemon — `lsp_enforcement`'s `block_once`
mode — and its own documentation says the quiet part out loud: "the first
symbol-lookup grep in a session is denied with guidance; subsequent retries are
allowed". That is right for a nudge. For a DoD gate it would be ceremony: the
agent reads the checklist, retries unchanged, and closes.

So the gate keys on the EVIDENCE, not on an attempt counter. The flip is denied
while no attestation exists; it passes once one does. In practice that feels
exactly like "the first attempt is blocked", because the first attempt has no
attestation yet — but what is enforced is the record, not the count.

### Machine-checked items and attested items are not the same thing

Some DoD items the daemon can verify; most it cannot. `ready for release` and
`QA passing` are claims about the world. `merged into the main branch` is a git
question the daemon can answer. Whether every success criterion is ticked it
already knows.

**An item that COULD be checked but is merely attested is the weak link**, and a
gate made only of attestations teaches the agent that writing the sentence is
the job. So a declared item carries a `verify:` discriminator: machine-checkable
items are CHECKED and cannot be talked past; the rest require an evidence line
(a commit SHA, a run URL, a command and its result) rather than a bare "yes".

## The policy is three-way, not a boolean

The owner's refinement: the close policy should have three postures, not an
on/off gate.

| Mode         | Behaviour when a plan's DoD is MET                                | Behaviour when it is not               |
| ------------ | ----------------------------------------------------------------- | -------------------------------------- |
| `human_gate` | Report it ready and name `approve-plan-close NNNNN` for the human | Deny the flip, listing the unmet items |
| `encourage`  | Actively advise closing it NOW                                    | Deny the flip, listing the unmet items |
| `neutral`    | Say nothing                                                       | Deny the flip, listing the unmet items |

`human_gate` is Plan 00367's existing behaviour plus the half it is missing: it
currently denies the flip and tells the AGENT to report the plan ready, but
nothing ever tells the HUMAN a plan is waiting on them. That is the #36-shaped
failure — work delivered and the person who has to act on it never told.

**Back-compatibility is not optional here**: `plan_workflow.close_requires_human_approval`
already ships and is set in real projects. It maps to the new key —
`true` → `human_gate`, `false` → `neutral` — so no installed project changes
behaviour on upgrade, with a `config-changes` migration entry recording it.
Whether `encourage` should become the shipped DEFAULT is an owner call and is
deliberately left open: it is the better posture, but it changes behaviour for
every existing install.

## What this fixes, and the part it does not

**The `encourage` direction WOULD have caught the failure that prompted all of
this.** Plans 00386 and 00389 were finished — QA 29/29, CI green, merged — and
sat open for days because the agent believed a gate existed that did not. An
advisory naming them as DoD-met-and-still-open is exactly the correction that
was missing, and it costs nothing when there is nothing to say.

**And the signal it keys on must not be the checkboxes**, which is the sharp
lesson from that incident. `header-body-coherence` already fires when every box
is ticked and the header still says `In Progress` — it should have caught both
plans. It did not, because the agent deliberately left the final criterion
unticked, and wrote down why: ticking it would complete the body and force a
`Complete` header it believed it was not allowed to write. The check was
side-stepped by an agent acting in good faith.

So a nudge built on "all boxes ticked" is gameable by the party it is aimed at.
One built on facts the agent does not control — the work is merged, the tree is
clean, the declared machine-checks pass — is not. That is why the machine-check
half of the DoD is load-bearing for BOTH directions, not just the gate.

**The part this does not fix**: nothing here would have corrected the agent's
false belief about the config key itself. That was Plan 00390 N2, and it is
fixed separately.

## Prior art this must reuse, not re-invent

Checked before filing (`hooks-daemon-plan-dedupe-scout`, 17 live plans, 69
archived): nothing already covers this, but three pieces of machinery do most of
the hard part.

- **`journal-completion-entry`** (`plan_qa/checks/journal_completion_entry.py`)
  already detects a commit that flips a plan to terminal without staging a
  closing journal entry. It already solves terminal-flip detection and the
  subtlety that an archive `git mv` makes existing day-files ride along as
  renames — so it counts only an Added file, a Modified file, or a rename whose
  content GREW. That is the exact primitive this needs, and re-deriving it is
  how the two drift apart. It is opt-in
  (`plan_workflow.qa.journal.enforce_on_completion`, `false` here) and ADVISE.
- **`plan_close_approval`** (Plan 00367) is the shape for the EDIT-time half:
  detecting a terminal `**Status**` flip in a `Write`/`Edit` before it lands,
  including the `would_be_content` handling and the "only the flip is gated, a
  plan already closed stays editable" rule.
- **Plan 00163** delivered the `JOURNAL/` infrastructure the evidence lands in;
  **Plan 00144** delivered the plan-QA staging this plugs into.

## Goals

- A project can declare its definition of done in `.claude/hooks-daemon.yaml`,
  and closing a plan requires each item to be satisfied.
- Machine-checkable items are CHECKED, not attested.
- Every other item requires an evidence line in the plan's `JOURNAL/`, so the
  proof is durable, reviewable and outside `PLAN.md`.
- A retry with no new evidence is denied exactly as the first attempt was.
- Silent and inert when a project declares no DoD — shipped OFF by default.

## Non-Goals

- Blocking a close on a human. Ruled out by the owner; Plan 00367's key remains
  the separate, opt-in way to want that.
- Gating a close on a RELEASE. A plan is done when it is merged and ready, not
  when it ships.
- Verifying claims the daemon cannot see (CI status, a QA run on another
  machine). Those are attested with evidence, and the plan says so rather than
  implying a verification it does not perform.
- Changing what `header-body-coherence` or `terminal-state-atomic` do.

## Tasks

### Phase 1: Declare the definition of done

- [ ] ⬜ **Task 1.1**: A config model for `plan_workflow.close_dod` — an
  ordered list of items, each with an `id`, human text, and a `verify:`
  discriminator selecting `attest` or a named machine check. Ships empty, so
  the feature is inert until a project opts in.
- [ ] ⬜ **Task 1.2**: The machine checks, starting with the two already
  answerable from data the daemon holds: every success criterion ticked, and the
  plan's work merged into the default branch. Each returns a verdict plus the
  evidence it used, so a denial can say WHY rather than just "not satisfied".

### Phase 2: The gate

- [ ] ⬜ **Task 2.1**: Deny a terminal `**Status**` flip while any declared item
  is unsatisfied, reusing `plan_close_approval`'s flip detection rather than a
  second copy. The deny lists every item with its state, because a checklist
  that reports only the first failure costs one round trip per item.
- [ ] ⬜ **Task 2.2**: Attestation is read from the plan's `JOURNAL/`, keyed by
  item `id`, and must carry evidence — an entry that names the item and nothing
  else does not satisfy it.
- [ ] ⬜ **Task 2.3**: A commit-stage twin, reusing `journal-completion-entry`'s
  staged-change primitive, so the gate is not bypassed by a `git add` of content
  written through a route the edit hook never saw.

### Phase 3: Prove it cannot be talked past

- [ ] ⬜ **Task 3.1**: A test that an unchanged retry after a denial is denied
  again. This is the test the whole design rests on; without it the feature is
  `block_once` with extra steps.
- [ ] ⬜ **Task 3.2**: A test that a machine-checkable item CANNOT be satisfied
  by attesting it — the attestation path must not be a universal override.
- [ ] ⬜ **Task 3.3**: Fail-open review. Every error path (unreadable journal,
  malformed config, missing plan folder) must ALLOW and log, never wedge a plan
  shut. A gate that can trap a finished plan is worse than no gate.

### Phase 4: The other two directions

- [ ] ⬜ **Task 4.1**: `plan_workflow.close_policy` with the three modes, and
  the back-compatible mapping from `close_requires_human_approval` pinned by
  test in both directions.
- [ ] ⬜ **Task 4.2**: `encourage` — a plan whose DoD is MET and whose header is
  still non-terminal is reported, naming the plan and what satisfied each item.
  Keyed on the machine checks, never on the checkbox count, for the reason
  recorded above.
- [ ] ⬜ **Task 4.3**: `human_gate` gains its missing half — the human is told
  which plans are waiting on their `approve-plan-close`, rather than only the
  agent being told to report it.
- [ ] ⬜ **Task 4.4**: `neutral` says nothing in either case, pinned by test.
  Silence is a supported choice, not an unimplemented branch.

### Phase 5: Dogfood

- [ ] ⬜ **Task 5.1**: Declare this repository's own DoD — complete, QA passing,
  merged to main, ready for release — and close the next plan through it.

## Success Criteria

- [ ] A plan whose DoD is unmet cannot be closed, and the denial names every
  unmet item and what would satisfy it.
- [ ] An unchanged retry is denied again, pinned by test.
- [ ] A machine-checkable item cannot be satisfied by attestation, pinned by test.
- [ ] A project declaring no DoD sees no change whatsoever.
- [ ] All three modes behave as tabled, and an existing project's
  `close_requires_human_approval` setting survives the upgrade unchanged.
- [ ] `encourage` names a DoD-met plan that is still open — reproduced against
  Plans 00386 and 00389 as they stood, since that is the case it exists for.
- [ ] The encourage signal cannot be suppressed by leaving a checkbox unticked,
  pinned by test. That is how the existing coherence check was side-stepped.
- [ ] No error path can leave a finished plan unclosable.
- [ ] Nothing in this plan waits on a human — the close stays agent-driven.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Requested by the owner: "what we could have is a plan close DOD checklist —
  this could be hooks daemon config driven — block the first attempt to close
  plan with a confirmation statement requirement to confirm that the full DOD
  has been achieved and logging proof to the plan journal".
- Filed against the owner's ruling in the same message that plan close must
  NOT be gated on a human, and that completion is not gated on release.
- Widened by the owner in the same session: "maybe the human plan gate works
  both ways — if not enabled then it actively encourages closing plans if they
  are fully done to DOD spec", then "or maybe 3 ways — human gate, encourage
  close, or neutral".
- Sibling of Plan 00367, which owns the human-gated close. Same moment, opposite
  answer to "who proves it" — and after the widening, 00367's key becomes one of
  this plan's three modes rather than a separate switch.
- The `encourage` mode is the direction that would have caught the incident
  behind Plan 00390 N2. The gate direction would not have; both are recorded
  above so the distinction is not lost.
