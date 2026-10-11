# Owner sheet B, 2026-10-11: the four plans you did not rule on

This re-puts the "Other plans" items from [OWNER-QUESTIONS-261011.md](OWNER-QUESTIONS-261011.md) under your standing
guidance in [OWNER-RULINGS-261011.md](OWNER-RULINGS-261011.md): clear winners are decided by the coordinator, and only
things that need your hands or your ownership reach you, each with enough context to answer from this sheet alone.

Of the nine items, six are decided by the coordinator, three are yours to apply, and none needs a decision from you.

## Decided by the coordinator

**1. The model experiment (Plan 00470, "always-on session", Task 4.3): dropped, not run.**
The plan proposed running the coordinator session for a while on Sonnet and for a while on Opus, with Opus sub-agents,
and comparing cost per tick, guard denies and triage or verdict errors, for you to pick from the record. Decision: do not run it.
A fair comparison needs days of matched running on a quiet host with usage headroom; today you ruled the dev host is
too loaded for the full suite, and on 2026-10-09 the account hit its hard limit (three agents died on it), so the
record would be noise.
Model choice also lives in Claude Code's own settings and the per-agent `model:` pins, which already exist and are not
to be fought. Next: the task is closed as declined, with this reason, and reopens only if quiet capacity appears.

**2. Keeping the prompt cache warm (Plan 00470 Task 4.4, feeding Plan 00452): this plan's part is complete.**
The task was to collect this always-on session's idle-gap profile. Collected (24,075 gaps over 25 days, 2026-09-15 to 2026-10-10). The rest
of the warming work belongs to Plan 00452, which still needs a gap profile from a project paced by a person, because
this one is paced by crons. Next: Task 4.4 is marked done in 00470 and 00452 stays blocked on its Task 2.4, with one
optional action for you in the "Owner to apply" section below.

**3. A usage backstop under your override (Plan 00479, "usage monitor", open question 5, blocking Task 6.2).**
Background: when usage nears the subscription limit the daemon pauses the session; you can override the pause with
`usage-pause clear`. An override written on 2026-10-08 hid a climb from 80% to 100%, and three agents died on the
hard limit from about 22:30 UTC on 2026-10-09. The question was whether anything may pause the session through your
override. Today you separately asked for a 95% single-thread cutoff that blocks sub-agent spawns (issue #104, filed
for later and not yet designed). The coordinator reads that as the answer: the cutoff is the backstop. That reading
is the coordinator's, not yours, and #104 lists override handling as an open design point.
Decision: the override keeps meaning "do not pause me", and the 95% cutoff applies even under an override, so past
95% the main thread keeps working alone and no new sub-agent can be started to die on the hard limit. No full pause
is added under an override. Next: Task 6.2 is built as "the #104 cutoff ignores the override", plus its two small
fixes (the resume tick under an override, and an unreadable override marker that never expires). The related fact
that the seven-day reset time moved is handled technically: the override re-reads the provider's reset time each
tick rather than trusting the one it was written with.

**4. The conformance gap calls (Plan 00484, "DBF conformance", success criterion 3 and Task 3.3).**
Background: the project's own conformance audit found sixteen gaps against the Defence Before Fix specification.
Three of them (G1, G2 and G4) were among your rulings of 2026-10-05 and are closed as you said. The rest were closed
by the coordinator's calls: eight simply fixed through the ledger, G3 fixed, G10 confirmed, G14 reworded to what the
code does, G16 graded at both levels, and G11 done except its tree-sweep `scan` mode, which is deferred to a
follow-up plan (`probe --only` is already done). You said today that the deliberate
limits recorded on the coordinator's judgement are "fine". The same reasoning extends here: every call is a closure
or a correction, where fixing is the default and no gap is being accepted or declared out of scope on your behalf.
The only deferred piece (G11) will be listed in the declaration as a known gap. Decision: the calls stand, success
criterion 3 is reworded to "every gap is closed or listed", and Task 3.3 publishes the declaration from the README.

**5. The full-QA speed outcome (Plan 00500, "full QA timing and speed").**
Background: the full suite took 90+ minutes and reboots killed runs. The plan added timing, made the gate resumable,
and cut the measured hot spots (for example one test file from 520 s to 172 s, another from 129 s to 11 s). The
total wall-clock did not drop measurably, because both runs were on the loaded host where run-to-run noise is about
700 s. The plan asked whether to accept the per-hot-spot savings or run a controlled before/after on a quiet host.
Decision: accept the per-hot-spot savings. A before/after needs two full runs (about 2.7 hours each) on the very host
you ruled today must not run the full suite. When issue #107 moves the full suite to GitHub Actions, its runners give
the quiet-host wall-clock figure for free. Next: the success criterion is recorded as "per-hot-spot savings measured;
total deferred to the Actions runs", and the plan closes.

**6. Who restarts a crashed session (Plan 00470 Task 3.5): decided in substance, yours to apply (item 7 below).**

## Owner to apply

These are settled, but they live in your user settings or on the host, which agents never edit.

**7. Restart loop and host settings for the always-on session (Plan 00470 Task 3.5).**
What it is: today nothing restarts `claude` or its supervisor if they crash while the VM is up; boot restore is
assumed from the fedora-desktop setup but unconfirmed on this host. Recommended, in your infrastructure setup:

- a systemd unit (or shell loop) around ccy with `Restart=always` and a back-off (`RestartSec=30` or more), that
  passes `--continue` on every restart after the first, so crons and context resume;
- `HOOKS_DAEMON_HOSTNAME=github-softwaredev-lifecycle-unattended` (your 2026-10-09 rename, the name the `issue-sdlc` job's host filter matches) in that unit's environment for the SDLC runner session, so its declared
  jobs are selected by host;
- `autoContinueAtUsageLimit: true` in the host's **user** settings (`~/.claude/settings.json`), which Claude Code
  requires there (a project file can only turn it off) and needs v2.1.234 or later.
  Once the unit exists, tell any agent its name and it is recorded in the runbook (RUNBOOK.md section 3).

**8. Bound Claude Code's transcripts (Plan 00470 Task 4.1).**
What it is: Claude Code's own session transcripts under `~/.claude/projects/` are the one unbounded store on the
always-on host (2.9 GB measured, 2.3 GB of it sub-agent transcripts). The daemon must not delete them; Claude Code's
`cleanupPeriodDays` user setting does. Recommended value: `"cleanupPeriodDays": 14` in `~/.claude/settings.json`.
Why 14: a restarted session only needs the most recent transcript, and two weeks is enough for post-incident reading
(the stop-hook inspector and the gap profiling both work on recent days). Claude Code's own default is 30 days, so if
you do nothing the store stays bounded at roughly a month.

**9. Optional: a human-paced transcript for the cache-warming decision (Plan 00452 Task 2.4).**
What it is: deciding whether to send "keep-alive" requests to stop the prompt cache going cold needs to know how long
a person-paced session sits idle. This repository's session is paced by crons, so it cannot say. If you want this
work to move, run `hooks-daemon cache-gaps` once in any project you drive by hand and hand an agent the output path.
If you never do, nothing breaks: the warming work stays parked, which is the plan's deliberate default.

## Questions for you

None. Every item above was either a clear winner or a setting only you can apply. If any decision in the first
section is not what you want, say which number and it is reversed.
