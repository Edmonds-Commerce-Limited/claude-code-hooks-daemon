# Plan 00189: worktree create daemon down raw path completion

**Status**: Not Started
**Created**: 2026-07-24
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00188 made the daemon OWN worktree creation: the `WorktreeCreate`
forwarder now runs in the `worktree` response mode, whose stdout Claude Code
parses as the created worktree's absolute PATH. When the daemon is UP, every
path (happy path, transport error, handler-returns-`{}`) correctly emits either
a raw path or a non-zero exit — never a corrupting `{}` — as verified by the
v3.49.0 release Code Review Gate.

This plan closes the ONE non-blocking gap that review surfaced (and which the
release consciously shipped per RELEASING.md "never drop a finding"): the
daemon-**DOWN** paths of the `WorktreeCreate` forwarder still emit JSON / `{}`
to **stdout with exit 0**. Because Claude Code reads this hook's stdout as a raw
path, a daemon-down worktree launch would be interpreted as the literal path
`/<cwd>/{...json...}` — the exact failure class Plan 00188 fixed, but on the
never-reached-in-practice daemon-down branch.

This is an **incomplete fix, not a regression**: the behaviour is identical to
v3.48.0 (where WorktreeCreate had no handler at all), so it was safe to ship in
v3.49.0. But it should be completed so the raw-path contract holds on EVERY
branch, up or down.

## Context & Background — the finding (v3.49.0 Code Review Gate)

The `worktree` response mode must obey a strict contract: **print a raw
absolute path on success, or exit NON-ZERO printing only to stderr — never emit
JSON/`{}` to stdout.** The daemon-up branches honour this. The daemon-down /
startup-failure branches do not:

- `init.sh:43-160` — `emit_hook_error(...)` prints a JSON error object to
  **stdout** and the generated forwarder then `exit 0`s so "Claude processes the
  JSON response". Correct for JSON-decision events; WRONG for the raw-path
  `WorktreeCreate` event (the JSON is read as the path).
- `install.py:378-395` — `create_forwarder_script`'s `WorktreeCreate` branch
  emits the standard `ensure_daemon` failure stanza (`emit_hook_error ... ; exit 0`)
  shared with JSON-decision forwarders, so a daemon that cannot start yields a
  stdout JSON blob for a raw-path event.
- `init.sh:735-748` and `init.sh:812-825` — the `send_request_stdin` failure
  overrides emit `{}` / JSON on socket errors for some modes; the `worktree`
  mode's fail path must instead exit non-zero with a stderr diagnostic (the
  happy `print_worktree` already exits 1 when `.worktreePath` is absent — the
  gap is specifically the daemon-**down**/`ensure_daemon`-failed branch, not the
  daemon-up no-path branch).

**Severity**: non-blocking / low. Reachable only when the daemon cannot be
started at all (in which case the entire hooks system is already down); no data
loss (Claude Code refuses a non-directory path); identical to pre-v3.49.0
behaviour.

## Goals

- The `WorktreeCreate` forwarder NEVER writes JSON/`{}` to stdout on ANY branch
  — daemon-up or daemon-down. On daemon-start failure it exits non-zero and
  writes its diagnostic to **stderr**, so Claude Code fails worktree creation
  cleanly instead of creating a garbage-named directory.
- A regression test asserts the daemon-down `WorktreeCreate` forwarder path
  exits non-zero with empty stdout (extend the Plan 00188 forwarder probes).

## Non-Goals

- No change to JSON-decision forwarders' daemon-down behaviour (emit error JSON
  - exit 0 is correct for them).
- No change to the daemon-up worktree paths (already correct and shipped).

## Tasks

### Phase 1: Complete the raw-path contract on the daemon-down branch

- [ ] ⬜ **Task 1.1**: RED — a test (forwarder-level or `init.sh`-level) that
  drives the `WorktreeCreate` forwarder with the daemon unstartable and asserts
  exit code ≠ 0 AND empty stdout (nothing parseable as a path).
- [ ] ⬜ **Task 1.2**: GREEN — teach `create_forwarder_script` (and/or a
  `worktree`-mode-aware branch in `init.sh`) to route the raw-stdout events'
  `ensure_daemon`-failure and socket-error paths to a stderr diagnostic + non-zero
  exit, instead of the shared `emit_hook_error` stdout-JSON stanza. Regenerate the
  deployed `.claude/hooks/worktree-create`.
- [ ] ⬜ **Task 1.3**: Generalise via the `raw_stdout` event flag so any future
  raw-stdout event inherits the correct daemon-down behaviour (single source of
  truth, not a WorktreeCreate special-case).
- [ ] ⬜ **Task 1.4**: Full QA green; daemon restart RUNNING; live-dogfood a
  worktree launch with the daemon forced down (or a unit-level equivalent).

## Success Criteria

- [ ] Daemon-down `WorktreeCreate` forwarder: exit ≠ 0, empty stdout, stderr
  diagnostic.
- [ ] Regression test guards it; extends to all `raw_stdout` events.
- [ ] Full QA passes; daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Captured from the v3.49.0 release Code Review Gate (RELEASING.md "never drop a
  finding"); to be fixed immediately after v3.49.0 ships.
- Session recovery cron: reuses Plan 00188's `7a4541bc` (one per session).
