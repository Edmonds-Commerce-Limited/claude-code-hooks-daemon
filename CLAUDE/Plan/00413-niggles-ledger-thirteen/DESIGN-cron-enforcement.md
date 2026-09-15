# Cron delivery and duplication: the design

Supporting document for ledger [00413](PLAN.md) N6: the owner's direction, the
facts found while answering it, and the design that follows. Kept out of
PLAN.md so that document stays a lean spec.

## The defect being designed around

`persistent_cron_assertor` cannot create a Claude Code cron; no API exists for
it. Its entire contribution is to PRINT "run `CronList`, then `CronCreate` for
anything missing" and rely on the agent to act. If that text is skimmed, the
declared cron never exists.

## CORRECTION: the daemon CAN see the crons

**The premise this entry was built on is false, and the correction changes the
design rather than decorating it.**

It said: nothing reports the difference, because `CronList` is session memory
the daemon cannot read, so "declared and running" and "declared and absent" are
indistinguishable from outside. That is true of `CronList`. It is not true of
the daemon.

`Stop` and `SubagentStop` receive **`session_crons`** — one entry per
session-scoped wakeup "sourced from `CronCreate`, `ScheduleWakeup`, and
`/loop`", each carrying `id`, `schedule`, `recurring` and `prompt`. It is in
the vendored contract already (`contracts/claude-code-hooks/Stop.json:48`), and
**no handler reads it.** It has been sitting there, documented, while two plans
rested on the daemon being blind to it — this one and 00412's D7.

So verification needs no supervisor, no acknowledgement verb and no
cooperation from the agent. The daemon is handed the answer.

This is the same failure as N12, one layer up: a capability was ruled out by
inference rather than checked, and the inference was wrong. Both times the
documentation said yes.

## The design

**1. Verify at `Stop`, in the daemon.** Compare declared (`persistent_crons`)
against actual (`session_crons`). Three constraints the implementation must
respect, all from the contract rather than guessed:

- `session_crons` reaches `Stop`/`SubagentStop` only, NOT `SessionStart`. So
  the check cannot run at session start — it runs at the first stop, which is
  the right moment anyway: the cron only has to exist before the session ends.
- `prompt` is **capped at 1000 characters** with an in-string `… [+N chars]`
  marker. This project's `issue-sdlc` prompt is longer than that, so exact
  prompt equality would never match. Match on `schedule` plus a normalised
  comparison of the prompt up to the cap.
- `session_crons` is present in the example yet conditional in practice, so it
  belongs in N12's `conditional_input_fields` slot — an absent list must not be
  read as "no crons exist" and used to nag.

**2. The teeth are a Stop block.** A declared cron with no match blocks the
stop, naming the exact `CronCreate` to run. That is the mechanism every other
Stop rule here already uses, it is enforcement the daemon applies itself, and
it cannot be skimmed: the session does not end until the declared state is
real or the agent explicitly says why not.

**3. The supervisor becomes the backstop, not the primary.** Demoted
deliberately. It still covers what the daemon cannot — a session that never
takes another turn — and the session-start nudge stays, because it is free and
the owner's one-line test showed it works. But enforcement no longer DEPENDS on
a component outside the daemon, which was the weakest part of the earlier
sketch.

**Why not watch `CronCreate` as a tool call?** It would work, and it was the
first design here. `session_crons` is strictly better: it reports the resulting
STATE rather than an observed action, so it is correct across a cron created
before the daemon started, deleted after creation, or created in a way the tool
hook missed. State beats event.

## The owner's rulings

Recorded verbatim, because both are rulings rather than suggestions:

> there's a very large amount of session start output, but in my experience
> claude itself totally ignores this — it's mainly for humans

> the system MUST have teeth or its pointless
>
> where the agent ignores hooks, we defer to the supervisor to handle it

That names an ENFORCEMENT TIER this ledger had not considered. The ccy
supervisor runs outside the agent — a `--worker` subprocess owned by the PTY
host — which is why it can see and act on what the agent can decline. So the
design question stops being "how do we word the advisory better" (the answer to
which is always "we cannot") and becomes **what does the supervisor check, and
what does it do when the check fails.**

## The evidence that settles the mechanism

The owner tested it on the other machine by typing one line:

> session start message crons — you need to follow the instructions

The agent immediately ran `CronList` (empty), created the job with the exact
declared schedule and prompt, re-ran `CronList` to confirm `c82f1a9b`, and
continued to the remaining session-start items unprompted. The owner's reading:

> maybe supervisor — after session start — simply needs to say "read session
> start and act upon all items"

**This is the cheapest candidate on the table and should be tried before
anything structural is built.** It also isolates the real variable: the
information was never missing, and rewording it was never going to help. What
changed was the CHANNEL. SessionStart output arrives as injected context, which
an agent weighs as background; the same words arriving as a turn-level directive
are acted on. The supervisor can produce the second kind and the daemon cannot
— which is precisely why the enforcement tier is the supervisor's.

**A nudge is not yet teeth.** Re-asking more loudly still depends on compliance.
Teeth means the supervisor VERIFIES the outcome, and it can: it reads the PTY
stream, so whether `CronCreate` was actually called is observable to it even
though `CronList` is session memory the daemon cannot read. Ship the nudge;
design for the check.

## Duplication: three problems, not one

The owner asks whether a **hostname lock** is the mechanism. Recorded as the
question, not the answer, because the obvious implementation collides with this
project's standing ruling that a per-machine fact must not live in tracked
config.

`PersistentCronConfig` is `extra="forbid"` with `id`, `schedule`, `prompt`,
`enabled`, `description` — **no per-machine gating**. Every checkout therefore
declares the same job, so two machines both create it and both fire at `:23`.

- **Env-var activation** — a `when_env:` gate on the declared job, set on
  exactly one machine. Not a lock: it removes the need for one by ensuring only
  one machine ever creates the job. Cheapest, and it matches the
  `CCY_HOST_HOSTNAME` precedent exactly.

- **A real lock** — needed only when you cannot control which machines run, and
  it requires SHARED state. In-repo untracked is per-checkout so it cannot
  arbitrate between machines; tracked puts a hostname in git. That leaves
  GitHub-side state as the only honest shared substrate.

- **The claim race, which is a separate defect** — even ONE machine is not
  enough for `issue-sdlc`. Its only claim is the `agent-working` label, applied
  AFTER selection, so two ticks on the same minute both select before either
  labels: two agents, one issue, two branches.

These are not alternatives. The first two concern the cron, the third concerns
the job, and choosing only one leaves a live failure.

### Settled: env-var activation, and an atomic claim

**Duplication — `when_env:` on the declared job.** `PersistentCronConfig` is
`extra="forbid"`, so this is a schema addition: a job carrying `when_env: VAR`
is asserted only where that variable is set and non-empty; a job without one
is asserted everywhere, so nothing existing changes.

Chosen over a real lock because a lock answers a question this project does not
have. A lock arbitrates between machines you do not control; here the owner
controls which machines run, so the cheaper move is to ensure only one ever
creates the job. It also matches the `CCY_HOST_HOSTNAME` precedent exactly and
keeps the per-machine fact in the environment, satisfying the standing ruling
that such a fact must not live in tracked config. The GitHub-side lock stays
recorded as the honest answer IF that premise ever changes — it is the only
shared substrate available — but building it now would be paying for a
guarantee nothing currently needs.

**The claim race — claim by pushing a ref, not by labelling.** `agent-working`
cannot fix this and no amount of ordering will: a label is read-modify-write
against a server with no compare-and-swap, so two ticks that both read "no
label" both proceed.

Git already has the primitive. Pushing a NEW ref fails, server-side and
atomically, if that ref already exists. So `issue-sdlc` claims an issue by
pushing a deterministically-named branch (`issue-<N>-sdlc`) BEFORE selecting
work; the push either succeeds — you hold the claim — or is rejected, and the
tick moves to the next eligible issue. No new infrastructure, no polling, and
the claim is visible to a human in the branch list.

`agent-working` stays as the human-facing SIGNAL it is good at being. It is
simply no longer asked to be a lock, which it never was.

**This is one defect fixed and one hazard deliberately left.** Env-var
activation does not fix the claim race — two sessions on the SAME machine still
double-tick — which is exactly why the two are settled separately rather than
as alternatives.

## Where this belongs longer-term

Plan [00412](../00412-jobs-recurring-work-and-security-review/PLAN.md) already
carries the structural answer, and it is the owner's own: a trigger is a KIND,
and `session_start` is the one with a real delivery guarantee, because the
daemon EXECUTES SessionStart itself while it cannot even see a cron. N6 is the
field evidence that the delivery gap is real rather than theoretical.
