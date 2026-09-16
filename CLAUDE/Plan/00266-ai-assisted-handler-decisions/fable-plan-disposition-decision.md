# Plan 00266 — disposition ruling

Decision document only. It does not change the status header; it says what the
status header should become and why.

## Decision

Close Plan 00266 as **Complete (reduced scope)**: Phase 1 delivered the
plan's deliverable, Task 4.0/4.0b fixed a real defect, and Phases 2, 3, 4.1–4.3
and 5 are struck as declined-on-evidence rather than left as work nobody
intends to do. The research documents stay in the archived folder as reference
material; the revival conditions stay in the record as the trigger for a NEW
plan, never for reopening this one.

## Reasoning

**What "Dormant" means here, and why this plan does not meet it.** The status
vocabulary is in `CLAUDE/core/PlanWorkflow.core.md:395-402`: `Complete`,
`Cancelled` and `Superseded` are terminal; `Dormant` is non-terminal. The only
check that reasons about `Dormant`, `dormant-honesty`
(`src/claude_code_hooks_daemon/plan_qa/checks/dormant_honesty.py:18-21`),
defines it by its remediation: "Dormant with a parenthetical naming what it is
blocked on". Dormant is parked-on-a-blocker. This plan is blocked on nothing.
Its own header says so: "Phases 2–5 are deliberately NOT being built"
(`PLAN.md:11-12`), and its Success Criteria are titled "Revival conditions"
(`:244`), none of which has occurred.

**The anti-pattern is the one the repository just ruled against.** The
definition of done (`PlanWorkflow.core.md:582-605`) says a plan gated on an
event outside its control — there, a release — "is not `In Progress`; it is
finished work with a mislabelled header", and instructs: "strike it as out of
the definition of done, record where its substance lives, and close the plan."
A plan held open until a false positive that "cannot be worked around by
rewording" appears (`PLAN.md:247-250`) is gated on an event that may never
arrive, and the recent commit `e0685cc3` ("retire an expired release-deferral
that was never a gate") applied exactly this reasoning to another plan.

**Why Complete rather than Cancelled or Superseded.**

- The plan's own framing of its question was factual: "Phase 1 answers that
  factual question and enumerates every real mechanism available"
  (`PLAN.md:20-22`). Goals 1–3 (`:66-76`) are met and evidenced across four
  supporting documents. Goal 4 ("decide, and build") was half met: the
  decision was taken, and the decision was "not yet, on this evidence" — a
  decision is a deliverable of a research plan, and the journal records it as
  one ("Building on that evidence would be manufacturing a justification",
  `JOURNAL/00266-Journal-26-08-24.md:283-286`).
- Task 4.0 shipped a genuine fix — `validate_hook_commands` was blind to two
  daemon commands nested in one entry (`PLAN.md:175-179`; commit `689cb2b7`).
- `Superseded` requires a superseding plan; none exists.
- `Cancelled` would be honest about the build phases but would file a plan
  whose primary deliverable was produced and is cited elsewhere under "won't
  do", beside plans that were abandoned (`CLAUDE/Plan/README.md:273`).
  The README already carries a precedent for the chosen shape: "Completed:
  ... includes 1 reduced-scope plan" (`:266`).
- The journal's stated reason for choosing Dormant over Complete — that
  archiving with unticked tasks would contradict `header-body-coherence`
  (`JOURNAL:288-291`) — is not what the check does. `header-body-coherence`
  returns nothing for a terminal header (`plan_qa/checks/header_body_coherence.py:49`);
  it only ever judges `Not Started` and `In Progress`. Commit `64be8e84`
  archived Plan 00174 as Superseded with two tasks deliberately unticked and
  passed the gate, on the stated principle that "a Superseded plan with honest
  open tasks tells a future reader more than one edited to look finished".
  The same applies here: strike the declined tasks with the task grammar's
  `❌` Cancelled icon and one line of reason each; do not tick them.

**Reference value is preserved by closing, not by staying open.**
`bin/hooks-daemon find-plan` searches the archive ("searched CLAUDE/Plan/
including archives"), and the Completed README row carries the summary. The
four research documents move with the folder unchanged.

**Revival condition 4 is checked, not assumed.** The raw hooks documentation
fetched today via `bin/hooks-daemon contract-status` still says "Agent hooks
are experimental and may change" (`untracked/scratch/hooks-raw.md:414`,
`:3615`). Conditions 1–3 depend on a false positive or exploitation appearing;
the niggles ledger (Plan 00419) is where such an observation would be recorded,
and a ledger entry that cites this plan's `DECISIONS.md` §3c is the correct
birth of a new plan.

## What closing costs, and who bears it

One atomic archive commit: status flip, `git mv` into `Completed/`, README row
moved with the statistics recount, holding-area criterion satisfied (this plan
has no release-bound consequences — Task 4.0's fix shipped in an earlier
release). Borne by whoever closes it. Nobody loses the research.

The real cost is discoverability: the `hooks-daemon-plan-dedupe-scout` agent
reads live plans, so a future agent proposing AI-assisted handlers will not be
pointed at this plan by that scout. Mitigation: the Completed README row should
name the leading architecture (dynamic prompting via `tool_use_id`) and the
measured costs, so a `find-plan "AI-assisted"` or a README scan lands on it.

## Strongest argument against

Keeping it Dormant costs nothing per day and keeps the four revival conditions
in the Active list where the next agent scanning for AI-handler work sees them.
That is a genuine convenience. Against it: the Active list is the place the
project reads to answer "is the slate clean?", and every plan there that no one
intends to progress makes that question harder to answer — which is the exact
harm the definition-of-done ruling names (`PlanWorkflow.core.md:593-595`).
"Zero daily cost" is also the argument for every stale plan ever kept.

## Does a human gate remain?

No. The choice between Complete-reduced-scope and Cancelled is a labelling
question with a defensible technical answer (the deliverable was produced),
not a preference only the owner can hold. Whether AI-assisted handlers are
ever built is a future decision that this plan's own text defers to evidence,
and the evidence has not arrived.
