# Plan 00094: Claude Code Introspection & Debugging Sub-Agent

**Status**: Not Started
**Created**: 2026-03-30
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Three related problems, one plan:

1. **Claude stops on QA tool failures** — When pytest, ruff, mypy etc. return non-zero, Claude often stops (or asks for guidance) rather than continuing to fix. The `auto_continue_stop` handler handles confirmation questions but not silent stops after failures. The `continue_on_errors` config option may fix this, and a new PostToolUse handler can inject "this is expected, keep fixing" context.

2. **No transcript introspection** — The daemon has a full `TranscriptReader` and every hook receives `transcript_path`, but nothing uses this for smart debugging. A Stop handler that reads the recent transcript could provide far better auto-continue decisions and diagnostic context.

3. **No specialist debugging sub-agent** — Claude Code supports `.claude/agents/` YAML+Markdown sub-agent definitions that are deployed project-scoped. The daemon already deploys hooks, settings.json, slash commands, and skills during install/upgrade. It should also deploy a **hooks-debugger** sub-agent that can: read transcripts, analyse hook events, explain what's happening, generate diagnostic reports, and propose new handlers.

## Goals

- [ ] ⬜ Fix the "stop on QA failure" UX — Claude should auto-continue after pytest/ruff/mypy/bandit failures without the user typing "go"
- [ ] ⬜ Deploy a `hooks-debugger` sub-agent via the daemon install/upgrade pipeline
- [ ] ⬜ The sub-agent can read transcripts, produce reports, and propose handlers from observed patterns
- [ ] ⬜ Leverage `transcript_path` in Stop hooks for smarter auto-continue decisions

## Non-Goals

- Changes to Claude Code itself (we work through hooks only)
- Replacing the existing `auto_continue_stop` handler (enhance, don't replace)
- A full IDE / chat interface for debugging

## Context & Background

### Research Findings

**Non-zero exit codes**: Claude Code itself continues after non-zero Bash exits. The problem is the Claude *AI* deciding to stop — emitting a Stop event after a QA failure without asking a question. `auto_continue_stop` only blocks Stop events when the last assistant message contains a confirmation question pattern. When Claude silently stops after a failure, no pattern matches.

**`continue_on_errors` option**: `auto_continue_stop` already has this config option — when enabled it blocks Stop events even when the transcript shows errors. This is the **quickest fix** for the QA failure case. But it's a blunt instrument and needs to be smarter (only apply to known QA tool failures, not all errors).

**Transcript path in hooks**: Every hook event JSON contains `transcript_path` pointing to the JSONL file. The existing `TranscriptReader` in `core/transcript_reader.py` can parse this lazily. A Stop handler reading the last few messages could make intelligent "should I continue?" decisions.

**Sub-agent deployment**: Claude Code discovers `.claude/agents/*.md` files at session start. These are YAML frontmatter + Markdown prompt, defining model, tools, permissionMode, and description. The description is critical — it's what the orchestrator uses to decide when to invoke the sub-agent. The daemon installer already deploys to `.claude/` and could write an agent file as part of install/upgrade.

**Agent format** (confirmed from docs):
```markdown
---
name: hooks-debugger
description: >
  Specialist for debugging Claude Code hooks daemon. Use when you need to:
  analyse why a hook fired/didn't fire, read session transcripts, diagnose
  handler configuration, generate diagnostic reports, or propose new handlers
  based on observed workflow patterns.
tools: Read, Bash, Glob, Grep
model: sonnet
---
You are a hooks daemon debugging specialist...
```

### Relevant Existing Code

| Component | Location | Relevance |
|-----------|----------|-----------|
| `TranscriptReader` | `core/transcript_reader.py` | Full JSONL parser, already in daemon |
| `auto_continue_stop` | `handlers/stop/auto_continue_stop.py` | Base for enhancement |
| `bash_error_detector` | `handlers/post_tool_use/bash_error_detector.py` | PostToolUse advisory, no exit code |
| `debug_hooks.sh` | `scripts/debug_hooks.sh` | Hook event capture via socket markers |
| Agent installer | `scripts/install/` modules | Deploy target for new agent file |
| `transcript_archiver` | `handlers/pre_compact/transcript_archiver.py` | Archives JSONL before compaction |

### The Stop Hook Continuation Mechanism

```
Claude finishes or decides to stop
  ↓
Stop hook fires (stop_hook_active: false)
  ↓ hook returns {"decision": "block", "reason": "...instruction..."}
Claude receives the block reason as a message and continues
  ↓
Claude finishes again
  ↓
Stop hook fires (stop_hook_active: true) ← MUST exit 0 / return {} here
  ↓
Claude stops cleanly
```

The existing `auto_continue_stop` handler already implements this correctly. We extend the pattern, not replace it.

## Tasks

### Phase 1: Fix QA Failure Auto-Continue (Quick Win)

- [ ] ⬜ **Task 1.1**: Read `auto_continue_stop` handler fully and understand the `continue_on_errors` option and all config paths

- [ ] ⬜ **Task 1.2**: Check current dogfooding config — is `continue_on_errors` enabled? What's the current behaviour?

- [ ] ⬜ **Task 1.3**: Design a `qa_tool_patterns` config option: a list of command prefixes that are "known QA tools" (pytest, ruff, mypy, bandit, black, shellcheck, eslint, etc.). When the last Bash tool call matched a QA pattern AND the Stop hook fires, auto-continue with a "fix the failures and continue" instruction rather than blocking unconditionally.

- [ ] ⬜ **Task 1.4**: TDD — write failing tests for the new QA-aware auto-continue logic:
  - Stop fires after `pytest tests/` failing → block with "fix and continue"
  - Stop fires after `ruff check src/` failing → block with "fix and continue"
  - Stop fires after unrelated Bash failure → existing behaviour (check confirmation pattern)
  - Stop fires with `stop_hook_active: true` → always exit (no loop)

- [ ] ⬜ **Task 1.5**: Implement — enhance `auto_continue_stop` with transcript-aware QA failure detection using `TranscriptReader` to read the last tool use from `transcript_path`

- [ ] ⬜ **Task 1.6**: Update config schema with `qa_tool_patterns` option and defaults

- [ ] ⬜ **Task 1.7**: Full QA + daemon restart verification

### Phase 2: Transcript-Aware Stop Handler Enhancement

- [ ] ⬜ **Task 2.1**: Add `transcript_path` extraction to `auto_continue_stop.matches()` — read from `hook_input["transcript_path"]` (already provided by Claude Code in every Stop event)

- [ ] ⬜ **Task 2.2**: Use `TranscriptReader.read_incremental()` in `handle()` to get last N messages and last tool use result without re-reading the full transcript

- [ ] ⬜ **Task 2.3**: Improve auto-continue instruction quality — instead of generic "proceed with remaining work", inject specific context:
  - What QA tool ran
  - What failed (brief summary from stdout/stderr already in transcript)
  - Explicit instruction: "Fix these N issues, then re-run to verify"

- [ ] ⬜ **Task 2.4**: TDD for transcript-aware improvements

- [ ] ⬜ **Task 2.5**: Full QA + daemon restart verification

### Phase 3: Hooks Debugger Sub-Agent Definition

- [ ] ⬜ **Task 3.1**: Design the agent definition file content. Key design decisions:
  - **description**: Must be specific enough that orchestrators invoke it for the right reasons
  - **tools**: Read, Bash, Glob, Grep (can read transcripts, run daemon CLI, grep logs)
  - **model**: sonnet (sufficient for analysis and report generation)
  - **permissionMode**: default (no need for elevated permissions)
  - The agent's prompt must cover: transcript reading workflow, `daemon.cli` commands for status/logs, handler config lookup, report format

- [ ] ⬜ **Task 3.2**: Write the agent file at `.claude/agents/hooks-debugger.md`. Agent capabilities:
  - Read current session transcript via `~/.claude/projects/{project}/{session}/transcript.jsonl`
  - Run `$PYTHON -m claude_code_hooks_daemon.daemon.cli status/logs/generate-playbook`
  - Read handler source code and config
  - Generate diagnostic reports in `untracked/debug-reports/`
  - Propose new handlers: output a skeleton handler + test file
  - Explain why a hook did/didn't fire for a given command

- [ ] ⬜ **Task 3.3**: Acceptance test the agent manually — invoke it, verify it can find the transcript, read daemon logs, and produce a useful report

- [ ] ⬜ **Task 3.4**: Add the agent file to the install/upgrade deployment pipeline:
  - In `scripts/install/` module: copy `.claude/agents/hooks-debugger.md` to the target project's `.claude/agents/`
  - In upgrade script: deploy/overwrite agent file (same as hook scripts)
  - Add to installer Step N as "Deploy debugging sub-agent"

- [ ] ⬜ **Task 3.5**: Add agent file deployment to the install validation checklist in `CLAUDE/LLM-INSTALL.md`

### Phase 4: Report Generation & Handler Proposal Tooling

- [ ] ⬜ **Task 4.1**: Create `scripts/generate_debug_report.py` — a standalone script the sub-agent (and humans) can run to produce a structured markdown report:
  - Daemon status (running, PID, uptime, memory)
  - Last 50 hook events (from logs)
  - Any DEGRADED MODE or error patterns
  - Active handler list with recent block/allow counts
  - Recent transcript summary (last 5 tool uses + decisions)

- [ ] ⬜ **Task 4.2**: Create `scripts/propose_handler.py` — given a description of desired behaviour, outputs a handler skeleton + test file using existing patterns:
  - Takes: event type, trigger description, action (block/advise)
  - Outputs: `src/claude_code_hooks_daemon/handlers/{event}/my_handler.py` skeleton
  - Outputs: `tests/unit/handlers/{event}/test_my_handler.py` skeleton
  - Pre-fills: HandlerID constant, priority range, matches/handle stubs

- [ ] ⬜ **Task 4.3**: Reference both scripts in the sub-agent's prompt so it knows to use them

- [ ] ⬜ **Task 4.4**: Full QA (scripts don't have unit tests — they're utilities — but verify they run without error)

### Phase 5: Documentation & Release Prep

- [ ] ⬜ **Task 5.1**: Update `CLAUDE/DEBUGGING_HOOKS.md` with sub-agent usage:
  - "Use the `hooks-debugger` sub-agent for interactive debugging"
  - How to invoke it, what to ask it

- [ ] ⬜ **Task 5.2**: Add `generate_debug_report.py` to `CLAUDE/BUG_REPORTING.md` workflow

- [ ] ⬜ **Task 5.3**: Regenerate `.claude/HOOKS-DAEMON.md` via `generate-docs` if any new handlers were added

- [ ] ⬜ **Task 5.4**: Run acceptance tests for Phase 1 changes (QA failure auto-continue):
  - Generate playbook: `generate-playbook > /tmp/playbook.md`
  - Execute `auto_continue_stop` acceptance tests
  - Verify QA failure scenario auto-continues correctly

## Technical Decisions

### Decision 1: Enhance `auto_continue_stop` vs New Handler
**Context**: Should we add a separate handler for QA failure auto-continue, or extend the existing one?

**Decision**: Extend `auto_continue_stop`. It already has the right structure (transcript reading, `stop_hook_active` check, config options). Adding a new handler at a different priority risks ordering issues. The `qa_tool_patterns` option is a natural extension of the existing `continue_on_errors` pattern.

### Decision 2: Where to Read the Transcript
**Context**: The `transcript_path` is in the Stop hook input. Should we read it in `matches()` or `handle()`?

**Decision**: Read in `handle()` only, after `matches()` returns True. Reading files in `matches()` would add I/O to every hook evaluation. `matches()` uses only the hook_input dict; `handle()` does the heavy lifting. The transcript is only needed when we're actually deciding to block.

### Decision 3: Agent File Ownership
**Context**: Should the agent file live in `.claude/agents/` (project-scoped) or be suggested for `~/.claude/agents/` (user-scoped)?

**Decision**: Deploy to the project's `.claude/agents/hooks-debugger.md` via install/upgrade. This makes it immediately available without user setup, co-located with the hooks configuration it's designed to debug, and version-controlled with the project.

### Decision 4: Report Script Location
**Context**: `scripts/` (user-visible) vs `src/` (packaged)?

**Decision**: `scripts/` for user-invocable utilities. The sub-agent prompt can reference them by relative path. No packaging needed — they're project-scoped utilities, not daemon internals.

## Success Criteria

- [ ] Running `./scripts/qa/run_all.sh` (returns non-zero) no longer causes Claude to stop — it auto-continues with fix instructions
- [ ] `hooks-debugger` agent appears in Claude Code's agent picker after daemon install
- [ ] Invoking the agent with "why did the handler block my command?" returns a useful explanation
- [ ] Invoking the agent with "generate a debug report" produces a markdown file with daemon status, recent events, and transcript summary
- [ ] `scripts/propose_handler.py block PreToolUse "block npm install in CI"` outputs a working handler skeleton
- [ ] All existing tests pass, 95%+ coverage maintained
- [ ] Full QA suite passes

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Transcript reading adds latency to Stop hook | Medium | Medium | Use `read_incremental()` with offset, read only last 5 messages |
| Auto-continue creates infinite loop on persistent failures | High | Low | `stop_hook_active` check already prevents this; add max-retries option |
| Agent description too vague — not invoked correctly | Medium | Medium | Test with real orchestrator invocations before release |
| Transcript format changes between Claude Code versions | Medium | Low | Use existing `TranscriptReader` which already handles multiple formats |
| `qa_tool_patterns` too aggressive — continues when it shouldn't | Medium | Low | Default list is conservative; user can extend via config |

## Notes

### The "go" Problem in Detail

When Claude runs `./scripts/qa/run_all.sh` and pytest returns non-zero:
1. Claude sees the failure output
2. Claude decides its task is done (reported the failures) and emits a Stop event
3. `auto_continue_stop` fires, scans last assistant message for confirmation patterns
4. No confirmation pattern → handler returns ALLOW → Claude stops
5. User types "go" to restart

With Phase 1 fix:
1-3. Same
4. Handler reads `transcript_path`, sees last tool use was `./scripts/qa/run_all.sh` with non-zero output
5. Handler recognises this as a known QA tool → returns BLOCK with "Fix the N QA failures, re-run to verify, then continue"
6. Claude continues without user intervention

### Sub-Agent Prompt Design Notes

The agent's description (used by orchestrators for routing) should be specific:
```
Specialist for debugging Claude Code hooks daemon behaviour. Invoke when the user
asks why a hook fired or didn't fire, wants to understand what's in the session
transcript, needs a daemon diagnostic report, or wants to propose a new handler
for an observed workflow pattern.
```

The agent's prompt body should include:
- How to find the current transcript: `transcript_path` from hook inputs, or `~/.claude/projects/` directory listing
- Available daemon CLI commands and what each returns
- The handler development workflow (see CLAUDE/HANDLER_DEVELOPMENT.md)
- Report format template
- Handler skeleton format (see existing handlers as examples)
