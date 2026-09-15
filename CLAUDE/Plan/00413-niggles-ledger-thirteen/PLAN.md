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

**Status**: ⬜ Open

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

**Status**: ⬜ Open

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

**Status**: ⬜ Open

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

## Tasks

- [ ] ⬜ **Task 1.1**: N1 — detector first: a test that asserts every
  `emit_hook_error` call site supplies an event name Claude Code accepts, and
  that fails on the three current ones. Then thread the real event name through.

- [ ] ⬜ **Task 1.2**: N2 — teach the guard to read the tracked
  `self_install_mode` declaration without spawning Python.

- [ ] ⬜ **Task 1.3**: N3 — establish whether the `.example` exclusion is
  deliberate, then track the template or anchor the ignore rule.

- [ ] ⬜ **Task 1.4**: Prove the composite fix the only way that counts —
  a genuinely fresh clone, with an agent started in it.

## Success Criteria

- [ ] ⬜ No `emit_hook_error` path can emit an event name Claude Code rejects,
  and a test fails if one is reintroduced.

- [ ] ⬜ A fresh clone of this repository starts a session in which the daemon
  either runs, or explains in readable prose exactly why it does not.

- [ ] ⬜ Every entry above is terminal.

## Delivery & Milestones

- Opened from a real first-run failure: a new collaborator's fresh clone, which
  is the one environment this project structurally cannot dogfood.
