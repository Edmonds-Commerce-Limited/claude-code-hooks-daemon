# Plan 00413 — the niggles, in full

Supporting document for [PLAN.md](PLAN.md), which carries the INDEX and the
task list. The bodies live here because seventeen of them put PLAN.md past
`plan-doc-size`'s warning tier and within reach of the hard block — and a plan
nobody can edit is worse than a long one. Nothing was deleted; this is remedy
(1) from the handler's own guidance.

Entries appear in the order they were found, which is not numeric order: N14,
N17, N16 and N15 were found while fixing earlier ones, and the sequence is
part of the record. Deeper narrative for most entries is in
[JOURNAL/00413-Journal-26-09-15.md](JOURNAL/00413-Journal-26-09-15.md).

### N1 — `hookEventName: "Unknown"` is not a valid event name, so the whole hook response is discarded

**Status**: ✅ Fixed at `48a9ff74`

`init.sh`'s `emit_hook_error()` embedded the literal `Unknown` as
`hookEventName` on three `source`-time guard paths. Claude Code validates that
field against a closed enum, so the whole response was discarded — the exact
inverse of the function's documented purpose ("ensures the agent sees errors").
The human got a raw JSON blob and an unexplained banner. Fixed by supplying the
REAL event name, never a valid-looking substitute, which would have traded a
visible error for a silent misroute.

### N2 — the self-install guard ignores the tracked config that answers it

**Status**: ✅ Resolved as NOT A DEFECT at `a39ec0d5` — the guard is right, its
comment was misleading

Filed as a defect and it was not one; proving N4 is what showed it. The guard
ignores the tracked `self_install_mode: true` deliberately — the config
declares INTENT, while the untracked signals are evidence the runtime was
actually BUILT, and a fresh clone has the intent with none of the runtime.
Believing the config would have routed the clone to advice that overwrites this
repository's own tracked config (N5).

What WAS wrong was the comment: an unfinished-TODO shape inviting exactly the
change about to be made. Replaced with the rationale.

### N3 — a fresh clone has no template for the secret word list

**Status**: ⬜ Open — but NOT as filed; the ignore rule is deliberate and the
fix is elsewhere

`.gitignore:220` ignores `*.secret.example` on purpose: the rule ships
*"BEFORE any such file is created so a broad `git add` can never catch one"*.
Tracking the template would weaken that, so my proposed fix was wrong.

The gap underneath is real and is about VISIBILITY.
`secret_file_hygiene_checker` reports only on protected paths *that exist*, so
a missing list produces no advisory at all — a new collaborator gets a working
daemon with one guard permanently inert and nothing saying so.

Graduated to Plan
[00414](../00414-absent-protected-path-is-silent/PLAN.md) (Task 1.7).

### N4 — the remedy the guard prints names an interpreter that is not installed

**Status**: ✅ Fixed at `48a9ff74` (and superseded by N5 — the whole command was
wrong, not just the interpreter)

The guard advised `python install.py --self-install`. Bare `python` is absent
by default on modern Fedora, Debian 12+ and Ubuntu, and from this container, so
a reader following it verbatim got `command not found` — which reads as a
broken repository rather than a wrong instruction. Swept for the same spelling
across user-facing output.

### N5 — the advertised remedy DESTROYS this repository's tracked config

**Status**: ✅ Fixed at `a39ec0d5`

Found by trying N4's advice instead of trusting it. `install.py` is the CLIENT
installer: `create_daemon_config` and `create_settings_json` do NOT skip an
existing file — they rename it `.bak` and write a default template over it, on
BOTH paths. A CI runner had already proved this, replacing this repo's
1188-line config with a template invalid against the current schema. So the one
instruction a fresh cloner was given would have destroyed the config and left a
daemon that will not start. Fixed by packaging the procedure `qa.yml` proves on
every run as `scripts/bootstrap-self-install.sh`, and having the message name
that and warn explicitly against `install.py`.

**The broader lesson, worth more than the fix**: N1–N5 are ONE sequential
failure, not four independent ones, and fixing any prefix without the last
makes things worse. Repairing N1 alone — the obvious first move, and the one
made — delivers destructive advice to a reader who previously could not read
it. Chain and reasoning in the JOURNAL.

### N6 — the whole persistent-cron mechanism rests on output agents skim

**Status**: ⬜ Designed — mechanism settled; implementation needs the owner's go

`persistent_cron_assertor` cannot create a Claude Code cron; no API exists. It
PRINTS "run CronList, then CronCreate" and relies on the agent to act — and the
owner's field observation is that agents skim SessionStart output.

Two compounding facts: `PersistentCronConfig` has no per-machine gating, so
every checkout declares the same job and two machines both fire it at `:23`; and
`issue-sdlc`'s only claim is the `agent-working` label, applied AFTER selection,
so two ticks on the same minute take the same issue.

The owner's rulings — *"the system MUST have teeth or its pointless"* and
*"where the agent ignores hooks, we defer to the supervisor to handle it"* —
named the supervisor as the enforcement tier. **N15 then found the daemon can
verify this itself** (`session_crons` at `Stop`), so the supervisor is demoted
to backstop and the teeth become a Stop block.

Design, evidence and the three distinct duplication problems:
[DESIGN-cron-enforcement.md](DESIGN-cron-enforcement.md).

### N7 — there is no sanctioned way to FIND a plan, so the number guard denies the only obvious one

**Status**: ✅ Resolved by Task 1.9 — `bin/hooks-daemon find-plan`

Filed as a false positive and it is not one: the guard's stated reason holds
exactly as written, and a glob under the plan directory really does skip the
363 plans in `Completed/`. What was missing is an AFFORDANCE — the deny
message's only remedy was the next plan NUMBER, an answer to a question the
caller did not ask. Fixed additively, detector untouched.

**N7b — the detector had no git-message exemption, which IS a false positive.**
Resolved by Task 1.10: a `git commit` message describing a scan cannot perform
one, so committing the entry above was denied by the handler it documents.

Full reasoning for both in the JOURNAL (13:25 entry).

### N8 — a newly recorded licence never reaches the files already vendored under that domain

Found doing Plan 00412 Task 1.2, correcting `licence: unreviewed` on four
vendored Defence Before Fix documents whose source states CC BY 4.0 plainly.

`documentation.remote.known_sources` maps a domain to an SPDX licence and, per
`CLAUDE/RemoteDocs.md`, exists so "the review is recorded once per SOURCE rather
than once per file". The capture advisory actively recommends it over per-file
frontmatter. But it is consumed only on the CAPTURE path, so recording it has no
effect on anything already vendored from that domain — which, for a domain
anybody has actually used, is every file they care about.

Neither obvious remedy works: hand-editing frontmatter is DENIED (correctly —
captured, not authored), and `refresh` reports `unchanged` because it compares
the SOURCE HASH, while a licence is a local judgement. What works is re-running
`remote-docs add` on the original URL, which is undocumented and reads as
destructive. Full reasoning in the JOURNAL.

The fix is a back-fill: either a `refresh --relicence` flag, or a plain check
that reports any vendored file whose `licence` disagrees with the
`known_sources` entry for its domain. The second is cheaper and fits the
project's report-the-drift habit, but it does not close the loop on its own.
It bites once per domain, so reporting the drift may well be enough.

### N9 — the provenance deny message misdiagnoses an Edit fragment as a whole file

Same task, separate defect, and this one can actively cause damage.

`Edit` on a vendored file with `new_string: "licence: CC-BY-4.0"` is denied
with: `no YAML frontmatter found; a remote document must open with a --- delimited provenance block`.

The verdict is right and must stand. The reason is wrong: the handler validated
the edit's `new_string` — a one-line fragment — as though it were the whole
file.

**It misleads in a harmful direction.** An agent reading the reason literally
would satisfy it as asked, by pasting a `---` block into the middle of the
document — corrupting the file, invited to do so by the deny message, and the
guard would then PASS that write.

Drop the frontmatter diagnosis for `Edit` and refuse hand-editing plainly: no
hand `Edit` of a vendored file is ever wanted, so nothing is lost.

### N10 — the question gate's escape hatch is correct interactively and catastrophic unattended

Raised by the owner, watching a legitimate `AskUserQuestion` go through in this
session: *"if this was in fully headless mode, which it will be most of the
time, [that] would have been a full stop on all progress."*

`ask_user_question_blocker` is prefix-positive. A question prefixed
`ASKING BECAUSE:` is ALLOWED, on the stated rationale that "the user is watching
and will interrupt if the assumption is wrong". That rationale is the whole
design, and it is **conditional on a user being there**.

Unattended — a cron tick, CI, `claude -p`, a hook-driven run — nobody is
watching, so a perfectly justified question is as fatal as a tautological one:
both wait for an answer that is never coming. The gate is calibrated for asking
being merely expensive, and the case where asking is TERMINAL has no
representation in it.

Note the inversion. The BETTER an agent behaves — declining to guess, declaring
why, using the sanctioned escape hatch exactly as documented — the more likely
it is to hang an unattended run.

**The daemon cannot detect the mode, and this was checked rather than assumed.**
No vendored event carries a headless, non-interactive or `--print` signal, so
the mode has to be DECLARED rather than inferred from the payload.

**RESOLVED.** Both facts were established, and neither made a handler change
the wrong lever:

- Claude Code 2.1.272 DOES offer mechanisms (`--permission-prompts none`,
  `--permission-mode dontAsk`), but `--permission-prompts` defaults to `host`,
  so an unattended run with no flags is NOT covered.
- Decisively: those are LAUNCHER flags, and this project's crons fire into an
  already-running interactive session whose flags were fixed at launch. No
  launcher flag reaches that case.

A `mode: unattended` was added and enabled here, RED first on the test that
matters — a PROPERLY JUSTIFIED question must be denied — and live-verified
through the real hook. A deny is strictly better than a hang: the agent keeps
working and the transcript records what it assumed. `get_rules()` and
`get_acceptance_tests()` are both mode-aware, because each publishes the
handler's behaviour to a different consumer and the strict text is wrong in
this mode. Full reasoning in the JOURNAL.

### N14 — the acceptance playbook describes the DEFAULT handler, not the configured one

`PlaybookGenerator` instantiated every handler bare (`handler_class()`),
reading the config only for `enabled` and `priority`. Configured `options`
never reached the instance, so a handler whose behaviour is switched by an
option declared the behaviour of a mode the daemon was not running.

Not a documentation nit: `tests/acceptance/test_playbook_harness.py`
DISPATCHES those declarations against the live daemon, which DOES apply
options. So the two disagreed and the harness reported three probes failing —
which reads as a defect in the handler, not a stale declaration. Found only
because N10 made the first handler whose declared tests vary by option.

Latent for every future option-switched handler, and silent until one exists.

### N17 — the freshness guard certifies a live dispatch it cannot vouch for

**Status**: ⬜ Open — found and evidenced today; no fix attempted

`compute_source_fingerprint` hashes `.py` ONLY and says so. Its CONSUMERS ask a
different question: the acceptance harness and `smoke_test` gate LIVE DISPATCH
on it. But config is bound at `initialise()`/`register_all()` — which is why a
restart is required after editing `.claude/hooks-daemon.yaml` — and nothing
hashes that file. Edit config, skip the restart, and the guard reports FRESH
while every dispatch is graded against the OLD config.

Not hypothetical: N14 is the evidence — `mode: unattended` changed three live
probe outcomes. The fix is to mix the resolved config into the identity
fingerprint so "stale" covers both inputs the daemon bound at startup. Detail
in the JOURNAL.

### N16 — CLAUDE.md's own discovery route fails on the FIRST handler it lists

CLAUDE.md says of its advisory list: *"Full text: `bin/hooks-daemon explain-handler <name>`"*. The first entry is `daemon_restart_verifier`, and
that command answers `ERROR: unknown handler`, with a "did you mean" list that
does not contain it — so the handler that just fired on your last commit reads
as nonexistent.

Systematic: all four PROJECT handlers fail, because `discover_handler_rules()`
scans only the library package while the CLAUDE.md generator lists them via
`_load_project_handlers`. The generated document and the command it recommends
disagree about what exists.

Scoped by checking rather than assuming: these handlers declare NO rules, so
`explain-rule --list` omitting them is CORRECT and the fingerprint index has no
rule IDs to miss. Only `explain-handler` is wrong. Detail in the JOURNAL.

### N15 — the daemon CAN see the session's crons, and two plans were built on it not being able to

N6 rests on "`CronList` is session memory the daemon cannot read", so declared-
and-running is indistinguishable from declared-and-absent. Plan 00412's D7
rests on the same claim. Both are false.

`Stop` and `SubagentStop` receive **`session_crons`** — one entry per wakeup
"sourced from `CronCreate`, `ScheduleWakeup`, and `/loop`", with `id`,
`schedule`, `recurring` and `prompt`. It is in the vendored contract already
(`Stop.json:48`) and **no handler reads it.**

So enforcement needs no supervisor, no ack verb and no cooperation: compare
declared against actual at `Stop` and block the stop. The correction is
recorded in [DESIGN-cron-enforcement.md](DESIGN-cron-enforcement.md).

Same failure as N12, one layer up — a capability ruled out by inference rather
than checked, and the documentation said yes both times. The 2026-08-26 review
of Plan 00273 had already named this exact hazard about this exact field.

### N11 — host-identity tests read the real machine's `/etc/hosts`, so they pass or fail by machine

Found by a full `tests/unit` run while working on N10. **Thirteen** tests in
`tests/unit/utils/test_host_identity.py` fail in this container and passed in
the previous session on another machine — the handoff for Plan 00411 records
"23,528 tests" green at `d1ed6e88`, which is the commit that introduced them.

Not caused by anything in this ledger: the file imports only
`claude_code_hooks_daemon.utils.host_identity`, which nothing here touches.

The tests pin a resolution LADDER whose bottom rung reads a name out of
`/etc/hosts`. That file is real machine state. This container's carries a name
that satisfies the resolver, so assertions of the form "a hostile value is
REFUSED" get a successful resolution instead and fail:
`assert HostName(name='dc-lts-dev-vm', ...)`.

The failure mode is the expensive one: green on the author's machine, red on
everyone else's, with the redness unrelated to the change under test.

The LADDER is not what is wrong — reading `/etc/hosts` is a deliberate rung
with a recorded reason. The TESTS are, by consulting the real file instead of a
controlled one. Make them hermetic; do not weaken the resolver or drop the
assertions.

**DETERMINED from the record — no owner decision needed.** Plan 00411's Task
1.1 mandates fixtures for exactly these two shapes, the `hosts_path` mechanism
exists, and the sibling tests already use it. Full reasoning in the JOURNAL.

### N12 — the vendored contract cannot express a CONDITIONAL input field, and the gap produced a wrong answer

Found by getting it wrong. Asked whether `PreToolUse` carries agent identity —
the fact deciding whether GitHub issue #14 is buildable — the `input_example`
and a sweep of every contract file both said no. The raw v2.1.272 docs say
YES: `agent_id` is delivered inside a subagent call, explicitly "to distinguish
subagent hook calls from main-thread calls".

The contract could not have shown it: those fields are CONDITIONAL, and an
example depicting a main-thread call omits them correctly. The trap is the
project's own reading convention (recorded in `Elicitation.json`) that the
per-event example is authoritative — right for an UNCONDITIONAL field, a
confident FALSE NEGATIVE for a conditional one. Fix the SLOT, not these two
fields. Full reasoning in the JOURNAL.

### N13 — a scoped QA scan publishes its verdict as the repository's own

`check_sensitive_content.py --json` wrote the shared repo artefact whatever it
scanned, so a `--path` run answering "is this DIRECTORY clean" overwrote the
answer to "is this REPOSITORY clean". Twenty tests scan a `tmp_path` through
that flag, one of them deliberately naming a file with a blocked term — so a
plain test run left `untracked/qa/sensitive_content.json` reading
`passed: false, files_scanned: 1` against a path under `/tmp`, while the
repository was clean across 3,514 tracked files.

That artefact is what `llm_qa.py` publishes for an agent to READ, so the false
verdict is consumed as fact. It was: I read it in-session and reported the repo
had a violation before checking.

Found by dogfooding, not by the suite — every check passed while the artefact
said otherwise, because nothing compares a scoped verdict against its scope.

