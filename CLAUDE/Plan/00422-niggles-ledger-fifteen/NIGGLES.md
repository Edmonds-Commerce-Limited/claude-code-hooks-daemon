# Plan 00422 — Niggles

The full write-up for each entry in ledger fifteen. `PLAN.md` carries the
status and the tasks; the reasoning, evidence and candidate remedies live here,
because they are findings rather than plan state.

The first four entries are inherited from ledger fourteen
([00419](../00419-niggles-ledger-fourteen/NIGGLES.md)), which closed with
eleven of its fifteen entries terminal and these four not. Each carries its
original number, the reason it failed that ledger's closing criterion, and its
evidence in full — a re-filed entry that summarises itself is a re-filed entry
nobody can act on.

### N1 — the `Priority` constants are not the numbers a fresh install ships

**Re-filed from [00419 N8](../00419-niggles-ledger-fourteen/NIGGLES.md).**
**Why it failed ledger fourteen's closing criterion**: the remedy is recorded
and OWNER-GATED, and unbuilt. Nothing about it was decided or deferred by
argument; the question was simply never put.

**Found**: while preparing the v3.65.0 config-changes manifest. A sub-agent
reported `Priority.HOST_HOSTNAME = 6` against a template shipping
`priority: 7`, and called it a class-versus-template mismatch introduced by
Plan 00411. Checking it rather than taking it at face value gave a different
and larger answer: the whole `status_line` block diverges, and has for far
longer than that handler has existed.

| Segment                 | `constants/priority.py` | `daemon/init_config.py` template |
| ----------------------- | ----------------------- | -------------------------------- |
| `git_repo_name`         | 3                       | 5                                |
| `environment_indicator` | 4                       | absent                           |
| `account_display`       | 5                       | 6                                |
| `host_hostname`         | 6                       | 7                                |
| `model_context`         | 10                      | 10                               |

**Nothing misbehaves today, and that is the trap.** Relative order is preserved
across the divergence, so every segment renders where its author intended and
no test, no QA check and no user report can see a problem. The defect is
latent: `Priority.HOST_HOSTNAME`'s own comment states an intent ("beside the
environment indicator"), and `environment_indicator` is not in the template at
all, so the constant documents a relationship a fresh install cannot have.

**Why it is a niggle.** A constant that the shipped default ignores is a
constant that lies about its own authority. Someone re-ordering the status line
by editing `priority.py` — the obvious place, and the place the comments invite
you to reason in — changes nothing for any project that took the default
config. The feedback arrives never, which is the worst latency a change can
have.

It is also an instance of a class this project already names: a second source
of truth for one decision, with no check that they agree. The same shape as
`RETIRED_HANDLERS` being duplicated into `init_config.py`, and as
`get_default_enabled()` being duplicated there and welded by
`test_default_enabled_template_consistency.py` — which is the precedent for the
remedy, because that test exists precisely because the same duplication bit
once already.

**Candidate remedies**, cheapest first:

1. Extend the existing `test_default_enabled_template_consistency.py` idea to
   PRIORITIES: assert every handler the template names ships the priority its
   `Priority` member declares. Cheap, and it fails red today.
2. Generate the template's priority values from the constants, so the
   duplication stops existing. Better, and larger — the template is a
   hand-maintained string with comments per line.
3. Nothing. The current state: the two agree by luck and stay agreeing only
   while nobody edits either.

Remedy owner-gated — (1) makes a currently-silent divergence loud across the
whole template, which may surface more than the status-line block and is a
scope decision rather than a bug fix. **That is the entire gate**: the owner
question is whether the test's blast radius is the whole template or only the
`status_line` block, and the divergence itself needs no further investigation.

### N2 — the linter runs on gitignored scratch output

**Re-filed from [00419 N11](../00419-niggles-ledger-fourteen/NIGGLES.md).**
**Why it failed ledger fourteen's closing criterion**: the remedy is chosen,
explicitly NOT owner-gated, and nobody built it. This one has no argument
against it on record at all — it was simply never done.

Extracting the embedded python rung from `init.sh` into
`untracked/scratch/rung.py` to compile-check it tripped `R-LINT-FAILURE` on
`UP041` — in code that is not mine, in a file that is gitignored, disposable,
and was never going to be committed.

`untracked/` is the project's own sanctioned scratch location:
`project_containment` actively pushes working notes there, and `pipe_blocker`
names it as the supported way to capture output. So the guards disagree with
each other about what that directory is for — one directs you to it, another
lints what you put in it.

**Verified while closing ledger fourteen, and it is still true**: no
`exclude_paths` entry covers `untracked/`. The only two `exclude_paths` keys in
`.claude/hooks-daemon.yaml` are the ones scoping `sensitive_content` and
`secret_file_guard`; `lint_on_edit` is configured with `enabled` and `priority`
and no `options` block at all, and there is no project-wide
`daemon.exclude_paths`. So remedy (1) below is not "already half done" — the
exclusion does not exist in any form.

**Why it is a niggle rather than a bug.** Nothing broke; the write landed and
the report was accurate about the code it read. The cost is a false signal at
the exact moment a scratch file is being used as a throwaway probe, which is
when the reader is least interested in its style.

**Candidate remedies**, cheapest first:

1. Add `untracked/` to `lint_on_edit`'s `exclude_paths` (or the project-wide
   `daemon.exclude_paths`). One line, and it matches how every other guard
   already treats that directory.
2. Nothing. Accept the noise on the grounds that a scratch file containing real
   code is still code — which is the argument against, and it is weak here,
   because the file is gitignored and cannot reach review.

Not owner-gated: this is a scope question about one project's own exclude list,
and remedy (1) turns nothing off for any file that can reach history.

### N3 — a committed future-dated entry makes the journal permanently uncorrectable

**Re-filed from [00419 N12](../00419-niggles-ledger-fourteen/NIGGLES.md).**
**Why it failed ledger fourteen's closing criterion**: two remedies are
recorded, neither is owner-gated, and neither was chosen or built. **Its
advisory is still live**, against ledger fourteen's own day-file
`00419-Journal-26-09-16.md`, and ledger fourteen closed saying so rather than
suppressing it.

Found by hitting it, in that plan's own day-file. Three rules meet and cannot
all hold at once once a future-dated entry is committed:

- `journal-append-only` — a correction is a NEW entry at the BOTTOM, never a
  rewrite.
- `journal-entry-ordering` — times increase down the file.
- `journal-entry-future-dated` — a timestamp ahead of the clock is wrong.

Correcting a future-dated entry means appending an entry whose HONEST timestamp
is numerically EARLIER than the wrong ones above it. So the correction is
reported out of order:

```
[advise] journal-entry-ordering: entries are out of chronological order:
`10:50` appears after `11:18`
```

The only ways to silence it are to move the correction out of the append
position (violating append-only) or to stamp it later than the entry it
corrects (perpetuating the false reading). **There is no legal move that
satisfies all three.**

**Why the remedy is not simply "fix the file".** The journal is APPEND-ONLY and
the offending entries have already reached history, so the state that produces
the finding cannot be edited away — not by this ledger, not by any later one.
Any real remedy has to change what the CHECK considers a finding; the file is
not a candidate for change. That is also why the live advisory against 00419 is
the regression case for whichever remedy is built: if the advisory still fires
on that day-file afterwards, the remedy did not work.

**Both advisories are ADVISE, so nothing is blocked** — this costs a confusing
report, not a wall. That is why it is a niggle and not a bug.

**Candidate remedies**, cheapest first:

1. Teach `journal-entry-ordering` that an entry which is out of order *only*
   with respect to entries the file itself flags as future-dated is not a
   finding. Narrow, and it fires exactly where the contradiction is real.
2. Give a correction entry an explicit grammar (e.g. a `correction` category)
   that `journal-entry-ordering` exempts. More honest to read, and it makes the
   correction legible as a correction rather than as another entry.
3. Nothing. The ordering advisory is noise in a rare case, and the day-file
   still reads correctly to a human.

Not owner-gated: (1) and (2) both narrow an advisory that is firing on a state
the other two rules force into existence, and neither weakens any gate.

**The upstream cause is worth separating from the remedy.** The entries only
became uncorrectable because they were appended with a `cat >> … <<'EOF'`
heredoc, which is not seen by the Write/Edit-time guards — CLAUDE.md states
exactly this ("a Bash write that drew no complaint is NOT a write that passed
those checks"). The identical mistake in plan 00411's journal went through
`Write` and was caught and fixed *before it landed*, seconds apart, in the same
session. `journal-entry-future-dated` is also deliberately EDIT-only (a batch
scan meets the entry when the append-only rule forbids acting on it), so a
heredoc append is not caught late either — it is caught never.

### N4 — a cron cannot be both cancelled for a session and declared in config

**Re-filed from [00419 N13](../00419-niggles-ledger-fourteen/NIGGLES.md).**
**Why it failed ledger fourteen's closing criterion**: the conflict was
surfaced for a ruling in the same session it was found, the remedy is recorded
and OWNER-GATED, and no ruling has been given.

**Found**: by obeying the owner. The instruction was to cancel the `issue-sdlc`
cron, and `CronDelete` removed it. The next `Stop` BLOCKED.

`cron_stop_enforcer` (Stop, priority 7 — `.claude/hooks-daemon.yaml:970-972`)
compares the session's `session_crons` against every job declared under
`persistent_crons`, and `issue-sdlc` is declared there
(`.claude/hooks-daemon.yaml:1129-1144`). A declared job the session does not
have is precisely the state that handler exists to refuse, and it refused it
correctly.

**So a session-scoped cancellation is unexpressible.** There are two moves and
each fails the other's test: obeying the owner fails the stop gate, satisfying
the stop gate disobeys the owner. The cron was re-created to clear the block —
which restored the very thing that had just been asked to stop — and the
conflict was surfaced for a ruling rather than settled by whoever happened to
be standing in front of it.

**The knob that does exist is a different and larger act.** Removing the
`issue-sdlc` job from `persistent_crons`, or setting `enabled: false` on it,
genuinely stops the enforcement, because enforcement is downstream of the
declaration. But that is committed config: it stops the job for every session,
on every branch, until someone puts it back. "Cancel it for now" and "we no
longer run this job" are different decisions with different blast radii, and
only the second one has a spelling.

**THE CLASS, and it now has THREE SIGHTINGS.** 00419's N3 (the two plan-close
gates), 00419's N12 — this ledger's N3 above (the three journal rules) — and
this entry: a gate that no legal sequence of moves can satisfy. Three
occurrences in three unrelated subsystems is a pattern, not a coincidence. The
shape is identical each time: a guard judging a STATE correctly, in a workflow
where that state is a legitimate INTERMEDIATE (N3's all-ticked body) or a
legitimate TEMPORARY (a journal correction, a paused cron). The guard is right
about the state and wrong about the moment.

00419 N3's remedy is the precedent worth copying, because it is the only one of
the three that has been fixed: it did not relax the check, it moved the check
to the stage where the state is settled. **A fourth sighting should be filed
against this class, not as a fresh niggle** — see PLAN.md Task 1.5.

**Candidate remedies**, cheapest first:

1. A session-scoped pause the enforcer honours, recorded the way the Stop
   handler already records "blocked only on human input" — a marker the daemon
   writes and expires on its own, not a config edit. It gives "cancelled for
   now" a spelling, and leaves the declaration intact so the next session
   re-creates the job.
2. Have the enforcer's deny text name the config knob and say plainly that a
   session-scoped cancellation has no spelling, so whoever is blocked learns the
   wall is real instead of inferring it from two failed attempts. The N3-(3)
   shape: cheapest, and weakest, because it makes an unsatisfiable gate
   learnable rather than satisfiable.
3. Nothing. An owner instruction to cancel a declared cron is rare, and the cost
   is one blocked stop plus a re-creation.

Remedy owner-gated — (1) hands a session the ability to switch off a guard the
project itself declared, which is a decision about that guard's authority rather
than a bug fix, and the thing it would be overriding is the owner's own
instruction.
