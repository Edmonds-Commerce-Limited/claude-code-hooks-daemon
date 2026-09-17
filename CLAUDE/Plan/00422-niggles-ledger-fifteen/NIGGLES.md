# Plan 00422 — Niggles

The full write-up for each entry in ledger fifteen. `PLAN.md` carries the
status and the tasks; the reasoning, evidence and candidate remedies live here,
because they are findings rather than plan state.

The first four entries are inherited from ledger fourteen
([00419](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)), which closed with
eleven of its fifteen entries terminal and these four not. Each carries its
original number, the reason it failed that ledger's closing criterion, and its
evidence in full — a re-filed entry that summarises itself is a re-filed entry
nobody can act on.

### N1 — the `Priority` constants are not the numbers a fresh install ships

**Re-filed from [00419 N8](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md).**
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

**Re-filed from [00419 N11](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md).**
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

**RESOLVED by (1)**, scoped to `lint_on_edit.options.exclude_paths` rather than
the project-wide `daemon.exclude_paths` — the latter would exempt the directory
from every guard including `sensitive_content`, which is a far larger act than
the noise being fixed.

**Remedy (1) as WRITTEN above was a no-op, and shipping it verbatim would have
looked like a fix.** These globs are FULL-matched (`_glob_to_regex` in
`utils/path_exclusion.py`), so a bare `untracked/` compiles to
`(?:.*/)?untracked/` and matches the directory path itself — never a file
inside it. Measured against the real matcher:

```
'untracked/'       -> False
'untracked/**'     -> True
'/untracked/**'    -> True
'untracked'        -> False
```

The shipped pattern is `/untracked/**`: the `**` reaches the files, and the
leading `/` anchors to the repo root so a nested `sub/untracked/` elsewhere is
not silently exempted as well.

**Verified in both directions, by writing the file rather than by reasoning.**
The same lint-failing bytes that were denied under `R-LINT-FAILURE` twice were
written again after the restart and drew no block. Confirmed still linted:
`src/**`, `tests/**`, `CLAUDE/**`, and `sub/untracked/**`.

### N3 — a committed future-dated entry makes the journal permanently uncorrectable

**Re-filed from [00419 N12](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md).**
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

**MEASURED, and it changes this entry's basis. The nominated regression file
carries 11 ordering regressions, and only ONE is the future-dated case.** Run
against `00419-Journal-26-09-16.md`:

```
entries=20 regressions=11
  10:50 after 11:18   <- the future-dated correction this entry is about
  10:53 after 11:18       the other ten are a different cause entirely
  10:40 after 11:18
  10:55 after 11:18
  11:05 after 11:18
  10:59 after 11:20
  10:20 after 11:20
  10:35 after 11:20
  10:45 after 11:20
  10:50 after 11:20
  10:58 after 11:20
```

Three agents' streams were merged into one day-file, so the clock resets at
each join. That is the dominant cause, and it is not what either remedy
addresses.

**So this entry's own closing criterion is unreachable.** It says "if the
advisory still fires on that day-file afterwards, the remedy did not work" —
but 10 of the 11 findings survive any future-dated exemption. The criterion
must be restated as eliminating the SPECIFIC finding `10:50 after 11:18`, or
this entry can never close.

**Remedy (1) is additionally not implementable at SWEEP stage.** It asks the
ordering check to ignore entries out of order only with respect to entries "the
file itself flags as future-dated" — but nothing in the file carries a
machine-readable flag (00419's correction is prose in a `finding` entry), and
future-datedness cannot be recomputed retrospectively: every entry in a
2026-09-16 file is in the past when a sweep reads it. The information needed
existed only at the moment of writing, which is exactly why
`journal-entry-future-dated` is EDIT-only.

That leaves remedy (2) as the only implementable one — **and it is bigger than
this entry assumed**. A `correction` category means editing the entry grammar
in `_JOURNAL_TEMPLATE_.md`, which exists in two copies, one of them under
`install/templates/` and therefore shipped to every client. Whether that
reaches the "not owner-gated" bar is now a live question rather than a settled
one, and it is the same shape as the template question Plan 00427 puts to the
owner for issue #45.

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

**Re-filed from [00419 N13](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md).**
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

### N5 — the v3.65.0 release reviews' NON-defects had no durable home

**Found**: after v3.65.0 shipped, while a later session was doing unrelated
work. Four reviewer agents took the `v3.64.0..HEAD` diff apart by subsystem and
returned 14 defects and roughly 20 non-defects. Every DEFECT was fixed before
the tag, which is the rule working. The non-defects were reported inline to the
coordinator and written to `untracked/agent-reports/` — and `untracked/` is
gitignored (`.gitignore:200`), so `git ls-files untracked/agent-reports/`
returns nothing. The container is ephemeral. The findings were one restart from
gone, and nothing would have reported their absence.

**The reports are now in `release-reviews/` beside this file**, verbatim, so the
evidence survives without being re-derived. They are the primary record; the
table below is an index, not a replacement. Their DEFECT sections are closed —
all fourteen shipped fixed in v3.65.0 — so only the non-defect sections are
live.

| #   | Where                                            | The finding                                                                                                                                                                      |
| --- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| a   | `CLAUDE/HANDLER_DEVELOPMENT.md:506`              | The 0-9 band says no built-in ships there; four now do. An author following it puts a Stop handler at 10+, after the terminal catch-all, and it is silently unreachable          |
| b   | `stop/cron_stop_enforcer.py`, subagent twin      | `matches()` and `handle()` each re-parse the whole config, uncached; measured 81.5 ms median per load, ~165 ms per Stop on this repo's config                                    |
| c   | `stop/teammate_reap_advisor.py:59-62,137-147`    | `_should_advise` and its two constants are a verbatim copy of `background_process_tracker`'s; both share an unlocked eviction that can `KeyError` under the dispatch thread pool |
| d   | `stop/__init__.py:11`                            | Names `cron_stop_enforcer` as priority 8; it is 7, and 8 is taken by `release_blocker`                                                                                           |
| e   | `utils/host_identity.py:258-268`                 | The documented four-rung ladder short-circuits instead of falling through to `/etc/hosts`; defensible, but the code and the docstring disagree                                   |
| f   | `tests/.../test_cron_stop_enforcer.py:201`, twin | Both assert against the SHIPPED priority, not the effective one, so a handler at 12 passes while being shadowed in this very repo                                                |
| g   | `utils/cron_enforcement.py:147-165`              | A `session_crons` prompt that is nothing but a truncation marker matches any declared job on the same schedule; fails in the ALLOW direction                                     |
| h   | `utils/markdown_links.py`                        | Imports `plan_qa.model`, contradicting its own docstring and making `docs_qa` transitively depend on `plan_qa`                                                                   |
| i   | `daemon/background_harvester.py`                 | `tree_pgids` is not filtered against `exclude_pgids`, so a suggested `kill --` can name the protected group                                                                      |
| j   | `docs_qa` `pointer_resolves._run_sweep`          | No dedupe — one repeated link prints five identical findings; the plan-QA twin dedupes                                                                                           |
| k   | `plan_qa` relocation messages                    | Assert "archived" for any number-resolved target, including a LIVE plan reached by a wrong path                                                                                  |
| l   | `plan_link_resolves` vs `pointer_resolves`       | Only one has the repo-root-relative fallback, so the two subsystems answer the same link two different ways                                                                      |

**Why it is a niggle rather than a defect.** Nothing here is broken in a way a
user hits today; (a), (f) and (g) are the ones with teeth, and each is a guard
that would fail quietly rather than loudly. The finding that matters most is the
PROCESS one: "Review Early, Never Drop Findings" was honoured for defects and
not for non-defects, and the gap was invisible because the reports existed — on
a path nothing durable reads.

**Candidate remedies**, cheapest first:

1. Work the table. Most rows are one-line fixes with an obvious owner; (a), (d)
   and (f) are documentation or test corrections that need no decision at all.
2. Make the loss impossible rather than noticed: have a review dispatch declare
   a TRACKED report destination by default, so a reviewer's evidence lands
   somewhere `git` can see without the coordinator remembering. The dispatch
   contract already names `untracked/agent-reports/` as its fallback, which is
   precisely the gitignored path this entry is about.
3. Nothing for the table, on the grounds that a release that shipped with its
   defects fixed did the important half. This loses (a), which is a live trap
   for the next person to add a Stop handler.

Remedy (2) is owner-gated — it changes what `dispatch_declaration` recommends
to every client project, not just this one.

### N6 — a worktree cannot run the acceptance release gates, and says the wrong reason

**Found**: during Plan 00424, running `llm_qa.py all` inside a worktree created
by `scripts/setup_worktree.sh`. Ten tests ERRORED at setup — the five
`test_playbook_harness.py` cases, three `test_stop_hook_hard_block.py` and two
`test_tool_use_error_recovery.py` — alongside `smoke_test` reporting 0/3. Every
one of them passes on `main`.

**Two separate faults, and the first hides the second.**

**Fault 1 — the socket path is one byte too long.** A Unix socket path is capped
at 108 bytes. The worktree's default is 109:

```
/workspace/untracked/worktrees/worktree-issue-42-remote-docs-add-overwrite/untracked/daemon-<hash>.sock
```

The daemon notices, prints `Socket path too long ... Using /tmp for runtime files`, and starts successfully — in `/tmp`. The acceptance gates look for a
live socket UNDER `untracked/`, find none, and report `Daemon not running — no live socket found under untracked/. Start it with: ./bin/hooks-daemon restart`.
That instruction cannot work: restarting puts the socket back in `/tmp` for the
same reason. The diagnosis names the symptom and hides the cause, and the
remedy it prints is the one thing guaranteed not to help.

Nothing warns at creation time. `setup_worktree.sh` ends with `=== Worktree Ready ===` and even suggests `./bin/hooks-daemon restart` as the verification
step. The length depends on the branch name, so a short name works and a
descriptive one silently does not — the failure is a property of what you
called your branch.

**Fault 2 — the playbook harness stalls in a worktree anyway.** With
`CLAUDE_HOOKS_SOCKET_PATH` pointed at a 91-byte path under `untracked/`, the
socket resolves and the tests start: four of the five playbook cases pass, then
`test_every_executable_probe_matches_its_expected_decision_and_reason` hangs.
Measured: 18 minutes with no progress, the daemon logging `Received empty request` every ~16 seconds and no probe traffic at all, so it is not slow — it
is waiting. On `main` the same five cases pass in **14.3 seconds**.

**Why it is a niggle.** Nothing is wrong with the shipped product; the cost is
that the worktree workflow this project mandates for sub-agent work cannot
verify its own blocking release gates, and the reason it gives is false. An
agent that trusts the message restarts the daemon in a loop.

**Candidate remedies**, cheapest first:

1. Have `setup_worktree.sh` measure the resulting socket path and fail loudly at
   creation time, naming the length and the cap, rather than letting a daemon
   fall back silently hours later. It already knows the path it is about to
   create.
2. Have the gate's skip reason distinguish "no socket under `untracked/`" from
   "a daemon is running but its socket is elsewhere, because the path is N bytes
   over the cap" — it can read the daemon's own status.
3. Shorten the default socket filename so the cap is reached only by genuinely
   extreme paths. Cheapest of all, and it narrows rather than closes the class.
4. Investigate fault 2 on its own; remedies 1–3 do not touch it, and it is the
   one that makes the gates unrunnable even once the path is right.

Remedies 1–3 are un-gated. Fault 2 needs diagnosis before a remedy can be
proposed, and this entry deliberately does not guess at one.

**FAULT 1 RESOLVED by (1).** `setup_worktree.sh` now measures the socket path
it is about to produce and refuses BEFORE creating anything, naming the length,
the cap, the excess and how many characters to cut.

**This entry's own arithmetic was wrong, and the correction matters.** It says
the cap is 108 and the path "one byte too long". The limit this codebase
enforces is `_UNIX_SOCKET_PATH_LIMIT = 104` — the macOS-safe value, not Linux's
108 — so the reported path is **5** bytes over, not 1. Measured:

```
limit = 104
 109 over=  5  worktree-issue-42-remote-docs-add-overwrite
 100 over=  0  worktree-issue-44-plugins-examples
  85 over=  0  worktree-plan-00028
```

The middle row is the sobering one: a branch used earlier the same day cleared
the cap by four characters. The margin is far tighter than "extreme paths only".

**Not reimplemented in bash.** The check calls the daemon's own
`prospective_socket_path` / `socket_path_overflow`, which reuse
`_UNIX_SOCKET_PATH_LIMIT`, so the guard cannot drift from the rule it enforces.
`get_socket_path` could not be reused directly: it sniffs self-install mode off
disk and creates the directory as a side effect, so it cannot answer for a
worktree that does not exist yet.

**Verified in both directions, end to end.** The over-limit branch is refused
at 109/104 with nothing created (no directory, no branch); a short name prints
`✓ Socket path fits (79/104 bytes)` and proceeds to `=== Worktree Ready ===`.

**The guard fails OPEN**: if the Python cannot be resolved or the measurement
cannot run, it warns and continues. A broken checker must not block worktree
creation.

**Fault 2 is untouched**, as this entry intended — remedies 1–3 never addressed
it, and the playbook-harness stall still needs diagnosis.

### N7 — the supervisor's effort floor cannot see an effort set from the selector

**Found**: reported by the owner in session, in their own words — "i just
manualy set effort to medium and supervisor forced it back to high". Reproduced
by reading `.claude/ccy/claude-supervise.py`, which is tracked in this
repository.

**The manual-effort latch works; the thing that feeds it has a blind spot.**
`_manual_effort_active` is honoured exactly as designed — when it is set,
`decide_once` picks `target = None`, so neither the per-model floor nor the
downgrade `xhigh` floor fires (`claude-supervise.py:3991-3999`). The latch is
set only by `note_manual_effort_command` (`:3816`), which is fed from
`take_effort_submitted`, which is fed from `_buffer_command_arg(_EFFORT_COMMAND)`
at `:769`.

`_buffer_command_arg` (`:843-856`) returns `None` when the line is a bare
`/effort` with no argument. Its own docstring says why: "a bare `/effort` with
no level opens Claude Code's own selector and names nothing this class can
read."

So the two ways a human sets effort are not equivalent:

| How the human sets it                    | Latch set? | Next tick                      |
| ---------------------------------------- | ---------- | ------------------------------ |
| `/effort medium` typed with the level    | yes        | honoured, sticky for the spell |
| `/effort` then picking from the selector | **no**     | floor injects the level back   |

The selector is the discoverable route — it is what `/effort` alone does — so
the failing path is the one a human is most likely to take. The supervisor then
looks like it is overriding a deliberate choice, because from its side no choice
was ever made.

**Why it is a niggle rather than a plan.** The mechanism is understood and the
diagnosis needs no further work; what is missing is a decision about which
signal to read, and that is the owner's to make.

**Candidate remedies**, cheapest first:

1. Treat an OBSERVED effort drop that the supervisor did not itself inject as a
   manual set, and latch on it. This reads the outcome instead of the keystroke,
   so it covers the selector, a config change and any future route at once. The
   risk to check first is whether the sidecar's post-injection reporting lag
   (`:1397`) could make the supervisor's own injection look human.
2. Latch on the bare `/effort` submission itself — the recognizer can see the
   command was submitted even when it cannot see the level — and read the level
   from the next effort reading rather than from the line.
3. Leave the behaviour and document it, so the floor is at least predictable:
   "type the level, or the floor will put it back."

Remedy 1 is the only one that closes the class rather than the instance.
Remedies 1 and 2 both need the owner's call on whether an unexplained drop
should be trusted as human, which is the same judgement the downgrade logic
makes deliberately in the other direction at `:3975-3989` — there, an
*unattributed* change is explicitly NOT acted on. That asymmetry is the decision,
and this entry does not pre-empt it.

**A REMEDY 4 THIS ENTRY MISSED — the hook payload already carries the level.**
Found while measuring something else entirely (Plan 00423's MAIN/SUB
dogfooding), from a captured `SubagentStop` payload:

```
"effort": {"level": "medium"}
```

Every `Stop`/`SubagentStop` the daemon receives carries the EFFECTIVE effort
level, whatever route set it. That reframes the entry: all three remedies above
are attempts to infer the level from the ACT of setting it — a keystroke the
selector never produces — and the daemon is simply handed the RESULT.

Reading the state instead of the act makes the selector path and the typed path
indistinguishable, which is precisely what "closes the class rather than the
instance" means here, and it does so without the risky inference remedy 1 needs.

**It does not settle the owner's question, and should not be read as doing so.**
The open judgement is whether an unexplained change counts as human, and the
payload answers "what is the level now?", not "who set it?". But remedy 1's
specific risk — the sidecar's post-injection reporting lag making the
supervisor's own injection look human — is avoidable here, because the
supervisor knows what it injected and can compare against an authoritative
reading rather than a drop it inferred.

Not verified: whether the supervisor process can see this payload at all, or
whether a daemon-side handler would have to relay it. That is the next check
before this becomes a candidate rather than an observation.
