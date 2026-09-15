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
