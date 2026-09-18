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

**`/untracked/**` WAS ALSO WRONG, and the verification above is exactly why it
looked right.** Every path I checked was a path I thought of. The one I did not
think of is where this handler's OWN acceptance probes write their fixtures:
`untracked/scratch/acceptance-test-lint-<lang>/` (`scratch_path(_FIXTURE_DIR, ...)` in all ten lint strategies, plus `playbook_harness._PROBE_SCRATCH`). The
exclusion therefore switched `lint_on_edit` off for its eight declared DENY
probes — `matches()` returned False for their own declared input — and the
full test suite caught it:

```
library:PostToolUse/LintOnEditHandler::Python lint - invalid code blocked:
  expected_decision=DENY but matches() returned False for its own declared input
  ... (8 probes: Shell, Python, Go, Rust, Ruby, PHP, Dart, Bash-heredoc)
```

Nothing surfaced this for a whole session: plan QA and docs QA both reported 0
findings over it, because neither runs the acceptance contract. A config change
that disables a guard is invisible to every check except the one that drives
the guard.

**The shipped patterns are now depth-scoped**, measured against the real
matcher before shipping this time:

```
                                                 /untracked/**   scratch/*
untracked/scratch/rung.py            (N2 case)   EXCLUDED        EXCLUDED
untracked/scratch/qa-out.txt                     EXCLUDED        EXCLUDED
.../acceptance-test-lint-python/invalid.py       EXCLUDED        linted
.../acceptance-test-lint-bash/authored.py        EXCLUDED        linted
.../acceptance-test-eslint-bash/authored.ts      EXCLUDED        linted
src/**, tests/**, sub/untracked/**               linted          linted
```

`- "/untracked/scratch/*"`, `- "/untracked/qa/**"`,
`- "/untracked/worktrees/**"`. The boundary is DEPTH: a note written straight
into the scratch directory is exempt, a fixture tree one level down is not,
because a probe that cannot be denied proves nothing.

**The glob dialect cannot express this any other way.** `path_exclusion` has no
negation — `path_matches_globs` returns True on ANY pattern match and
`merge_exclude_patterns` only unions — so "everything under `untracked/` except
the probe fixtures" is not writable. Depth is the only available discriminator.

**Residual, deliberately not fixed here** (see N11): the fixtures live in the
sanctioned human scratch directory at all, which is what forces this coupling.
A dedicated `untracked/acceptance/` root would separate them properly, but that
is library code, ten strategies and every client's docs — a bigger act than the
regression being repaired.

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

**THE LIVE ADVISORY IS GONE, and not because anything was remedied.** Measured
rather than assumed: `plan_qa` now reports 0 findings over the whole tree, while
the cited day-file still carries all 11 ordering regressions in its content.
Both are true because `journal_entry_ordering._live_journal_targets` walks only
plans in the plan ROOT, and 00419 is archived. The exclusion exists for exactly
this entry's reason, stated in its own docstring: `archive-immutability` forbids
editing an archived journal, so a finding there is one nobody is PERMITTED to
act on, and "a permanently unfixable finding trains readers to ignore the
check".

So the entry's restated closing criterion — eliminate the specific finding
`10:50 after 11:18` — was met by ARCHIVING, and every instance of this
contradiction is self-limiting in the same way: it can only be reported while
the plan is live. That is worth knowing before anyone builds a remedy for it,
and it is the third premise in this ledger to expire before its entry did.

**What remains real**: the contradiction still bites inside a LIVE plan's
day-file, for as long as that plan is live.

**Done, un-gated: the remediation no longer opens with the illegal move.** It
began "move the out-of-order entry back to its chronological slot" — precisely
what `journal-append-only` forbids once the entry is committed, offered as the
FIRST instruction, with the legal move second. It now leads with the append,
keeps moving as the narrower case it is (an entry that has not landed yet), and
states plainly that a correction whose honest time is earlier will itself read
as out of order and is still the right move. A reader who cannot act on the
advice is a reader who learns to ignore the check — which is the same argument
the archived-plan exclusion already makes.

**Remedy (2) stays unbuilt and is owner-gated after all.** A `correction`
category is a change to the entry grammar in `_JOURNAL_TEMPLATE_.md`, which
ships to every client; that is a template decision of the same shape Plan 00427
put to the owner, not a ledger fix.

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

**Rows (a) and (d) DONE by Plan 00435, and the table was wrong in a third place
neither row mentions.** The Advisory row read `56-69` against a
`PriorityRange.ADVISORY_MAX` of 73, so four shipped handlers sat in no
documented band at all. All three surfaces agreed with each other and all three
were wrong, because `quote_drift` keeps the two `ssot-quote` copies faithful to
the SSoT and nothing compared the SSoT to the code. There is now a test that
does, with the row-count control that stops a parser matching nothing from
reading as agreement. Row (d)'s `priority 8` is 7, naming what holds 8, and the
skill's paraphrase — which stated a third value, `56-65` — agrees now too.

**Row (c) DONE by Plan 00437, and its mechanism held up under checking.** The
thread pool is real: the daemon is asyncio and owns no pool of its own, but
`server.py` dispatches through `run_in_executor(None, controller.dispatch, …)`
and the default executor is a `ThreadPoolExecutor`, with handlers as
daemon-lifetime singletons. Both copies of the counter now delegate to one
locked `SessionAdviceCounter`, which removes the duplication and the race in
the same move.

**The test needed the same scepticism the finding did.** At CPython's default
5ms switch interval the unlocked shape survived 16 threads of 200 calls with
zero errors — a concurrency test written the obvious way would have passed
against the defect and proved nothing. Driving the switch interval to its floor
with 32 threads of 2000 calls produced 26 `KeyError`s, and the shipped test was
then watched failing against a deliberately unlocked copy of the new class
before it was restored. Worth remembering for the next concurrency finding in
this repository: under the GIL, "it did not raise" is not evidence.

**Row (g) DONE by Plan 00436.** Confirmed exactly as filed: a delivered prompt
of nothing but a truncation marker strips to an empty string, is correctly
identified as truncated, and every declaration on the schedule starts with it —
so any declared job matched, and a cron that was never created was reported as
live. Prefix matching now requires a non-empty prefix.

**Residual, recorded rather than implied**: a delivery whose surviving prefix is
one or two characters is still matched by prefix, and is nearly as weak. It is
left alone deliberately — a minimum LENGTH would be a policy invented here, and
the delivery cap gives no basis for a floor above zero. The empty prefix is the
case that carries no evidence at all; a short one is a different argument and
should be made on its own evidence if it ever costs anything.

**Row (f) is CORRECTED, not built.** The claim is accurate about the unit test:
`CronStopEnforcerHandler().priority < Priority.AUTO_CONTINUE_STOP` compares
against the SHIPPED 15 while this project overrides that handler to 10, so a
Stop handler at 11-14 passes it while being shadowed here. But the CLASS is
already guarded:
`test_stop_chain_terminal_shadowing.py::TestThisProjectHasNotFallenIntoTheTrap`
builds the router from this project's real config file, including
`project_handlers_config`, and fails on anything registered after the handler
that breaks the chain — which is precisely the effective-priority question the
unit test cannot answer. The unit test is a wiring sanity check and its
docstring already points at that module. Nothing to build; the row named the
weaker of two tests as though it were the only one.

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

The three-branch reading that establishes this lives in
[JOURNAL/00422-Journal-26-09-17.md](JOURNAL/00422-Journal-26-09-17.md), in the
`11:00` entry — not duplicated here. The journal is append-only, so it is the
stable home for a measurement; this entry is what interprets it.

The row that matters: `worktree-issue-44-plugins-examples` measured 100 against
the 104 cap. A branch used earlier the same day cleared it by four characters,
so the margin is far tighter than "extreme paths only" implies.

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

### N8 — the socket-path guard fails open exactly where it is needed

**Found** by watching it not fire, hours after shipping it. N6 fault 1's remedy
adds a pre-flight to `setup_worktree.sh` that refuses an over-cap socket path
at creation. A sub-agent then created a worktree whose socket path is **130
bytes against the 104-byte limit — 26 over — and the guard allowed it.**

**Why.** The guard resolves a Python to call the daemon's own measurement
helpers, and deliberately fails OPEN if it cannot: "a broken checker must not
block worktree creation". Measured in the failing environment:

```
resolve_venv: no usable venv found under <fresh worktree>/untracked/
RESOLVE_FAILED -> guard fails open
```

A worktree created from the MAIN checkout resolves fine, because the main venv
exists. A worktree created from INSIDE another worktree — which is where paths
get long enough to matter — has no venv yet, so the measurement cannot run and
the guard stands down. **It is inert in precisely the case that motivated it,
and healthy everywhere else**, which is the worst possible distribution: it
reports `✓ Socket path fits` on every short path anyone tests it against.

**This is not an argument against failing open.** Blocking worktree creation
because a checker is broken would be worse. The defect is that the check needs
a venv at all, for arithmetic that is two path joins and a length comparison.

**Candidate remedies**, cheapest first:

1. Run the measurement under system `python3`, loading `paths.py` DIRECTLY by
   file path via `importlib.util.spec_from_file_location` — no venv, no
   editable install, and the limit still read from the daemon's own constant.

   **The obvious spelling of this remedy does not work, and the difference is
   the whole point.** `PYTHONPATH=<root>/src python3 -c "from claude_code_hooks_daemon.daemon.paths import ..."` FAILS: importing the
   module by package path executes
   `claude_code_hooks_daemon/__init__.py`, which imports `FrontController` and
   therefore pydantic:

   ```
   ModuleNotFoundError: No module named 'pydantic'
   ```

   `paths.py` itself is stdlib-only, so loading the FILE bypasses the package
   `__init__` and succeeds under bare `python3`, returning `limit = 104` from
   the real constant. Measured both ways before recording this — the first
   version of this entry asserted the `PYTHONPATH` spelling and was wrong.

2. Fall back to the MAIN checkout's resolved Python when the local one fails,
   walking up from the worktree. Works, but couples worktree creation to the
   parent tree's health.

3. Reimplement the arithmetic in bash. Cheapest to write and the one to avoid:
   it duplicates the limit constant, which is exactly the two-copies-one-truth
   shape this session has now hit three times (issue #44, the journal category
   array, and this).

Not owner-gated: it makes an existing guard work as documented and weakens
nothing.

**REMEDIED by Plan 00431**, via remedy (1) as written. The pre-flight now loads
`daemon/paths.py` by file location under the system `python3`, so it needs no
venv and still reads `_UNIX_SOCKET_PATH_LIMIT` from the daemon's own constant.
Fail-open is kept for a missing `python3` or a missing `paths.py`, and each case
now names itself instead of naming the venv.

The RED was reproduced before the fix rather than assumed: the regression test
extracts `preflight_socket_path` from the script and runs it with the venv
resolver stubbed to fail, which is what a nested worktree actually presents.
Against the old code it allowed a 165-byte path; against the new code the live
script refuses one and creates nothing. The set includes the control that would
have caught a guard which simply started refusing everything.

**Cost of the miss, so the priority is honest**: a sub-agent spent a long run
inside that worktree, its acceptance gates and smoke tests failed against a
daemon relocated to `/tmp`, and it reported 4 red QA categories that were
environmental. The guard existing but not firing produced exactly the confusion
it was built to prevent.

### N9 — worktree isolation plus an explicit worktree instruction nests them

**Found** by causing it. A sub-agent dispatched with `isolation: "worktree"`
ALREADY has its own isolated checkout. The brief I wrote then also told it to
run `./scripts/setup_worktree.sh`, so it created a SECOND worktree inside the
first:

```
/workspace/.claude/worktrees/agent-<id>/untracked/worktrees/worktree-j427
```

95 bytes of directory before the socket filename is even appended — which is
how N8's 130-byte path came about.

**Nothing warns.** `isolation: "worktree"` and a worktree-creating instruction
are independently reasonable and mutually invisible: the agent cannot tell that
its cwd is already an isolation worktree rather than a normal checkout, and
`setup_worktree.sh` does not know it is being run inside one.

**Consequences beyond the path length**, all observed in the same run: the
agent's committed work landed on a branch inside a tree the coordinator later
reaped; a recovery attempt started re-porting that work into the outer root;
and the nested tree's QA was graded against a daemon that had silently moved to
`/tmp`.

**Candidate remedies**, cheapest first:

1. Have `setup_worktree.sh` DETECT that it is already inside a worktree
   (`git rev-parse --git-common-dir` differs from `--git-dir`) and refuse, or
   at minimum warn loudly and name the enclosing tree. It already knows enough
   to tell.
2. Fix the dispatch guidance so a brief that names `isolation: worktree` never
   also instructs a worktree creation. Documentation only, and it relies on
   whoever writes the next brief reading it — which is the failure mode here,
   since I wrote this one having just shipped the guard.
3. Nothing. It needs both conditions at once and is rare.

Not owner-gated. Remedy (1) is a refusal added to a script, not a policy
change.

**REMEDIED by Plan 00433**, via remedy (1), refusing rather than warning. A
warning is read by whoever is watching, and the whole point of this entry is
that nobody was. The refusal names the enclosing checkout and prints the command
to run there, so it costs one step rather than an investigation.

Remedy (2) was deliberately NOT taken as well. Fixing the dispatch guidance
relies on the next brief's author reading it — and the brief that caused this
was written immediately after shipping the guard it defeated.

The detection is `git rev-parse --absolute-git-dir` against
`--path-format=absolute --git-common-dir`; they are equal in a normal checkout
and differ in a linked worktree. Both paths are normalised because
`--git-common-dir` answers relatively from a main checkout and absolutely from a
worktree, so an unnormalised comparison would fire everywhere.

The documented CHILD worktree workflow is unaffected — a child is created from
the main checkout — and that is pinned by a control test, not by reasoning.

### N10 — a QA checker's own tests overwrite that checker's real QA artefact

Found while reading the intermediate artefacts of a full `llm_qa all` run.
Three checks showed a failure that the run's final report did not:

```
git_history          passed=false  total_violations=1  refs_scanned=2
skill_references     passed=false  total_violations=1  files_scanned=1
python_var_guidance  passed=false  total_violations=1  files_scanned=1
```

Two named their evidence outright — `/tmp/pytest-of-root/pytest-184/...`,
pytest fixtures deliberately containing the violation their checker hunts. The
third flagged a ref name with `refs_scanned: 2`; this repository has 152 refs
(`git for-each-ref | wc -l`) and the finished run reported `git_history: 0 violations (2418 commits, 152 refs swept)`. A two-ref repository is a fixture.

**Mechanism, confirmed in the code.** `scripts/qa/check_git_history.py:53`:

```python
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "git_history.json"
```

An absolute path into the real checkout, resolved from `__file__`, written
whenever `--json` is passed regardless of `--repo` (line 548). And
`tests/unit/qa/test_check_git_history.py:108` runs the checker against a temp
fixture repo, then reads `_JSON_OUTPUT` — the real repository's artefact. The
test does not merely tolerate the clobber, it **depends** on it. Same shape in
the `skill_references` and `python_var_guidance` test modules.

**Why it is worse than a stale file.** `llm_qa` hands a reader the JSON path
and a `jq` hint as each check's evidence surface (`llm_qa.py:433-437`). After a
full run three of those describe a fixture. Both directions are wrong: a check
that PASSED is left with a fixture FAILURE (what happened, and it cost a
mid-run diagnosis), and a check that FAILED can be left with a fixture PASS,
which **masks a real defect** and is the direction nobody would notice.
Ordering decides which, and the ordering is incidental.

**Candidate remedies:**

1. Give each checker an `--output` argument defaulting to the current constant,
   and have the three test modules pass `tmp_path`. Removes the shared mutable
   global rather than working around it.
2. Guard the guard: a test asserting the checker does NOT write the repo
   artefact when `--output` is given.

Do NOT "fix" this by reordering `llm_qa` so the checks run after the tests —
that makes the corruption deterministic in the masking direction.

**Scope check before building**: three modules are confirmed by measurement.
Every `scripts/qa/check_*.py` with a module-level `_OUTPUT_FILE` and a test
that shells out to it shares the shape; take the inventory as part of the fix
rather than assuming it here.

Not owner-gated: this is a test-isolation defect in this project's own QA
tooling.

**REMEDIED by Plan 00432**, and the scope check earned its keep twice. The
inventory this entry asked for found **ten** affected checkers, not three.

Seven take a scan-target override; the four this entry did not name are
`check_github_urls.py`, `check_security_downgrade_flags.py`,
`check_eacces_safe_predicates.py` and `check_authored_path_stat.py`. They go
unnoticed for the ordinary reason — no test happens to point them elsewhere
today, so the shape is latent rather than firing.

Three more take an override naming an INPUT FILE (`--inventory`, `--corpus`,
`--registry`). I set those aside first as "no scanned directory to report
beside", which was a statement about the FIX shape wearing the clothes of a
statement about the defect. Two of the three still sweep this repository, so the
override changes the DECLARATIONS the sweep is graded against — and "clean
against our registry" is not the fact "clean against a substitute" establishes.
They report beside the file they were pointed at. **The near-miss is the part
worth keeping**: a scope boundary drawn from what was convenient to fix is
indistinguishable, on the page, from one drawn from what is actually affected.

The fix is not remedy (1). `check_sensitive_content.py` had already solved this
for itself, with the reasoning written at its own write site, so the repository
already had a convention: a scoped scan reports BESIDE what it scanned. Adding
an `--output` flag would have been a second convention for one problem. Remedy
(2)'s guard is there, generalised — one parametrised test over all seven,
including the control that a checker which stopped honouring its own override
flag would scan the repository and pass by accident.

The 45 tests across four modules that READ the repository artefact now read the
scoped one, which also makes their assertions about the fixture rather than
about whatever ran last.

### N11 — acceptance probe fixtures live in the sanctioned human scratch directory

Surfaced by N2's second failure rather than found independently, and left
unfixed there deliberately.

Every lint strategy writes its acceptance fixtures to
`untracked/scratch/acceptance-test-lint-<lang>/` via `scratch_path()`, and
`playbook_harness._PROBE_SCRATCH` is `("untracked", "scratch")`. That is the
same directory `project_containment` pushes working notes into and
`pipe_blocker` names as the capture target — so the harness and the human share
one namespace.

The consequence is not hypothetical: any project-level exclusion written for
the human half silently disables the handler's own acceptance coverage, which
is exactly what N2 did. N2's repair works by DEPTH, which is a coincidence of
layout rather than a boundary anyone declared, and nothing stops the next
exclusion re-breaking it.

Plan 00333 put the fixtures in-repo for a good reason —
`project_containment` denies a Bash write named outside the repo root, so
`/tmp` is unavailable. That argues for in-repo and gitignored, not for
*scratch* specifically.

**Candidate remedies:**

1. A dedicated `untracked/acceptance/` root, distinct from `untracked/scratch/`.
   In-repo, gitignored, and no longer colliding with the directory agents are
   told to put working notes in.
2. Declare the coupling instead: a test asserting no configured
   `lint_on_edit` exclusion matches any declared probe's `tool_payload` path.
   Cheaper, and it fails loudly the next time rather than silently.
3. Nothing. N2's depth-scoped patterns hold today.

Remedy (2) is worth doing even if (1) is chosen, because it is the guard that
would have caught N2 at config-edit time rather than a session later.

Owner-gated for (1): it moves a path that ten strategies, the playbook harness
and client-facing docs all name.

**Remedy (2) ALREADY EXISTS, and this entry proposed building it a second
time.** `tests/integration/test_acceptance_contract.py::TestEveryDeclaredInputProducesItsDeclaredVerdict`
drives every declared BLOCKING probe against the real config-injected handler
and fails when the declared verdict does not come back.

Measured rather than read: restoring the N2-breaking `/untracked/**` pattern in
this project's own config turns it red in **1.63 seconds**, naming each probe
individually —

```
library:PostToolUse/LintOnEditHandler::Shell lint - invalid code blocked:
  expected_decision=DENY but matches() returned False for its own declared input
```

— for eight strategies, then green again on restore. It is also strictly
stronger than the proposed test: it is not scoped to `lint_on_edit` or to
`exclude_paths`, so it covers any handler that stops matching its own declared
input for any reason.

The entry's framing is the drift worth keeping. "Cheaper, and it fails loudly
the next time" describes a guard that was already there, already loud, and
already the thing that caught N2 — which the entry SAYS two paragraphs earlier
and then does not connect. A remedy proposed against a defence you have already
cited is a duplicate, and the cost of building it is a second thing to keep in
step with the first.

**Revised: nothing to build here.** What remains is remedy (1), which is
owner-gated, and the ledger is where it waits.

### N12 — the supervisor asset has been red under its own lint gate since v3.65.0

`tests/integration/test_client_owned_asset_lint.py::TestPythonAssetsAreCleanUnderRuffDefaults`
fails on `.claude/ccy/claude-supervise.py`, reporting `ISC004` (unparenthesized
implicit string concatenation in a collection, several sites) and `SIM103`
(return the negated condition directly, `:3578`).

Found incidentally while clearing Plan 00423 Task 3.2's own failures, and
separated from them deliberately: the file is untouched by that work
(`git diff HEAD` empty for it) and its last commit is
`62019300 Release v3.65.0: version bump across the tree`. So this is not a
regression introduced here — the gate has been red on `main` since that
release.

**Why it matters more than the findings themselves.** The findings are
cosmetic. The fact is not: a test that has been failing on `main` across a
release is a test nobody is reading, and the whole point of that gate is that a
DAEMON-OWNED asset deployed into a CLIENT-owned path is clean under the
client's default rule set — a client who runs ruff on their own `.claude/`
tree currently gets our noise. A gate that is already red cannot report the
next thing that breaks it, which is the same failure shape as N8 and as the
three vacuous guards this session has already cost.

**The question worth answering before fixing the lint**: why did a full-suite
run go red at release time without stopping the release? Either the release
pipeline does not run this suite, or it ran and the failure was accepted. The
answer decides whether this is a five-minute lint fix or a hole in the release
gates — and only the second one is worth a plan.

**Candidate remedies:**

1. Fix the six findings and leave the gate alone. Cheapest, and wrong on its
   own — it restores the green without explaining the year the gate spent red.
2. Fix them, then establish which release gate should have caught this and
   confirm it now does, with the check named.
3. Nothing, if the file is deliberately exempt — in which case the exemption
   belongs in the test as a tracked entry with a reason, not as a standing
   failure.

Remedy (2). The lint fix is not the deliverable; knowing why nobody saw it is.

**Verified, and the entry above is wrong about the gate.** The question "why
did a full-suite run go red at release time without stopping the release?" has
an answer nobody expected: it did not go red. The gate is green, and re-running
it is one command.

- `tests/integration/test_client_owned_asset_lint.py` — 9 passed, exit 0, on
  the tree the entry describes. Neither the asset nor the test has changed
  since (`git log` for both stops at `62019300`), so it was green at the
  release too.
- `ruff check --isolated .claude/ccy/claude-supervise.py` — clean. The repo's
  OWN config is clean on it as well; `SIM103` is in `pyproject.toml`'s ignore
  list by name, as a readability preference.
- One ruff on the machine (0.15.11, the single fingerprint-keyed venv), so this
  is not a version disagreement.

The two rule codes are real, and reachable by exactly one selection nobody
runs: `ruff check --isolated --preview --select ISC,SIM` gives `ISC004` at
`:2886` and `:3207` and `SIM103` at `:3578`. `ISC004` is PREVIEW-only — `ruff rule ISC004` says so — so it cannot fire under ruff's defaults at any version,
which is the only thing that gate runs. The entry above reported the output of
a hand-widened selection as the verdict of a named test.

**Both `ISC004` sites are correct as written**, checked rather than assumed,
because that rule exists to catch a MISSING COMMA and a missing comma there
would be a live defect in the supervisor. Both are a deliberate two-line
f-string message inside a returned tuple, split where black put the break.

**Revised remedy: (3), and there is nothing to exempt.** No code change is
owed: the deployed-asset contract is cleanliness under the language's DEFAULT
rule set, and the test's own docstring says upstream cannot guarantee
cleanliness under rules a client CHOOSES — a preview rule is as chosen as a
rule gets. An `accepted_default_rules` entry would be worse than nothing, since
`test_every_accepted_rule_still_fires` would fail it immediately for not
tripping under the defaults.

**What survives is the lesson, not the finding**, and it is N13's again
from the other direction: N13 was a self-reported number nobody could check,
this was a self-reported FAILURE nobody re-ran. A named test and an exit code
are one command apart, and the entry quoted the name without the command.

### N13 — the plan-dedupe scout cleared a plan tree it never read

Dispatched `hooks-daemon-plan-dedupe-scout` before filing Plan 00430. It
returned: "**Checked 0 live plans.** The plan directory contains no active plan
folders — only templates and infrastructure files. There are no plans in
`CLAUDE/Plan/` root and no archived plans in `Completed/` or `Cancelled/`… **No
existing plan covers this.**"

The tree it was pointed at holds **30** live plan folders, **377** in
`Completed/` and **13** in `Cancelled/`.

**Why this is worse than a wrong answer.** The verdict it reached — no existing
plan covers this — happened to be correct, and I only found that out by
re-running the search by hand. A scout that reads nothing returns "no duplicate
found" every single time, and that answer is indistinguishable from a real
clearance. This is the vacuous-guard shape again: N8, N12, the three guards
this session has already paid for, and now an AGENT rather than a checker. The
dedupe scout exists precisely because the failure it prevents is silent and
expensive; one that always says "clear" adds latency and a false assurance.

Note the counts it reported were not "unknown" or "error" — they were **zero**,
stated with the same confidence as a real reading. Nothing in its report
distinguished "I looked and found nothing" from "I did not look."

**Candidate remedies:**

1. Give the scout a vacuity guard of its own: it must report the number of plan
   folders it enumerated, and a run that enumerates zero in a tree that is not
   empty is an ERROR it reports as such, not a clearance.
2. Have the caller verify the count before trusting the verdict — cheap, but it
   makes the scout's answer worthless, since the caller has then done the read.
3. Investigate why it read nothing first. A tool-permission or path-resolution
   failure that surfaces as an empty result rather than an error would explain
   it, and would be the real defect.

Remedy (3), then (1). Fixing the report shape without knowing why it saw an
empty tree would just make the next silent failure noisier rather than rarer.

**Remedy (3) done — and it moves the answer to (1).** Investigated in the same
session.

**It does not reproduce.** A second dispatch, same agent, same tree, a
different subject, with three diagnostics demanded in the prompt: it enumerated
`CLAUDE/Plan/*/PLAN.md` = 28, `Completed/*/PLAN.md` = 378,
`Cancelled/*/PLAN.md` = 13, named five real folders verbatim, and ran the
step-3b archive grep with no stopper. So the empty read was not a
tool-permission failure, not a path-resolution failure, and not deployment
drift — the deployed file is byte-identical to its template in `src/`. It was
a one-off model failure.

**But the successful run was ALSO wrong, by one.** It reported 28 live plans;
the tree holds **29** folders and **29** `PLAN.md` files. Nothing in its output
distinguished 28 from 29 — the number was plausible, internally consistent, and
wrong. This is precisely the drift the agent definition already warns about
("covered 34, then 32, then 17 of the same unchanged 34 plans"), and the
definition's own countermeasure — "the number you report MUST equal the length
of that list" — is self-reconciliation by the same reader that miscounted, so
it cannot catch it.

**That is the finding.** The interesting failure is not the dramatic zero; it
is that a routine, believable answer was also unreliable. A caller cannot tell
the two apart, which makes the scout's count worthless as evidence however
reasonable it looks.

**One defect found on the way, real but not the cause.** The definition
declares `tools: Read, Glob, Grep` — no Bash — while step 3b instructs a
`grep -ril ...` SHELL command and makes the `## Prior art` section compulsory
("an omitted section is indistinguishable from a skipped check"). The Grep tool
does the same job and the repro run mapped across fine, so this blocks nothing.
It is still worth fixing: an instruction naming an idiom the agent cannot run
invites either a dropped section or a `Grepped N archived plans.` line that was
never measured.

**Revised remedy: (1), and it must be EXTERNAL.** The count has to come from
something other than the agent's own honesty — the caller enumerating the
folders itself and comparing, or the dispatch carrying the expected count so a
mismatch is loud. Asking a miscounting reader to check its own count is the
vacuous guard one level up. Rewrite step 3b in tool terms while there.

**REMEDIED by Plan 00434**, and the dispatch that filed that plan demonstrated
the defect a third time while the plan was being written. The scout reported
`Checked 30 live plans.` — a number that was wrong at dispatch (29 folders) and
right on arrival (30), because 00434's own folder was created mid-run. No
reader of that report can tell those apart, which is the argument for a
caller-stated number and against any amount of better self-auditing.

`mkplan.bash` now prints the root plan-folder count beside the reminder to
dispatch the scout, names the `Checked N live plans.` sentence to compare it
with, and says to re-dispatch on a mismatch; `plan_number_helper`'s guidance
carries the same rule for a caller who never runs the scaffolder. Step 3b is
written in Grep-tool terms, and the agent is v1.2.0.

**The step 3b fix shipped as a general guard rather than a one-file edit.** A
shell fence in any shipped agent whose frontmatter does not declare `Bash` now
fails a test — observed RED on the scout and green on `hooks-daemon-docs-qa`,
which declares Bash and carries a fence, so the check is not passing vacuously.
