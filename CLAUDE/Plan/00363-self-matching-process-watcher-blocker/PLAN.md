# Plan 00363: self-matching process watcher blocker

**Status**: In Progress
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
- DENY the self-match wherever it appears, loop or not. The one-shot form was
  going to be advisory; the incident report settles it the other way — an
  advisory inside a background waiter is read by nobody, and the report's own
  timeline has the agent believing a hand-run `pgrep -f` twice in one night.
- The deny message shows the exact safe rewrite: `pgrep -f "[r]un_02"`,
  `pgrep -x <name>`, `ps -o pid= -p <pid>` with a captured PID, or the
  harness-tracked `run_in_background` completion notification that makes the
  loop unnecessary.
- Acceptance tests (blocking and advisory) via `get_acceptance_tests()`;
  CLAUDE.md guidance via `get_claude_md()`; rule IDs in `constants/rule_ids.py`.

The full incident, the three rules it argues for and the deny/allow corpus are
in [INCIDENT-REPORT.md](INCIDENT-REPORT.md): Rule A (self-matching process
search, deny), Rule B (waiting on a wrapper's `$!` after `setsid`/`nohup sh -c`,
deny for `setsid`, advise otherwise), Rule C (unbounded liveness loop, advise).

## Non-Goals

- Detecting a loop that never ends for any other reason (wrong file path,
  wrong exit-code sense). This plan covers self-matching process probes only.
- Rewriting the command. The handler denies and explains; it does not edit.
- Judging `pgrep` without `-f` (process-name match cannot hit a `bash -c`
  shell) or a probe whose pattern comes from a variable the handler cannot
  resolve — those are allowed, with an advisory naming the risk.

## Tasks

### Phase 1: Detection library

- [x] ✅ **Task 1.1**: `utils/process_probe.py` — parse a Bash command into
  probe sites (`pgrep`, `pkill`, `ps | grep`, `ps -p`, `kill -0`); for each,
  classify self-matching vs safe, whether a match is signalled, and whether it
  sits inside a loop/`watch`/`timeout … bash -c` wait. The test applied is the
  tool's own semantics — does the pattern, read as an ERE, match the text of
  the probe's own command line — not a pattern list. Pure functions, TDD first.
- [x] ✅ **Task 1.2**: Corpus test: the incident report's deny and allow
  corpora verbatim, plus `[p]attern`, `grep -v grep`, `pgrep -x`, `pgrep -u`,
  `$$` exclusion, variable patterns, command-name respellings
  (`/usr/bin/pgrep`, `\pgrep`, `env pgrep`, line continuations).

### Phase 2: Handler

- [x] ✅ **Task 2.1**: `handlers/pre_tool_use/self_matching_process_probe.py`
  at priority 17 (safety band); DENY on every self-match; registered in
  `constants/handlers.py`; rule IDs `R-PGREP-SELF-MATCH` (deny),
  `R-UNBOUNDED-LIVENESS-LOOP` and `R-PGREP-UNRESOLVED-PATTERN` (advisory),
  each with `explain-rule` text.
- [x] ✅ **Task 2.2**: `get_acceptance_tests()` covering deny, advisory and
  the safe forms; `get_claude_md()` guidance with the safe rewrites;
  `get_relevance` left at the base `Relevance.always()` — every project runs
  Bash through the same `bash -c` wrapper, so nothing could make it
  inapplicable.
- [x] ✅ **Task 2.3**: Default-enabled in the shipped config template, this
  repo's config and `.claude/hooks-daemon.yaml.example`; config-changes
  manifest entry; release-notes callout in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`; `HANDLER_REFERENCE.md` section
  and summary row (the canonical per-handler list, per `docs/CLAUDE.md`).

### Phase 3: Wrapper-pid wait (Rule B)

- [x] ✅ **Task 3.1**: Detect `kill -0 $!` / `wait $!` / a loop keyed on `$!`
  when the backgrounded command in the same invocation starts with `setsid`,
  `nohup sh -c`, `nohup bash -c`, `timeout` or `env`; deny for `setsid`
  (the parent exits at once), advise for the others; the message names the
  pidfile-written-by-the-job, `pgrep -P <wrapper-pid>` and wait-on-the-artefact
  remedies. Rule ID `R-WAIT-ON-WRAPPER-PID`.
- [x] ✅ **Task 3.2**: Rule C advisory: an `until`/`while` whose body is only
  `sleep` and whose condition is a process probe, with no iteration cap —
  suggests `timeout 3600 bash -c '…'` or a counter. A loop waiting on an
  ARTEFACT (`until grep -q "PLAY RECAP" run.log`) is never flagged: that is
  the remedy the deny message asks for.

## Success Criteria

- [x] ✅ The incident command (`until ! pgrep -f "provision.bash target-host"; do sleep 20; done`) is denied with a message naming the
  `[p]rovision.bash target-host` rewrite, and the rewritten command is allowed.
- [x] ✅ `pkill -f <literal>` is denied (would kill the calling shell).
- [x] ✅ `ps aux | grep foo | grep -v grep` and `pgrep -x foo` are allowed with
  no advisory; so is `until grep -q MARKER log; do sleep 10; done`.
- [x] ✅ Full QA passes; acceptance tests pass in the main thread (Rules A
  and C, v3.63.0 gates).
- [x] ✅ The release-notes callout is in the UNRELEASED holding area (folded
  into v3.63.0's release notes at release time).
- [x] ✅ Rule B (Phase 3) ships with its own callout in the holding area
  (`01-wait-on-wrapper-pid.md`): `setsid ./job & kill -0 $!` is denied,
  `timeout`/`env`/`nohup sh -c` advise, and `./job & pid=$!` stays silent.

## Delivery & Milestones

- Plan filed during the v3.63.0 release.
- Rules A and C merged at `003f3036` and shipped in v3.63.0 (tag `v3.63.0`,
  release commit `3cdc2e11`): the `self_matching_process_probe` handler with
  `R-PGREP-SELF-MATCH` (deny), `R-UNBOUNDED-LIVENESS-LOOP` and
  `R-PGREP-UNRESOLVED-PATTERN` (advisory).
- Rule B (wrapper-pid wait, Phase 3) built on the
  `agent-ab2da8fe312aa481b-9a2cd3ca` worktree branch: `R-WAIT-ON-WRAPPER-PID`
  in the same handler, denying for `setsid` and advising for `nohup sh -c`,
  `nohup bash -c`, `timeout` and `env`. Ships in the next release; the main
  thread merges and closes the plan.
