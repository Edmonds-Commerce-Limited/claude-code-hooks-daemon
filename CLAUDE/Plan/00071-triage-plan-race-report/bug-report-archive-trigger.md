# Bug Report: Plan Number Hook Incorrectly Triggers on Archive Operations

## Summary

The plan number validation hook fires incorrectly when archiving a completed plan via `git mv` to `CLAUDE/Plan/Completed/`. It treats the archive operation as a "new plan creation" and demands a higher plan number.

## Steps to Reproduce

1. Have an existing committed plan at `CLAUDE/Plan/023-defence-before-fix-skill/PLAN.md`
2. Run:
   ```bash
   git mv CLAUDE/Plan/023-defence-before-fix-skill CLAUDE/Plan/Completed/023-defence-before-fix-skill
   ```
3. Hook fires with error:
   ```
   PLAN NUMBER INCORRECT

   You are creating: CLAUDE/Plan/023-defence-before-fix-skill/
   Highest existing plan: 023
   Expected next number: 024
   ```

## Expected Behaviour

The hook should NOT trigger when:
- Moving/archiving an existing plan to `CLAUDE/Plan/Completed/`
- The operation is a `git mv` (not creating a new directory)
- The plan number already exists (it's the same plan being moved, not a new one)

## Actual Behaviour

The hook treats the `git mv` target path as a new plan creation attempt, sees that 023 already exists (because it IS plan 023), and demands 024.

## Root Cause

The hook appears to match any Bash command that contains a `CLAUDE/Plan/NNN-` path pattern without distinguishing between:
- Creating a new plan directory (`mkdir -p CLAUDE/Plan/024-new-thing`)
- Archiving an existing plan (`git mv CLAUDE/Plan/023-old-thing CLAUDE/Plan/Completed/023-old-thing`)

## Suggested Fix

The hook should:
1. **Ignore `git mv` operations** — these are moves, not creations
2. **Ignore paths under `CLAUDE/Plan/Completed/`** — archiving is not creation
3. **Only trigger on `mkdir` commands** that create new plan directories in `CLAUDE/Plan/` (not `CLAUDE/Plan/Completed/`)

## Context

- Hook: Plan number validation (part of hooks-daemon)
- Trigger: PreToolUse:Bash
- Command that triggered: `mkdir -p CLAUDE/Plan/Completed && git mv CLAUDE/Plan/023-defence-before-fix-skill CLAUDE/Plan/Completed/023-defence-before-fix-skill`
- Date: 2026-02-27
- The operation succeeded despite the warning (hook did not block, only warned)
