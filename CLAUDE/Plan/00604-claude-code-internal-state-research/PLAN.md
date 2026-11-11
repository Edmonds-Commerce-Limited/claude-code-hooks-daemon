# Plan 00604: claude code internal state research

**Status**: In Progress
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon and the ccy supervisor judge what a Claude Code session is doing: busy, idle, waiting, running background tasks or monitors, running sub-agents. They do it from indirect signals, such as the screen text, a sidecar the status line writes, and transcript files. Claude Code itself must track all of this somewhere. Plan 00603 (supervisor idle compaction) is already blocked on the question "can we see background tasks and running sub-agents?", and Plans 00501 (session modes) and 00251-style coordinators need the same facts.

This plan is pure research. It finds out how this version of Claude Code (2.1.322 here) keeps its own state, using documentation, files on disk, the hook payloads and the installed program, so we can say what the daemon can read or hook into and what it cannot. It changes no daemon code.

## Goals

- A map of where Claude Code keeps session state, per kind: background tasks (shell and agent), monitors, scheduled cron jobs, sub-agents and teammates, the input box and turn state, permission and plan modes, context and usage figures, the goal condition, and the inbox socket.
- For each kind: the location or channel (file, directory, socket, environment variable, hook input field, status-line input field, settings key), the format with one redacted example, who writes it, how often, and whether Anthropic documents it as supported or it is internal and may change.
- A ranked list of hook points: what the daemon could read today to answer "is the session truly idle?", with the reliability and the failure mode of each.
- Gaps: facts that have no readable source, so the daemon must keep guessing.
- A recommendation for each consumer: Plan 00603 (idle compaction), Plan 00501 (session modes), and any other plan that infers state from the screen.

## Non-Goals

- No daemon or supervisor code changes.
- No reverse engineering that breaks a licence or terms of use. Reading what the installed tool writes to this container's own disk, its documentation, its debug output and its hook payloads is in scope. Do not decompile in a way the terms forbid; if the program is a bundle, say what you inspected and how.
- No secrets in any report: redact tokens, prompts and file contents.

## Tasks

### Phase 1: Documentation

- [x] ✅ **Task 1.1**: Read the vendored and online Claude Code documentation (hooks, status line, settings, sub-agents, background tasks, monitors, scheduled tasks, teams and the inbox, `/goal`, SDK and headless modes). Use the remote-docs tool for capture. List every documented state surface and field.
- [ ] 🔄 **Task 1.2**: Diff the hook input schemas and status-line input between what the docs say and what this daemon's captured payloads show (debug capture of real events). Docs side done in RESEARCH.md. Payload side not run: `daemon.payload_capture` is off, and switching it on needs a restart of the shared daemon.

### Phase 2: On disk

- [x] ✅ **Task 2.1**: Map the state under `~/.claude/` and under the temporary task directories (for example `/tmp/claude-*/<project>/<session>/tasks/*.output`), by listing, sizes and redacted samples. Identify which files change when a background task starts, runs and ends.
- [x] ✅ **Task 2.2**: Run small controlled experiments in a scratch session where cheap and safe (start and stop a background command, a monitor, a sub-agent, a cron) and record what changes on disk and in hook payloads.

### Phase 3: The program

- [x] ✅ **Task 3.1**: Inspect the installed program as far as the terms allow (package layout, bundled documentation, help output, debug flags, environment variables, any status or introspection command) for state tracking and any API that exposes it.

### Phase 4: Synthesis

- [ ] 🔄 **Task 4.1**: Write `RESEARCH.md` with the map, the ranked hook points, the gaps and the per-consumer recommendations; update Plan 00603 and Plan 00501 with what it settles. RESEARCH.md is written. The cross-plan notes for 00603 and 00501 are left to the coordinator.
- [ ] 🔄 **Task 4.2**: File a plan for the best hook point if one is worth building, or record that none is. RESEARCH.md recommends one plan: a composite `true_idle()` reader built from session status, sub-agent metas and task output trailers. Filing it is left to the coordinator.

## Success Criteria

- [x] `RESEARCH.md` answers, with evidence, whether a true idle (no background task, no sub-agent, no monitor) can be read reliably, and from where.
- [x] Every surface in the map is marked documented or internal, with the Claude Code version it was observed on (2.1.322).
- [ ] The pending-release holding area has no release-bound consequence recorded, because this plan changes no shipped code (say so in the plan on completion).

## Delivery & Milestones

- Plan filed from an owner request on 11 November 2026.
