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

### N1 — `hookEventName: "Unknown"` is not a valid event name, so the whole hook response is discarded

**Status**: ✅ Fixed at `48a9ff74`

`init.sh`'s `emit_hook_error()` takes an event name as `$1` and embeds it
verbatim in `{"hookSpecificOutput": {"hookEventName": $event, ...}}`. Three
call sites pass the literal string `Unknown`, and the function's own default is
`${1:-Unknown}`:

| line | error type                   |
| ---- | ---------------------------- |
| 265  | `init_path_error`            |
| 285  | `nested_installation`        |
| 323  | `hooks_daemon_repo_detected` |

Claude Code validates `hookEventName` against a closed enum (`PreToolUse`,
`UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `Setup`,
`PreModelSwitch`, …). `Unknown` is not in it, so the response fails schema
validation and is thrown away wholesale.

The consequence is the inverse of what the code intends. `emit_hook_error` is
documented as **CRITICAL: This ensures the agent sees errors and can take
action** — and on these three paths it guarantees the agent sees nothing. The
carefully-worded remedy text is discarded along with the envelope. What the
human gets instead is a raw JSON blob in the status-line area and a
`SessionStart:startup hook error` banner, neither of which names a cause.

Reproduction: clone this repository fresh and start an agent in it.

The fix must supply a REAL event name rather than substituting a valid-looking
one — mislabelling a `PreToolUse` failure as `SessionStart` would trade a
visible error for a silent misroute. The wrappers already know their own event
(`.claude/hooks/session-start` passes `"SessionStart"` correctly to its own
`emit_hook_error` call); only the guards that run at `source` time, before the
wrapper reaches its body, lack it.

### N2 — the self-install guard ignores the tracked config that answers it

**Status**: ✅ Resolved as NOT A DEFECT at `a39ec0d5` — the guard is right, its
comment was misleading

**The original entry below was wrong, and proving N4 is what showed it.** The
guard reads two untracked signals and deliberately does not read the tracked
`self_install_mode: true`. That is correct: the config declares INTENT, while
the env file and `HOOKS_DAEMON_ROOT_DIR` are evidence the runtime was actually
BUILT. A fresh clone has the intent and none of the runtime.

Had the guard believed the config, it would have waved the clone through to the
`NOT_INSTALLED` branch — whose advice is to run the client installer, which
overwrites this repository's own tracked config (see N5). So the "defect" I
filed would have made the outcome strictly worse.

What was genuinely wrong was the comment, which read as an unfinished TODO
(*"requires Python, done later — for now, just trust the override"*) and invited
exactly the change I was about to make. Replaced with the rationale.

`init.sh:309-327` refuses to initialise when the checkout's git remote says
this is the hooks-daemon repository, unless self-install is established. It
tests exactly two things: the `HOOKS_DAEMON_ROOT_DIR` environment variable, and
the presence of `.claude/hooks-daemon.env`.

Both are **untracked and per-checkout**. The repository's own
`.claude/hooks-daemon.yaml` is **tracked** and declares `self_install_mode: true` on line 7 — the fact the guard needs is committed, and the guard does not
read it. The code says so directly:

```
# Check config file for self_install_mode (requires Python, done later)
# For now, just trust the HOOKS_DAEMON_ROOT_DIR override
```

Deferring to keep Python off the hot path is a sound instinct; the cost landed
somewhere unintended. `self_install_mode: true` is a line of YAML that bash can
read without spawning anything, and the guard is not on the hot path — it runs
once, and only in this repository.

This is the same shape as ledger four's entry: **a canonical home must be one
the reader actually receives.** There, two tracked documents pointed at an
untracked home and were dead in every fresh clone. Here, a tracked declaration
is ignored in favour of an untracked one, and the same class of reader — the
one who just cloned — is the one who pays.

N1 is what makes N2 expensive rather than merely annoying: the guard's message
already names the remedy (`python install.py --self-install`), and N1 is why
nobody reads it.

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

`.claude/block-words.secret.example` is not tracked, so a fresh clone receives
no template for the `sensitive_content` word list. The daemon's documented
behaviour when the file is missing is to stand that source down **silently**,
which is correct as a runtime policy and unhelpful as an onboarding one: a new
collaborator gets a working daemon with one guard permanently inert and no
signal that it exists.

The counterexample is next to it — `.claude/hooks-daemon.yaml.example` IS
tracked, and is how the config is discoverable. An `.example` file carries no
secrets by definition; that is what makes it an example.

Scope check before fixing: confirm the ignore rule is not deliberately
prefix-matching the real file, in which case the fix is to anchor the rule
rather than to force-add the template.

### N4 — the remedy the guard prints names an interpreter that is not installed

**Status**: ✅ Fixed at `48a9ff74` (and superseded by N5 — the whole command was
wrong, not just the interpreter)

The `hooks_daemon_repo_detected` message ends with:

> To install for development, run: `python install.py --self-install`

The flag is correct — `install.py --help` confirms `--self-install`. The
interpreter is not. Bare `python` is absent from this container's `PATH`
(`python3` is present), and it is absent by default on modern Fedora, Debian 12+
and Ubuntu, none of which ship an unversioned `python` without an explicit
compatibility package. `install.py`'s own shebang is `#!/usr/bin/env python3`.

So a reader who follows the instruction verbatim gets `command not found`, which
reads as a broken repository rather than a wrong instruction.

This is minor in isolation and compounds badly in sequence: N2 sends the reader
here, N1 stops them ever seeing the sentence, and if N1 is fixed so they finally
read it, N4 is what they hit next. Worth sweeping for the same `python `
spelling elsewhere in user-facing output rather than fixing just this line.

### N5 — the advertised remedy DESTROYS this repository's tracked config

**Status**: ✅ Fixed at `a39ec0d5`

Found by trying N4's advice instead of trusting it. `.github/workflows/qa.yml`
already documented what `install.py --self-install` does to an existing
checkout, in a comment that exists because a CI runner proved it:

> `create_daemon_config` and `create_settings_json` do NOT skip an existing file
> — they RENAME it to `.bak` and write a default template over it. The `force`
> flag only controls whether that backup is taken, so BOTH paths overwrite. On
> the runner it replaced this repo's 1188-line hooks-daemon.yaml, and the daemon
> then refused to start because the template it wrote is invalid against the
> current schema.

So the one instruction a fresh cloner was given would have cost them the
repository's config and left them with a daemon that will not start — and N1
plus N4 had both been "fixed" in a way that made that instruction MORE
prominent and MORE likely to be followed.

`install.py` is the CLIENT installer. Its job is to create files a client
project does not have yet, and every one of them is already tracked here.
Nothing in a clone of this repository needs installing; only the two gitignored
per-checkout runtime artefacts need building.

Fixed by packaging the procedure qa.yml proves on every run as
`scripts/bootstrap-self-install.sh`, and having the message name that and warn
explicitly against `install.py`.

**The broader lesson, worth more than the fix**: four entries that each looked
independent were one sequential failure, and fixing any prefix of them without
the last would have made things worse, not better. N2 routes the reader to the
guard; N1 discards the guard's explanation; N4 garbles the command; N5 makes the
command destructive. Repairing N1 alone — the obvious first move, and the one I
made — delivered destructive advice to a reader who previously could not read
it.

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

- [ ] ⬜ **Task 1.9**: N7 — a plan finder that searches the WHOLE tree
  (`Completed/` included) and returns paths, named in `plan_number_helper`'s
  deny message beside the number. Detector unchanged; check whether
  `README.md`'s index already serves as the substrate.

- [ ] ⬜ **Task 1.10**: N7b — give `plan_number_helper` the git-message
  exemption `sed_blocker` already has, so a commit describing a discovery scan
  is not mistaken for one. Detector fix, RED first.

- [ ] ⬜ **Task 1.11**: N8 — close the loop between `known_sources` and the
  files already vendored under that domain. Decide between a back-fill flag and
  a drift check; the drift check is cheaper and matches the project's habits,
  so start by establishing whether reporting alone is sufficient.

- [ ] ⬜ **Task 1.12**: N9 — stop `remote_docs_provenance` diagnosing an `Edit`
  fragment as a frontmatter-less file. RED first, on a single-line edit that
  leaves valid frontmatter untouched. Prefer refusing hand-edits plainly over
  reconstructing the resulting file, unless the reconstruction is needed
  elsewhere.

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
