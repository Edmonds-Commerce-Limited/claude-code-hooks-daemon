# Plan 00413: niggles ledger thirteen

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger twelve (00407) is
archived, so this is the open one.

Both opening entries came from the same event: a collaborator was granted
access, cloned the repository fresh, and started an agent in it. Nothing about
that is unusual — it is the ordinary first-run path for anyone new — and it
produced a session with every safety handler inactive and an on-screen error
that named neither cause nor remedy.

That is worth stating plainly because this repository's own defences are the
product. A fresh clone is the one environment the project cannot dogfood, since
every checkout the maintainers work in has already been installed into.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

> **Resolved entries are compressed to their verdict.** Full reasoning for
> N1 and N2 is in
> [JOURNAL/00413-Journal-26-09-15.md](JOURNAL/00413-Journal-26-09-15.md)
> (11:58 entry), relocated when `plan-doc-size` passed its warning threshold.
> Nothing was deleted.

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
reads two UNTRACKED signals and deliberately ignores the tracked
`self_install_mode: true`, because the config declares INTENT while the env file
and `HOOKS_DAEMON_ROOT_DIR` are evidence the runtime was actually BUILT — and a
fresh clone has the intent with none of the runtime. Believing the config would
have routed the clone to advice that overwrites this repository's own tracked
config (see N5), making the outcome strictly worse.

What WAS wrong was the comment: an unfinished-TODO shape that invited exactly
the change about to be made. Replaced with the rationale. N1 is what made this
expensive rather than annoying — the guard already named its remedy, and N1 is
why nobody read it.

### N3 — a fresh clone has no template for the secret word list

**Status**: ⬜ Open — but NOT as filed; the ignore rule is deliberate and the
fix is elsewhere

`.gitignore:220` ignores `*.secret.example` on purpose, with its reason stated:
the rule ships *"BEFORE any such file is created so a broad `git add` can never
catch one"*. That is defence in depth against someone copying a real list to an
`.example` name, and tracking the template would weaken it. My proposed fix was
wrong.

The gap underneath it is still real, and it is about VISIBILITY rather than the
template. `secret_file_hygiene_checker` reports only on protected paths *that
exist on disk*, so a missing list produces no advisory at all — a new
collaborator gets a working daemon with one guard permanently inert and nothing
anywhere saying so. Surfacing the absence is a handler behaviour change, so it
wants its own plan rather than a ledger quick-fix.

Graduated to Plan
[00414](../00414-absent-protected-path-is-silent/PLAN.md) (Task 1.7).

### N4 — the remedy the guard prints names an interpreter that is not installed

**Status**: ✅ Fixed at `48a9ff74` (and superseded by N5 — the whole command was
wrong, not just the interpreter)

The guard advised `python install.py --self-install`. The flag was right; the
interpreter was not — bare `python` is absent by default on modern Fedora,
Debian 12+ and Ubuntu, and from this container. A reader following it verbatim
got `command not found`, which reads as a broken repository rather than a wrong
instruction. Swept for the same spelling across user-facing output.

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

**The broader lesson, worth more than the fix**: four entries that each looked
independent were ONE sequential failure, and fixing any prefix of them without
the last would have made things worse. N2 routes the reader to the guard; N1
discards the guard's explanation; N4 garbles the command; N5 makes the command
destructive. Repairing N1 alone — the obvious first move, and the one made —
delivered destructive advice to a reader who previously could not read it.

### N6 — the whole persistent-cron mechanism rests on output agents skim

**Status**: ⬜ Open — owner has ruled on the direction; mechanism not yet chosen

`persistent_cron_assertor` cannot create a Claude Code cron; no API exists. It
PRINTS "run CronList, then CronCreate" and relies on the agent to act — and the
owner's field observation is that agents skim SessionStart output. When they do,
the declared cron never exists and nothing reports it, because `CronList` is
session memory the daemon cannot read.

Two compounding facts: `PersistentCronConfig` has no per-machine gating, so
every checkout declares the same job and two machines both fire it at `:23`; and
`issue-sdlc`'s only claim is the `agent-working` label, applied AFTER selection,
so two ticks on the same minute take the same issue.

The owner's rulings — *"the system MUST have teeth or its pointless"* and
*"where the agent ignores hooks, we defer to the supervisor to handle it"* —
name the ccy supervisor as the enforcement tier, and a one-line test on the
other machine showed a turn-level directive succeeds where the same words as
injected context did not.

Full design input, evidence and the three distinct duplication problems:
[DESIGN-cron-enforcement.md](DESIGN-cron-enforcement.md).

### N7 — there is no sanctioned way to FIND a plan, so the number guard denies the only obvious one

**Status**: ⬜ Open — needs a finder; the guard itself is correct and must stay strict

Asked to locate a recently-created plan about Jobs, the obvious first move is
`ls -d CLAUDE/Plan/*job*`. `plan_number_helper` denies it: the `ls_patterns`
entry `ls\s+.*<plan_dir>/\*` matches any glob under the plan directory,
whatever the glob contains.

**This was filed as a false positive and it is not one.** The guard's stated
reason — folder scans miss plans archived in `Completed/` — applies exactly as
written: `CLAUDE/Plan/*job*` searches the 27 active plans and skips the 363 in
`Completed/`, so it would have answered confidently and wrongly had the plan
been archived. The deny prevented an unreliable answer, which is its job.

What is missing is an AFFORDANCE, not a loosening. The deny message's entire
remedy is *"Next plan number is 00415"* — an answer to a question the caller
did not ask. A name search has no sanctioned route at all: `git ls-files`
happens to work and is not mentioned anywhere, and
`hooks-daemon-plan-dedupe-scout` is an agent dispatch, which is the right
weight before filing a plan and the wrong weight for "where is the Jobs plan".

So the guard blocks the unreliable route, stays silent about the reliable one,
and offers a number instead. An agent that hits this either routes around it
with an unblocked-but-equally-partial glob, or burns an agent dispatch.

The fix is additive: a finder that searches the whole tree — active,
`Completed/`, and any other subdirectory — and returns paths, named in the deny
message beside the number. Nothing about the detector should be narrowed:
deny-by-default is what makes a scan-derived number untrustworthy by
construction, and a finder that covers `Completed/` is strictly better than the
glob it replaces rather than a concession to it.

Worth checking while there: whether the same silence applies to the other
discovery shapes the handler blocks (`find`, `echo` glob expansion), and
whether `README.md`'s index is already a searchable substrate the finder should
read rather than walking the filesystem again.

**N7b — and the detector has no git-message exemption, which IS a false
positive.** Committing the entry above was denied, because the commit message
quotes the offending command in its own prose. A `git commit -m`/`-F` message
cannot scan anything; it is a description of a scan, which is exactly what a
ledger entry about a scan must contain.

`sed_blocker` already solves this and is the precedent to copy: its exemption 2
spares a `git commit` message mentioning sed, with no command separator between
the two. `plan_number_helper` has no equivalent, so the handler blocks writing
down the defect it just raised — and the workaround (`git commit -F <file>`,
since the file's CONTENT is never scanned) is discoverable only by hitting the
wall first.

This half is a straight detector fix rather than a new affordance, and it is
cheap: the same exemption shape, applied to the same position in the command.

### N8 — a newly recorded licence never reaches the files already vendored under that domain

Found doing Plan 00412 Task 1.2, correcting `licence: unreviewed` on four
vendored Defence Before Fix documents whose source states CC BY 4.0 plainly.

`documentation.remote.known_sources` maps a domain to an SPDX licence and, per
`CLAUDE/RemoteDocs.md`, exists so "the review is recorded once per SOURCE rather
than once per file". The capture advisory actively recommends it over per-file
frontmatter. But it is consumed only on the CAPTURE path, so recording it has no
effect on anything already vendored from that domain — which, for a domain
anybody has actually used, is every file they care about.

Neither obvious remedy works:

- Hand-editing the frontmatter is DENIED by `remote_docs_provenance`, correctly:
  this tree is captured, not authored.
- `remote-docs refresh --path <file>` reports `unchanged` and rewrites nothing.
  Refresh compares the SOURCE HASH; the licence is a local judgement rather than
  source content, so a content-identical refresh has no reason to re-stamp it.
  This is defensible behaviour on its own terms, which is what makes the gap
  easy to miss.

What does work is re-running `remote-docs add` on the original URL, because
capture re-derives frontmatter from config. That is undocumented, reads as
destructive (it overwrites a vendored file), and is discoverable only by
exhausting the two documented routes first.

The fix is a back-fill: either a `refresh --relicence` flag, or a plain check
that reports any vendored file whose `licence` disagrees with the
`known_sources` entry for its domain. The second is cheaper and fits the
project's report-the-drift habit, but it does not close the loop on its own.

Scale check before anyone over-builds this: it bites once per domain, at the
moment a licence is first recorded. Reporting the drift may well be enough.

### N9 — the provenance deny message misdiagnoses an Edit fragment as a whole file

Same task, separate defect, and this one can actively cause damage.

`Edit` on a vendored file with `new_string: "licence: CC-BY-4.0"` is denied
with: `no YAML frontmatter found; a remote document must open with a --- delimited provenance block`.

The verdict is right and must stand. The reason is wrong: the handler validated
the edit's `new_string` — a one-line fragment — as though it were the whole
file. Every single-line edit to every vendored file produces this message,
including edits that would leave the frontmatter untouched and intact.

**It misleads in a specific and harmful direction.** An agent reading the stated
reason literally would satisfy it the way it asks — by pasting a `---`
frontmatter block into the middle of the document, corrupting the file, having
been invited to do so by the deny message. The guard would then pass the
resulting write, because the fragment now does open with `---`.

The honest reason is already in the rest of the message: this tree is captured,
not hand-edited. Either judge the file the edit WOULD produce (`old_string`
replaced in the real content), or drop the frontmatter diagnosis for `Edit`
entirely and refuse hand-editing plainly. The second is simpler and loses
nothing — no hand `Edit` of a vendored file is ever wanted.

### N10 — the question gate's escape hatch is correct interactively and catastrophic unattended

Raised by the owner, watching a legitimate `AskUserQuestion` go through in this
session: *"if this was in fully headless mode, which it will be most of the
time, [that] would have been a full stop on all progress."*

`ask_user_question_blocker` is prefix-positive. A question prefixed
`ASKING BECAUSE:` is ALLOWED, on the stated rationale that "the user is watching
and will interrupt if the assumption is wrong". That rationale is the whole
design, and it is **conditional on a user being there**.

Unattended — a cron tick, CI, `claude -p`, a hook-driven run — nobody is
watching. The justification the prefix carries is then irrelevant: a perfectly
justified question is as fatal as a tautological one, because both wait for an
answer that is never coming. The gate is calibrated for the case where asking is
merely expensive, and the case where asking is terminal has no representation in
it at all.

Note the inversion this produces. The BETTER an agent behaves — declining to
guess, declaring honestly why it cannot decide, using the sanctioned escape
hatch exactly as documented — the more likely it is to hang an unattended run.
The handler currently rewards the behaviour that breaks headless mode.

**The daemon cannot detect the mode, and this was checked rather than assumed.**
No vendored event in `contracts/claude-code-hooks/` carries a headless,
non-interactive or `--print` signal; `PreToolUse` gets `session_id`,
`transcript_path`, `cwd`, `permission_mode` and `scratchpad_dir`, none of which
distinguishes an attended session from an unattended one. So a third mode cannot
infer its own applicability from the payload — it has to be DECLARED (config or
environment) by whatever launches the unattended run, or detected outside the
hook contract entirely.

**RESOLVED.** Both facts were established, and neither made a handler change
the wrong lever:

- Claude Code 2.1.272 DOES offer mechanisms — the installed CLI confirms
  `--permission-prompts none` ("anything that would prompt is denied
  automatically") and `--permission-mode dontAsk` — and a denied tool leaves
  the model working rather than stalling. But `--permission-prompts` defaults
  to `host`, not `none`, so an unattended run with no flags is NOT covered.
- Decisively for this repository, those are LAUNCHER flags and this project's
  crons are `CronCreate` session-memory jobs firing into an already-running
  interactive session. That session has a TTY and its flags were fixed at
  launch, so the 3am question is drawn to a terminal nobody is reading. No
  launcher flag reaches that case.

A `mode: unattended` was added and enabled here, RED first on the test that
matters — a PROPERLY JUSTIFIED question must be denied — and live-verified
through the real hook. `get_rules()` is mode-aware too, because it renders the
CLAUDE.md rule table and the strict Rule would have published "blocked without
the prefix" in the one mode where a prefix can never help.

The shape of the fix, once the mode is known: a mode in which `AskUserQuestion`
is denied unconditionally, prefix or not, with a reason that tells the agent to
pick the best option, state the assumption in output text, and continue. A deny
is strictly better than a hang — the agent keeps working and the transcript
records what it assumed, which is exactly the audit trail the attended case gets
from the user's silence.

Two things to establish before building it, because either could make a new
handler mode the wrong answer:

1. whether Claude Code already offers a question timeout, or a supported
   disable (`disallowedTools`, a permission deny rule) that returns a
   recoverable tool error rather than stalling — if so this is configuration,
   not a handler change;
2. whether a denied `AskUserQuestion` reliably leaves the model working, rather
   than stopping anyway, which is the failure this entry exists to prevent.

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
everyone else's, and the redness has nothing to do with the change under test.
A developer meeting this for the first time spends their first hour hunting a
defect in their own work.

Worth stating precisely, because the fix could easily be the wrong one: the
LADDER is not what is wrong — reading `/etc/hosts` is a deliberate, documented
rung with a recorded reason (Debian-family hosts write `127.0.1.1 <hostname>`;
Fedora ones do not, which is why "returns nothing" is pinned behaviour). What
is wrong is that the TESTS consult the real file instead of a controlled one.
The fix is to make them hermetic — inject the path or the file's content — not
to weaken the resolver or delete the assertions.

**DETERMINED from the record — not deliberate, and no owner decision needed.**
Plan 00411's Task 1.1 mandates fixtures for exactly these two `/etc/hosts`
shapes, the mechanism exists (`hosts_path` parameter, `ENV_ETC_HOSTS_PATH`),
and the sibling ladder tests already use it. The 13 failures omit it and reach
the real file. The assertion is wrong too: refusing a hostile env value does
not mean NOTHING resolves — the ladder correctly continues to the `/etc/hosts`
rung, which is silent on Fedora and speaks in this container. Full reasoning in
the JOURNAL (13:05 entry).

## Tasks

- [x] ✅ **Task 1.1**: N1 — detector first, RED on both tracked paths, then the
  fix: no event name at all, carried by the universal `systemMessage` field.

- [x] ✅ **Task 1.2**: N2 — resolved as not-a-defect; the misleading TODO-shaped
  comment that invited the wrong change was replaced with the rationale.

- [x] ✅ **Task 1.3**: N3 — established: the exclusion IS deliberate and
  documented. Re-scoped to visibility, which needs its own plan.

- [x] ✅ **Task 1.4**: N4 — corrected in `init.sh` and `daemon/cli.py`; the swept
  repository had no other bare `python install.py`.

- [x] ✅ **Task 1.5**: N5 — `scripts/bootstrap-self-install.sh`, and a message
  that warns against the destructive command rather than recommending it.

- [x] ✅ **Task 1.6**: Prove it the only way that counts — cloned fresh from
  GitHub, ran the real forwarder, followed the printed instruction verbatim.

- [x] ✅ **Task 1.7**: N3 graduated to Plan
  [00414](../00414-absent-protected-path-is-silent/PLAN.md).

- [ ] ⬜ **Task 1.8**: N6 — design the enforcement tier the owner named: what
  the supervisor CHECKS about declared crons, and what it DOES when the check
  fails. Then settle duplication (env-var activation vs a GitHub-side lock) and
  the `agent-working` claim race as the separate problem it is.

- [x] ✅ **Task 1.9**: N7 — `bin/hooks-daemon find-plan <number|name|words>`,
  named in the deny message beside the number and in the injected guidance.
  Detector unchanged, as intended: it still denies, and now says what to do
  instead. Substrate question answered NO — the README index is complete today
  (404 rows against 404 folders) but a plan missing a row would be invisible to
  a reader told the search covers everything, which is the guard's own failure
  mode one layer up. The finder walks the filesystem, which cannot have that
  gap. Live-verified on the archived plan a folder scan misses.

- [x] ✅ **Task 1.10**: N7b — `plan_number_helper` now exempts a `git commit`
  message, RED first on the live reproduction. Anchored on the LAST mention,
  not the first as `sed_blocker` does: a first-match anchor would let
  `git commit -m '...<dir>...' && ls <dir>/*` launder a real scan, and the
  plan directory appears in exactly the messages this exemption allows. Both
  laundering shapes are pinned as still-denied.

- [x] ✅ **Task 1.11**: N8 — `remote-docs check` now reports licence drift
  against `known_sources` beside staleness, and names re-capture as the fix
  (`refresh` compares the source hash and reports `unchanged`). Reporting was
  chosen over a back-fill flag deliberately: re-stamping a licence is a legal
  assertion about someone else's work, so it should be a decision rather than
  a side effect. Folded into the existing verb rather than a new one — a
  second command nobody runs would leave the drift as invisible as it was.
  Proved end-to-end on a scratch project, since the real corpus is clean.

- [x] ✅ **Task 1.12**: N9 — an `Edit` in the tree is now refused outright,
  with a reason that names the real objection instead of a frontmatter
  complaint. RED first. The fix closed a HOLE the misdiagnosis had opened: a
  fragment that parsed as valid provenance previously PASSED, so the message
  invited pasting a `---` block into the document and then waved the corrupted
  write through. The new message also names the `remote-docs add` re-capture
  route, which N8 found was discoverable only by trial.

- [x] ✅ **Task 1.13**: N10 — both facts established, and neither removed the
  need: Claude Code's mechanisms are LAUNCHER flags and cannot reach a
  `CronCreate` job firing into a live interactive session. `mode: unattended`
  added RED-first and enabled here; live-verified through the real hook.

- [ ] ⬜ **Task 1.14**: N11 — UNBLOCKED, no owner confirmation needed: Plan
  00411's Task 1.1 mandates fixtures, so the dependence is accidental. Pass the
  existing `_FEDORA_STYLE_HOSTS` fixture via the `hosts_path` parameter the
  sibling tests already use, so the lower rung is silent and `None` is the
  correct expectation. Do NOT weaken the resolver or drop the assertions.

## Success Criteria

- [x] ✅ No `emit_hook_error` path can emit an event name Claude Code rejects,
  and a test fails if one is reintroduced — 15 tests, including a sweep of all
  32 forwarders and two vacuity guards so a dead regex cannot pass silently.

- [x] ✅ A fresh clone of this repository starts a session in which the daemon
  either runs, or explains in readable prose exactly why it does not.

- [x] ✅ The printed remedy is one a reader can follow without losing anything:
  run from a bare clone it reaches 31/31 listeners and leaves the tracked tree
  clean, with no `.bak` files.

- [ ] ⬜ Every entry above is terminal.

## Delivery & Milestones

- Opened from a real first-run failure: a new collaborator's fresh clone, which
  is the one environment this project structurally cannot dogfood.
