# Hooks Daemon Plan File Race Condition

## Problem Summary

When Claude Code is in **plan mode**, the hooks daemon intercepts writes to the plan file at `/root/.claude/plans/{plan-name}.md` and redirects them to a project-level location at `CLAUDE/Plans/{NNNNN}-{plan-name}/PLAN.md`. This creates a **race condition** that makes it impossible for Claude to write plan content to the plan file.

## Detailed Sequence of Events

### What happens step by step:

1. **Claude reads the plan file** at `/root/.claude/plans/iterative-sauteeing-cerf.md`
   - File contains redirect notice pointing to `CLAUDE/Plans/00048-iterative-sauteeing-cerf/PLAN.md`

2. **Claude attempts to Edit the plan file** with the actual plan content
   - The Edit tool requires matching the current `old_string` content exactly

3. **The hooks daemon intercepts** (either the read or the edit attempt) and:
   - Creates a NEW plan folder (incrementing the number: 00049, 00050, 00051...)
   - Rewrites the plan file content with a NEW redirect notice pointing to the new folder
   - The `old_string` Claude was trying to match no longer exists in the file

4. **Edit fails** with: `File has been unexpectedly modified. Read it again before attempting to write it.`

5. **Claude reads the file again** - sees the new redirect notice (now with 00050)

6. **Claude attempts Edit again** - but the daemon has already modified it again (now 00052)

7. **This loops indefinitely**, with the plan number incrementing each time:
   - 00045 → 00047 → 00048 → 00049 → 00050 → 00051 → 00052 → 00053

### Result: 9 empty plan folders created

```
CLAUDE/Plans/00045-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00047-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00048-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00049-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00050-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00051-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00052-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00053-iterative-sauteeing-cerf/PLAN.md  (empty)
CLAUDE/Plans/00053-iterative-sauteeing-cerf-2/PLAN.md  (empty)
```

Claude was never able to write plan content to the plan file. The plan content only exists in the conversation context.

## Root Cause

The hooks daemon's `PostToolUse` hook for Write/Edit operations on the plan file:
1. Detects a write to `/root/.claude/plans/*.md`
2. Creates a project-level plan folder under `CLAUDE/Plans/`
3. **Replaces the plan file content** with a redirect notice
4. This replacement happens **between Claude's Read and Edit operations**, causing the Edit to fail because the file content no longer matches

The fundamental issue is that the hook **mutates the file that Claude is actively trying to edit**, creating an unresolvable race condition.

## Impact

- Claude cannot write plan content during plan mode
- Multiple empty plan folders are created as side effects
- The plan number auto-increment counter advances unnecessarily (from ~45 to ~53)
- Manual cleanup is required to remove the duplicate empty folders
- Claude must fall back to describing the plan in conversation text and calling ExitPlanMode without the plan file containing actual content

## Suggested Fix Options

### Option A: Don't mutate the source file
Instead of replacing the plan file content with a redirect notice, the hook should:
1. **Copy** the content to `CLAUDE/Plans/{NNNNN}/PLAN.md`
2. Leave the original file **unchanged** at `/root/.claude/plans/{plan-name}.md`
3. Only write the redirect notice **after** Claude calls ExitPlanMode (i.e., after the plan is finalized)

### Option B: Use a file lock or atomic operation
Ensure the hook only triggers once per write operation, not on every read-modify cycle. Use a lock file or debounce mechanism to prevent the hook from firing while Claude is mid-edit.

### Option C: Hook on ExitPlanMode only
Move the redirect/copy logic to the ExitPlanMode hook instead of the Write/Edit hook. This way:
1. Claude writes plan content freely during plan mode
2. When ExitPlanMode is called, the hook copies the finalized plan to the project directory
3. No race condition because the file is only touched once at the end

### Option D: Make the redirect file stable
If the hook must create the redirect, use a **stable redirect** that doesn't change between reads:
- Always point to the same folder (don't create new ones on each trigger)
- Use an idempotent check: if redirect already exists and points to a valid folder, don't modify anything

## Workaround Used

After multiple failed attempts to edit the plan file, Claude:
1. Called `ExitPlanMode` with the plan described in conversation text
2. After exiting plan mode, wrote the plan content directly to `CLAUDE/Plans/00045-visual-acceptance-testing/PLAN.md` (the project-level file)
3. Manually cleaned up the 8 duplicate empty plan folders via `rm -rf`

## Environment

- Claude Code running in podman container (`lts-discreet-booking_yolo`)
- Hooks daemon: `.claude/hooks-daemon/`
- Plan file: `/root/.claude/plans/iterative-sauteeing-cerf.md`
- Date: 2026-02-27
