# Callout: declare crons your project always wants, and have them re-asserted

**Plan**: 00384
**Audience**: operators

**Claude Code crons cannot persist, and that is not a setting you can change.**
`CronCreate`'s `durable` parameter is documented as having no effect: every job
lives in session memory only, is gone when the session ends, and a recurring
job auto-expires after 7 days regardless. So a cron you want to ALWAYS have is
not something you create once.

A new `persistent_crons` config section lets a project DECLARE the jobs it
wants, and a new `persistent_cron_assertor` SessionStart handler re-states them
at the start of every session so they can be re-created.

```yaml
persistent_crons:
  enabled: true
  jobs:
    - id: nightly-audit
      schedule: "23 3 * * *"      # 5-field, local time
      description: "What this job is for"
      enabled: true
      prompt: |
        What to do when it fires.
```

**It states what you DECLARED — it does not report what is missing.** The
daemon cannot read Claude Code's session memory, so it has no way to know which
jobs are already running, and the advisory is worded to never imply otherwise.
Run `CronList` first and create only what is absent. Creating a duplicate makes
the job fire twice an hour, costing a model turn each time.

**Inertness is one switch.** `persistent_crons.enabled` defaults to `false` and
overrides each job's own `enabled` flag, so turning the whole mechanism off is
a single reliable action rather than an audit of every declaration. Nothing is
declared by default, so this ships silent: a project that says nothing gets
nothing, and the handler stays quiet.

**Schedules are validated at config load.** A schedule that is not a 5-field
cron expression is rejected when the config is read, rather than becoming a job
that silently never fires — which you would otherwise discover by noticing work
that did not happen.

**Pick an off-`:00` minute** where the task allows it. `23 * * * *` beats
`0 * * * *`; every project that asks for "hourly" and gets `0 *` lands on the
API at the same instant.

**The 7-day expiry still applies to the created job.** Re-assertion at session
start is what makes that survivable: a new session re-establishes the
declaration, so the ceiling only bites a session that runs for more than a
week without restarting.
