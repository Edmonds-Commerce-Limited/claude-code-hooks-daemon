# Plan 00602: long running command guard

**Status**: In Progress
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A long command run in the foreground of the main thread blocks the session: messages from the owner and from other agents wait until it ends. The owner asked for a handler that makes this impossible by habit. Any command that may take more than about 30 seconds must run in the background (`run_in_background`), and any foreground command must carry a timeout.

A `timeout N` wrapper, a `sleep` loop, or a wait on a process or on CI is a strong sign that the command is long. The handler uses that sign, and a list of commands known to be slow (test suites, QA runs, builds, installs, `gh run watch`, `until` loops over a remote state). It acts as a PreToolUse guard on the Bash tool for the main thread. Sub-agents are not judged, because they do not block the owner's messages.

## Goals

- A foreground Bash call that is likely to exceed 30 seconds is denied with the exact background form to use, or allowed with a short explicit timeout only when it is clearly short.
- A foreground command with no timeout and no known-fast shape gets an advisory to set one.
- A foreground wait loop (`until`, `while`, `sleep N` with N above a few seconds) is denied and pointed at `run_in_background` and the Monitor tool.
- The 30-second threshold and the command lists are configurable, with a per-call opt-out declaration that names a reason.

## Non-Goals

- No change to sub-agent Bash calls.
- No rewriting of the command on the agent's behalf.
- No measurement of real run times in v1; judgement is by command shape.

## Tasks

### Phase 1: Facts

- [ ] ⬜ **Task 1.1**: Mine recent session transcripts (the transcript tooling) for foreground Bash calls that ran longer than 30 seconds or hit a tool timeout. List the shapes, so the detector is built from evidence.
- [x] ✅ **Task 1.2**: Check the existing handlers that already touch this (the unbounded liveness loop guard, the pipe blocker, the background process tracker) so the new handler adds only what is missing.

### Phase 2: Handler

- [x] ✅ **Task 2.1**: Tests first: foreground shapes that must be denied, advised and allowed, including `timeout N cmd`, `until` loops, `sleep` waits, `gh run watch`, test and QA runs.
- [x] ✅ **Task 2.2**: The handler, its config (threshold, lists, mode: deny / advise / off), rule IDs and `explain-rule` text.
- [x] ✅ **Task 2.3**: The block message names the background form and the Monitor tool; CLAUDE.md guidance text and an acceptance test.

### Phase 3: Release

- [x] ✅ **Task 3.1**: Release note, config docs, and the handler's entry in the generated handler guidance.

## Success Criteria

- [x] A foreground `timeout 590 bash -c 'until ...'` wait is denied in the main thread and allowed in a sub-agent (the handler has `scope=MAIN`; the chain scope gate is covered by `tests/unit/core/test_chain_handler_scope.py`).
- [x] A foreground test-suite run is denied with the background command to use.
- [x] Short commands (`git status`, `ls`) are never blocked.
- [x] The pending-release holding area has a release note for the handler (`057-long-running-command-guard.md`).

## Delivery & Milestones

- Plan filed from an owner request on 11 November 2026.
