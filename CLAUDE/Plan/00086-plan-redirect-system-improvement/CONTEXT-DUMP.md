# Plan 86: Context Dump - Plan Redirect System Issues

## Origin

During plan 85 (Reminder Pseudo-Event System), the plan redirect system's UX flaws became apparent. This document captures the full context from that session.

---

## Problem Statement (User's Words)

> "the plan redirect system has a major flaw which is that the plan that I am asked to approve is just a redirect. I have to open the plan in a separate window in order to properly audit it - this breaks flow"
>
> "it also looks like the plan rename happens before the plan approval - often but not always - eg this session you did rename it"
>
> "the block hook instructs the agent to rename it, but then the redirect still has the old name so this causes confusion"

---

## How The Current System Works

### Claude Code Plan Mode

When Claude Code enters plan mode (`EnterPlanMode` tool), it assigns a random plan file path:
```
/root/.claude/plans/{random-words}.md
```
Example from this session: `/root/.claude/plans/idempotent-chasing-wadler.md`

The system instructions tell Claude:
- "You should create your plan at /root/.claude/plans/idempotent-chasing-wadler.md using the Write tool"
- "You should build your plan incrementally by writing to or editing this file"
- "NOTE that this is the only file you are allowed to edit"

### The Redirect Handler (markdown_organization)

The `markdown_organization` handler (PreToolUse, priority 50, BLOCKING) intercepts Write/Edit tool calls targeting markdown files. When it detects a write to `~/.claude/plans/`, it:

1. **Redirects** the content to `CLAUDE/Plan/{NNNNN}-{random-words}/PLAN.md` (project version control)
2. **Writes a redirect stub** to the original path (so Claude Code's plan mode doesn't break)
3. **Instructs the agent** to rename the folder to a descriptive name

### The Flow That Actually Happens

```
1. EnterPlanMode → Claude Code assigns /root/.claude/plans/random-words.md
2. Agent explores codebase (read-only)
3. Agent writes plan to /root/.claude/plans/random-words.md
4. markdown_organization INTERCEPTS the write:
   - Content saved to CLAUDE/Plan/00085-random-words/PLAN.md
   - Redirect stub written to /root/.claude/plans/random-words.md
   - Agent told to rename folder
5. Agent renames folder: 00085-random-words → 00085-descriptive-name
6. Agent calls ExitPlanMode
7. User sees plan approval UI
```

### What The User Sees at Step 7

The ExitPlanMode tool reads from `/root/.claude/plans/random-words.md` to show the user the plan. But this file now contains just the **redirect stub**, not the actual plan content!

The redirect stub looks something like:
```markdown
# Plan Redirect
This plan has been saved to: CLAUDE/Plan/00085-descriptive-name/PLAN.md
```

So the user has to open a separate file to review the actual plan. **This breaks the approval flow.**

---

## Issues Identified

### Issue 1: Plan Approval Shows Redirect Stub, Not Content
- **Severity**: HIGH - breaks core UX
- ExitPlanMode reads from `.claude/plans/random-words.md` which is just a redirect
- User cannot review plan content in the approval UI
- Must open separate file/window to read actual plan

### Issue 2: Rename Before Approval Creates Confusion
- Agent renames folder before ExitPlanMode (because handler instructs it to)
- The redirect stub still references the old random name
- After rename, the redirect path is stale
- Timing is non-deterministic (sometimes rename happens, sometimes not)

### Issue 3: Redirect Stub Has Stale Path After Rename
- Redirect stub says `CLAUDE/Plan/00085-random-words/PLAN.md`
- But folder was renamed to `CLAUDE/Plan/00085-descriptive-name/PLAN.md`
- If user follows the redirect, it points to wrong location

### Issue 4: Plan Mode File Restriction
- Plan mode says "this is the only file you are allowed to edit"
- But the handler redirects to a different file
- Creates tension between plan mode restrictions and redirect behaviour

---

## Current Handler Implementation

The handler is `markdown_organization` in the PreToolUse handlers:
- **File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`
- **Priority**: 50
- **Behaviour**: BLOCKING
- **Config key**: `markdown_organization`

It matches Write/Edit tool calls to markdown files and enforces organization rules including the plan redirect.

---

## What Happened In This Session (Concrete Example)

1. `EnterPlanMode` assigned path: `/root/.claude/plans/idempotent-chasing-wadler.md`
2. Agent explored codebase with 3 Explore agents + 1 Plan agent
3. Agent called `Write` to `/root/.claude/plans/idempotent-chasing-wadler.md` with full plan content
4. `markdown_organization` handler intercepted:
   - Saved content to `CLAUDE/Plan/00085-idempotent-chasing-wadler/PLAN.md`
   - Wrote redirect stub to original path
   - Instructed agent to rename folder
5. Agent renamed: `00085-idempotent-chasing-wadler` → `00085-reminder-pseudo-event-system`
6. Agent called `ExitPlanMode`
7. User saw redirect stub instead of plan content
8. User had to open `CLAUDE/Plan/00085-reminder-pseudo-event-system/PLAN.md` separately

---

## Brainstormed Solutions

### Option A: Keep Redirect + Append Full Plan Below
- Write the redirect notice at top
- Append the FULL plan content below for reference
- Pro: ExitPlanMode shows actual content to user
- Con: Content exists in two places (redirect file + plan folder) - could diverge
- Con: If agent edits plan via the redirect path, edits go to wrong copy

### Option B: Write Plan Directly to Project Folder (Skip Redirect)
- Don't intercept the write at all
- Instead, have the agent write directly to `CLAUDE/Plan/NNNNN/PLAN.md`
- This requires teaching the agent (via CLAUDE.md instructions) to write plans there
- Pro: No redirect confusion, single source of truth
- Con: Plan mode's assigned path is ignored - agent must override system instructions
- Con: Plan mode UI won't show the plan (it reads from assigned path)

### Option C: Symlink Instead of Redirect
- Create a symlink from `/root/.claude/plans/random-words.md` → `CLAUDE/Plan/NNNNN/PLAN.md`
- ExitPlanMode would follow the symlink and show actual content
- Pro: Transparent, single source of truth
- Con: May not work if ExitPlanMode doesn't follow symlinks
- Con: Symlink target changes after rename

### Option D: Copy Content Back After Redirect
- Handler redirects as before
- But also copies full content to the redirect path (not just a stub)
- Essentially: content exists at both paths, redirect path is the "mirror"
- Pro: ExitPlanMode shows actual content
- Con: Two copies can diverge if agent edits one but not the other

### Option E: Investigate Claude Code Plan Mode Configuration
- Research if Claude Code supports configuring the plan file path
- If we can set it to `CLAUDE/Plan/NNNNN/PLAN.md` directly, no redirect needed
- This would be the ideal solution if the feature exists
- Need to research: Claude Code settings, plan mode configuration

### Option F: Post-Redirect Hook Update
- After redirect, update the redirect stub to include full content
- The hook itself writes: redirect header + full plan content to original path
- ExitPlanMode shows everything
- On subsequent edits, handler re-copies content
- Pro: Works within current system
- Con: Complexity of keeping two copies in sync

---

## Research Questions

1. Does Claude Code support configuring the plan file path? (settings.json, environment vars, etc.)
2. Does ExitPlanMode read from the file or from some internal state?
3. Can we use symlinks with the plan mode system?
4. Is there a way to hook into ExitPlanMode to modify what the user sees?
5. What does the Claude Code plan mode UI actually display? The file content? A diff?

---

## Plan 85 Status

Plan 85 (Reminder Pseudo-Event System) is ON HOLD pending this review.
Location: `CLAUDE/Plan/00085-reminder-pseudo-event-system/PLAN.md`

---

## Research Results (2026-03-11)

### plansDirectory Setting: DOES NOT EXIST

The `plansDirectory` setting was **hallucinated** by a research agent. It does not exist in Claude Code. There is no way to configure where Claude Code stores plan files.

**What actually exists:**
- Claude Code always assigns: `~/.claude/plans/{random-words}.md`
- No setting to change this path
- Plan mode is toggled via Shift+Tab or `--permission-mode plan`
- ExitPlanMode reads from the assigned file path to show user the plan

**Verified by searching:**
- Claude Code official docs (docs.anthropic.com)
- GitHub issues/discussions
- Local settings.json files (project and user level)
- No `plansDirectory` in any schema or documentation

### ExitPlanMode Behavior

ExitPlanMode reads from the plan file path assigned at EnterPlanMode time. The content shown to the user for approval is whatever is in that file. This means:

- If the file contains a redirect stub → user sees the redirect stub
- If the file contains full plan content → user sees the full plan content

**This is the key insight for the fix.**

### Recommended Fix: Write Full Content to Redirect Path

The simplest fix is to change `handle_planning_mode_write()` (line 238-366 of `markdown_organization.py`) to write the **full plan content** to the redirect path instead of just a stub.

**Current behavior** (line 286-300):
```python
stub_content = (
    f"# Plan Redirect\n\n"
    f"This plan has been moved to the project:\n\n"
    # ... just a redirect notice
)
original_path.write_text(stub_content, encoding="utf-8")
```

**Proposed behavior**:
```python
# Write redirect header + FULL plan content
mirror_content = (
    f"<!-- Plan mirror: canonical location is {plan_path} -->\n\n"
    f"{content}"  # The actual plan content
)
original_path.write_text(mirror_content, encoding="utf-8")
```

**Why this works:**
1. ExitPlanMode reads from `~/.claude/plans/random-words.md`
2. That file now contains the full plan content
3. User sees the actual plan during approval
4. The canonical copy is still in `CLAUDE/Plan/NNNNN/PLAN.md`

**What about edits?**
If the agent edits the plan via the redirect path, the markdown_organization handler would intercept (it already matches on `.claude/plans/`). The handler would need to also update the canonical copy. But in practice, plan mode only allows writing to the plan file, and the initial write is the only one that matters for approval.

### Recommended Fix: Move Rename After Approval

Currently the DENY response instructs the agent to rename immediately. This causes:
- Rename happens before ExitPlanMode
- Redirect stub has stale path

**Fix**: Remove rename instructions from the DENY response. Instead, add rename guidance to ExitPlanMode approval or to CLAUDE.md instructions (rename AFTER plan is approved, during implementation).

### Summary of Changes

1. **`handle_planning_mode_write()`**: Write full content (not stub) to redirect path
2. **DENY response**: Remove rename instruction; just say "plan saved to {path}"
3. **CLAUDE.md or PlanWorkflow.md**: Add guidance to rename plan folder after approval, during implementation phase
