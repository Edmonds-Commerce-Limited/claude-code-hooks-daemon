# Plan 00034: Investigation - What Happened to dogfooding_reminder?

**Date**: 2026-02-10
**Investigator**: Claude (sleuth mode)

## Summary

Plan 00034's Phase 1 (move dogfooding_reminder to plugin) **was completed** in commit `7a201db`, but the plugin was **accidentally deleted** by a later commit `3642c29`. Phases 2-3 (QA.md, run_all.sh update) were also completed in `7a201db`.

## Timeline

### 1. Commit `7a201db` - Plan 00033: Remove API usage handlers

**Date**: 2026-02-09 10:15:04 UTC

This commit did double duty - it handled both Plan 00033 (remove API handlers) and most of Plan 00034:

- **Moved** `dogfooding_reminder` from `src/claude_code_hooks_daemon/handlers/session_start/` to `.claude/hooks/handlers/session_start/dogfooding_reminder.py` (165 lines)
- **Created** plugin tests at `.claude/hooks/handlers/session_start/tests/test_dogfooding_reminder.py` (150 lines)
- **Created** `.claude/hooks/handlers/__init__.py` and `session_start/__init__.py`
- **Removed** `DOGFOODING_REMINDER` from library constants (`constants/handlers.py`, `constants/priority.py`)
- **Created** `CLAUDE/QA.md` (635 lines) - Plan 00034 Phase 2/4
- **Updated** `scripts/qa/run_all.sh` with sub-agent QA reminder - Plan 00034 Phase 3
- **Created** Plan 00034's PLAN.md itself

**Plan 00034 status after this commit**: Phase 1 done, Phase 2 done (merged with Phase 4), Phase 3 done.

### 2. Commit `3642c29` - Feature: Add client installation safety checks

**Date**: 2026-02-09 13:09:10 UTC (~3 hours later)

This commit introduced the `ClientInstallValidator` and **accidentally destroyed the plugin**:

- **Deleted** `.claude/hooks/handlers/__init__.py`
- **Deleted** `.claude/hooks/handlers/session_start/__init__.py`
- **Deleted** `.claude/hooks/handlers/session_start/dogfooding_reminder.py` (165 lines)
- **Deleted** `.claude/hooks/handlers/session_start/tests/__init__.py`
- **Deleted** `.claude/hooks/handlers/session_start/tests/test_dogfooding_reminder.py` (150 lines)
- **Rewrote** `.claude/hooks-daemon.yaml` (246 lines changed) - plugin registration removed

The commit message says "Regenerated hook scripts to match installer output" - the client validator feature appears to have regenerated/cleaned `.claude/hooks/` structure and didn't know about the plugin living there.

## Root Cause

The `.claude/hooks/` directory serves dual purposes:
1. **Hook entry point scripts** (bash scripts that Claude Code calls)
2. **Plugin handler directory** (Python handlers loaded by daemon)

The client validator commit treated `.claude/hooks/` as purely hook scripts and regenerated it, wiping out the plugin directory that had been placed there 3 hours earlier.

## Current State

| Deliverable | Status |
|---|---|
| dogfooding_reminder removed from library | Done (constants cleaned) |
| dogfooding_reminder as plugin | **LOST** - deleted by `3642c29` |
| Plugin config registration | **LOST** - config rewritten by `3642c29` |
| Plugin tests | **LOST** - deleted by `3642c29` |
| `CLAUDE/QA.md` created | Done (still exists) |
| `run_all.sh` sub-agent reminder | Done (still exists) |
| AgentTeam.md updated | Done (updated in `7a201db`) |

## Options

1. **Restore the plugin** - Recover the 3 files from git history (`git show 7a201db:.claude/hooks/handlers/session_start/dogfooding_reminder.py`), re-register in config
2. **Abandon the handler** - Accept the deletion, close plan as partially complete. The handler was a nice-to-have reminder, not critical functionality.
3. **Recreate differently** - If `.claude/hooks/` is too fragile for plugins (gets regenerated), consider a different plugin path

## Recommendation

Option 1 (restore) is straightforward - the code exists in git history. But the underlying conflict (`.claude/hooks/` serving two purposes) should be addressed to prevent this from happening again. The plugin path might need to be somewhere that install/upgrade tooling won't touch.
