# Context — Plan 00139: Failsafe Recovery Cron

## The problem

Long-running, multi-hour plan executions get **silently stalled by external
factors that are not the agent's fault and not a human-input block**:

- **Server-side Claude API flakiness** (e.g. `529 Overloaded`, transient 5xx,
  network failures) that aborts a turn mid-work.
- **Rate limits** hit during bursty tool use.
- **5-hour usage limits** on large-scale projects — the session simply cannot
  continue until the window resets.

When any of these fire, the agent stops. Nobody told it to stop; the work is
not complete; it is not blocked on the human. But it just sits there idle until
a human happens to notice and pokes it. On a large project this can waste hours.

## What we want

A **failsafe recovery cron** — an hourly scheduled prompt that acts as a safety
net. When it fires (only while the REPL is idle), it tells the agent:

> Any work that was paused for **any reason other than being blocked on human
> input** must be resumed and carried to completion.

It is **NOT a heartbeat**. The distinction is critical:

- The agent **must not** regard the cron as a pacing mechanism and **wait** for
  it between units of work. Doing so is an **own goal** — it would convert a
  recovery net into an artificial hourly throttle.
- Work proceeds **at full speed** until an external factor blocks it. The cron
  only matters when something has already gone wrong.

## Today's specific trigger

On 2026-06-23 the server-side Claude API was very flaky (repeated `Overloaded`
responses — one even knocked out an Opus doc-review sub-agent during the
v3.26.0 release). That is the acute case. The chronic case is hitting 5-hour
usage limits on big builds. An hourly recovery cron would get things moving
again automatically after each such interruption.

## Origin

User directive (verbatim intent):

> we're going to promote the concept of prompting claude to create cron loops
> whenever executing plans. once a plan is created (so perhaps we hook into plan
> write?) then we prompt claude to create a cron. this is NOT a heartbeat cron -
> this IS a failsafe recovery cron. The recovery cron message should be clear
> that any work that is paused for any reason other than being blocked on human
> input must be resumed. It is to recover from external factors such as API
> failures, rate limits, usage limits etc. The cron should be hourly. does the
> hooks daemon have any ability to know what crons claude might already have set
> up? today is a specific case - the server side claude API has been very flakey
> today. But more generally - when doing very large scale projects it possible
> to simply hit 5 hour limits. the agent MUST NOT regard the cron as a heartbeat
> and actually wait for the cron - that is an own goal.

## Investigation findings (cron introspection)

Answering "does the hooks daemon have any ability to know what crons claude
might already have set up?":

- Claude Code exposes `CronCreate` / `CronList` / `CronDelete` tools to the
  agent (the daemon cannot call these — they are agent-side tools).
- `CronCreate(durable: true)` **persists to `.claude/scheduled_tasks.json`**;
  `durable: false` (the default) is **in-memory only**, lost on session exit.
- `.claude/scheduled_tasks.json` is **gitignored** (`.git/info/exclude`:
  `**/.claude/scheduled_tasks.json`).
- Recurring crons **auto-expire after 7 days** (fire once more, then delete).
- Crons fire **only while the REPL is idle** (never mid-turn — so they cannot
  interrupt active work).

**Conclusion:** the daemon CAN introspect **durable** crons by reading
`.claude/scheduled_tasks.json` directly (a normal file). It CANNOT see
**in-memory** crons except by observing `CronCreate`/`CronList`/`CronDelete`
tool calls as hook events within a session. Therefore daemon-side dedup
("don't advise creating a recovery cron if one already exists") is only
reliable when the recovery cron is **durable**.

**Decision (2026-06-23):** despite the above, the user's direction is to create
crons **non-durable** — durable crons are experienced as unreliable and would
defeat the handler's purpose (ensure a cron runs *during execution* and is
*cleaned up on completion*). So we do NOT rely on disk dedup; instead the
handler tracks reminders in-session (cooldown) to avoid context spam, and the
agent uses `CronList` to avoid creating duplicates. See `PLAN.md` → Decisions.

## Mechanism constraint

The daemon **cannot create a cron itself** — `CronCreate` is an agent-side
tool. So the daemon's role is **advisory**: on plan creation it injects guidance
telling the agent to create the failsafe recovery cron (idempotently). The
agent performs the actual `CronCreate` call.

## Related existing handlers

Plan-lifecycle handler cluster the new work sits beside:

- `plan_workflow` (PreToolUse, advisory) — guidance when creating plan files
- `plan_number_helper`, `validate_plan_number` (just hardened in Plan 00138)
- `plan_completion_advisor` (advises moving completed plans)

The new recovery-cron advisor is a sibling — most naturally a **PostToolUse**
handler (fires *after* a plan is created), since the trigger is "once a plan is
created".
