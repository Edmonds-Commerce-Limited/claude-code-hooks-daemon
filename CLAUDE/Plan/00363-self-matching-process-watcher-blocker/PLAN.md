# Plan 00363: self-matching process watcher blocker

**Status**: Not Started
**Created**: 2026-09-09
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An agent waiting for a background job wrote a wait loop shaped like
`until ! pgrep -f "run_02" ...; do sleep 30; done`. The job finished hours
earlier but the loop never exited, because the Bash tool runs every command
through `bash -c "<command>"`: the pattern being searched for sits in the
waiting shell's own command line, so `pgrep -f` always finds at least one
match — itself. The agent reported it as "my waiter never noticed because its
pgrep was matching its own process". The same shape kills the calling shell
with `pkill -f`, and `ps aux | grep <pattern>` without `grep -v grep` (or the
`[p]attern` trick) has the identical defect.

This is a whole class of silent never-ending waits, not a one-off. The daemon
already judges Bash commands for shapes that waste a session (`pipe_blocker`,
`verification_result_not_consumed`, the root-recursion guard); a self-matching
process probe belongs in that family. The fix is a PreToolUse Bash handler
that denies the self-matching shapes with a message naming the safe form, so
the loop is never armed.

## Goals

- Deny a Bash command whose process probe would match the probing shell's
  own command line: `pgrep -f`/`pkill -f` whose pattern is a literal that also
  appears in the command, and `ps ... | grep <pattern>` with no self-exclusion
  (`grep -v grep`, `grep -v $$`, `[p]attern` bracket trick, `pgrep -x`).
- Treat the shape as BLOCKING when it sits inside a `while`/`until`/`for`
  loop, a `watch`, or a `&&`-gated sequence that waits on it (a never-ending
  wait), and ADVISORY when it is a one-shot probe (a wrong answer, not a hang).
- The deny message shows the exact safe rewrite: `pgrep -f "[r]un_02"`,
  `pgrep -x <name>`, `ps -o pid= -p <pid>` with a captured PID, or the
  harness-tracked `run_in_background` completion notification that makes the
  loop unnecessary.
- Acceptance tests (blocking and advisory) via `get_acceptance_tests()`;
  CLAUDE.md guidance via `get_claude_md()`; rule IDs in `constants/rule_ids.py`.

## Non-Goals

- Detecting a loop that never ends for any other reason (wrong file path,
  wrong exit-code sense). This plan covers self-matching process probes only.
- Rewriting the command. The handler denies and explains; it does not edit.
- Judging `pgrep` without `-f` (process-name match cannot hit a `bash -c`
  shell) or a probe whose pattern comes from a variable the handler cannot
  resolve — those are allowed, with an advisory naming the risk.

## Tasks

### Phase 1: Detection library

- [ ] ⬜ **Task 1.1**: `utils/process_probe.py` — parse a Bash command into
  probe sites (`pgrep`, `pkill`, `ps | grep`) using the existing
  `shell_segmentation` helpers; for each, classify self-matching vs safe, and
  whether it sits inside a loop/wait construct. Pure functions, TDD first.
- [ ] ⬜ **Task 1.2**: Corpus test: the real incident command and its safe
  rewrites; `[p]attern`, `grep -v grep`, `pgrep -x`, `pgrep -u`, `$$`
  exclusion, variable patterns, `pgrep -f` outside a loop.

### Phase 2: Handler

- [ ] ⬜ **Task 2.1**: `handlers/pre_tool_use/self_matching_process_probe.py`
  in the safety priority range; DENY for loop/wait shapes, advisory for
  one-shot; registered in `constants/handlers.py`, rule IDs
  `R-PROCESS-PROBE-SELF-MATCH` (deny) and `R-PROCESS-PROBE-ONE-SHOT`
  (advisory) with `explain-rule` text.
- [ ] ⬜ **Task 2.2**: `get_acceptance_tests()` covering deny, advisory and
  the safe forms; `get_claude_md()` guidance with the safe rewrites; handler
  relevance (`get_relevance`) so `optimise` recommends it everywhere.
- [ ] ⬜ **Task 2.3**: Default-enabled in the shipped config, config-changes
  manifest entry, release-notes callout in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, `HANDLER_DEVELOPMENT.md`
  family list updated.

## Success Criteria

- [ ] The incident command (`until ! pgrep -f "run_02"; do sleep 30; done`)
  is denied in the main thread with a message that names the `[r]un_02`
  rewrite, and the rewritten command is allowed.
- [ ] `pkill -f <literal>` is denied (would kill the calling shell).
- [ ] `ps aux | grep foo | grep -v grep` and `pgrep -x foo` are allowed with
  no advisory.
- [ ] Full QA passes; acceptance tests pass in the main thread.
- [ ] The release-notes callout is in the UNRELEASED holding area when the
  plan is marked Complete.

## Delivery & Milestones

- Plan filed during the v3.63.0 release; delivery targeted for the release
  after it unless it lands green before the v3.63.0 QA gate.
