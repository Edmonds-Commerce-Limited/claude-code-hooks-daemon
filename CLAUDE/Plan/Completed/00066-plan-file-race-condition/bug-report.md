# Hooks Daemon Bug Report: Plan File Race Condition

**Reporter**: Claude agent (session 2026-02-22)
**Component**: `markdown_organization` handler + plan number helper
**Severity**: Medium (workaround exists but causes friction)

## Summary

When Claude Code enters plan mode and writes to the plan file at `/root/.claude/plans/{name}.md`, the hooks daemon intercepts the write and creates a redirect file pointing to `CLAUDE/Plans/{number}-{name}/PLAN.md`. However, the daemon modifies the plan file between Claude's `Read` and `Write` operations, causing a "File has been unexpectedly modified" error on every write attempt.

## Reproduction Steps

1. Claude enters plan mode via `EnterPlanMode`
2. System creates plan file at `/root/.claude/plans/glittery-wandering-thimble.md`
3. Claude reads the file — sees redirect content pointing to e.g. `CLAUDE/Plans/00026-glittery-wandering-thimble/PLAN.md`
4. Claude attempts to write plan content to the file
5. **Between read and write**, the daemon modifies the file (changes the plan number, e.g. 00026 -> 00024 -> 00025)
6. Claude's Write tool fails: "File has been unexpectedly modified. Read it again before attempting to write it."
7. Claude reads again — sees a NEW redirect with a different number
8. Claude attempts to write again — same race condition occurs
9. This loops indefinitely. The plan content is never written.

## Observed Behavior

In this session, three consecutive write attempts produced three different plan numbers:
- First attempt: `00026-glittery-wandering-thimble`
- Second attempt: `00024-glittery-wandering-thimble`
- Third attempt: `00025-glittery-wandering-thimble-2`

None of these directories were actually created (confirmed via Glob).

## Expected Behavior

One of:
1. The daemon should not modify the file between read and write operations
2. The redirect target should be stable (same number on consecutive reads)
3. The Write tool should succeed when writing to the plan file, with the daemon intercepting AFTER the write to copy/redirect the content

## Root Cause Hypothesis

The `plan_number_helper` handler appears to run on every file access (read or write) to the plan file and regenerates the redirect each time, potentially using different plan numbers. This creates a TOCTOU (time-of-check-time-of-use) race condition with Claude's read-then-write pattern.

## Workaround

Exit plan mode with `ExitPlanMode` and implement directly. The plan content exists in the conversation context even though it never reached the file. This works but loses the benefit of persisted plan files.

## Impact

- Plan files cannot be written during plan mode (the primary purpose of plan mode)
- Plan numbers are unstable and increment on each failed attempt
- Ghost plan directories may be created that don't contain actual plans
- Agent must articulate the plan in conversation text instead of the plan file

## Affected Handlers

- `markdown_organization` (priority 35) — redirects plan writes to project
- `plan_number_helper` (priority 30) — assigns/changes plan numbers

## Environment

- Claude Code CLI in YOLO container (Podman)
- hooks-daemon running as background process
- Plan file path: `/root/.claude/plans/{name}.md`
- Project plans path: `CLAUDE/Plans/`
