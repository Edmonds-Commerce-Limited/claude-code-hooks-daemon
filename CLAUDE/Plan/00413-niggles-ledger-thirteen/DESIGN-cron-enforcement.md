# Cron delivery and duplication: the design input so far

Supporting document for ledger [00413](PLAN.md) N6. Nothing here is decided —
this is the owner's direction plus the facts found while answering it, kept out
of PLAN.md so that document stays a lean spec.

## The defect being designed around

`persistent_cron_assertor` cannot create a Claude Code cron; no API exists for
it. Its entire contribution is to PRINT "run `CronList`, then `CronCreate` for
anything missing" and rely on the agent to act. If that text is skimmed, the
declared cron never exists — and nothing reports the difference, because
`CronList` is session memory the daemon cannot read. "Declared and running" and
"declared and absent" are indistinguishable from outside.

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

## Where this belongs longer-term

Plan [00412](../00412-jobs-recurring-work-and-security-review/PLAN.md) already
carries the structural answer, and it is the owner's own: a trigger is a KIND,
and `session_start` is the one with a real delivery guarantee, because the
daemon EXECUTES SessionStart itself while it cannot even see a cron. N6 is the
field evidence that the delivery gap is real rather than theoretical.
