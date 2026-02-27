# Bug Report: Plan Number Validation Hook False Positive

## Summary

The PreToolUse hook for plan file creation incorrectly rejects a brand-new plan number as a collision with itself, because the `find` command used to determine the "highest existing plan" includes the directory that is being created in the *current* tool call.

## Reproduction Steps

1. Highest existing plan number is 023 (in `CLAUDE/Plan/Completed/023-...`)
2. Run `find` to get next number — correctly returns `024`
3. Run `mkdir -p CLAUDE/Plan/024-dto-phpstan-rules`
4. Run `Write` to create `CLAUDE/Plan/024-dto-phpstan-rules/PLAN.md`
5. Hook fires on the `Write` call and runs its own `find` to validate the plan number
6. Hook's `find` now discovers `CLAUDE/Plan/024-dto-phpstan-rules/` (created in step 3)
7. Hook concludes: "Highest existing plan: 024, Expected next number: 025"
8. Hook rejects plan 024 as incorrect — **false positive**

## Root Cause

The hook's validation logic has a **TOCTOU (time-of-check-time-of-use) race condition** with a twist:

The `mkdir` that creates the plan directory happens *before* the `Write` tool creates the PLAN.md file inside it. By the time the hook's `find` command runs (triggered by the `Write` call), the directory already exists on disk from the preceding `mkdir`.

The hook's `find` command:
```bash
find CLAUDE/Plan -maxdepth 2 -type d -name '[0-9]*' | grep -oP '/\K\d{3}(?=-)' | sort -n | tail -1
```

This finds ALL directories matching the pattern, including the one just created. It then compares the plan number being written against `highest + 1`, but the "highest" already IS the plan being created.

## Expected Behaviour

The hook should recognise that the plan number being created IS the highest number found, and that this is the expected normal case. It should only reject if the plan number is **lower than or equal to** a **pre-existing** plan number.

## Possible Fixes

### Fix 1: Exclude the current plan from the search

The hook knows which plan is being created (from the file path). Exclude that directory from the `find` results:

```bash
# If creating plan 024-dto-phpstan-rules, exclude it from the search
find CLAUDE/Plan -maxdepth 2 -type d -name '[0-9]*' | grep -v '024-dto-phpstan-rules' | grep -oP '/\K\d{3}(?=-)' | sort -n | tail -1
```

### Fix 2: Allow "highest == current"

Instead of requiring `plan_number == highest + 1`, allow `plan_number == highest` (the directory was just created) OR `plan_number == highest + 1` (directory not yet created):

```python
if plan_number >= highest_existing and plan_number <= highest_existing + 1:
    # Valid
```

### Fix 3: Check by file existence, not directory existence

Validate based on whether `PLAN.md` already exists inside the directory, not whether the directory itself exists. The `mkdir` creates the directory, but the `Write` creates the file — if the file doesn't exist yet, it's a new plan.

## Impact

- Blocks plan creation with a confusing error message
- Previously observed in a different form (plan archive `git mv` triggering the same hook incorrectly — see earlier session notes)
- Workaround: ignore the warning, the plan number IS correct

## Environment

- Hook: PreToolUse handler for Write tool
- Trigger: Writing to `CLAUDE/Plan/NNN-*/PLAN.md`
- Date: 2026-02-27
