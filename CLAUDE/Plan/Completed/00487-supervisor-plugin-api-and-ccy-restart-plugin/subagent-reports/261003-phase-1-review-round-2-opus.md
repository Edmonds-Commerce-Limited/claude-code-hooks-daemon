# Plan 00487 Phase 1 review, round 2 (opus)

Verdict: APPROVE, with the following. All must be fixed before merge.

Owner hard rule: a plugin can never bring down or block the session.

1. IMPORTANT, `.claude/ccy/claude-supervise.py` near line 8936. When `_contained`
   trips, the host only stops handling plugin results while the worker keeps
   running every plugin. Notify still types into the chat, exit requests are
   dropped, and a plugin that then hangs is never disabled (`handle_worker_silence`
   no longer runs), so every tick stalls the PTY loop for the 2 s read timeout
   indefinitely. Fix: on a trip, disable ALL plugins (through the uniform failure
   path, one notice) and restart the worker with no plugin flags. Test the
   hang-after-trip scenario.

2. MINOR, near lines 3849 to 3866. Notify rate limits are fixed intervals with no
   lifetime cap. Add a per-kind, per-process cap (named constants) after which
   further Notify of that kind is dropped and logged once. Test it.

3. MINOR, near lines 3863 and 3870. The RESTART_SOON and RESTARTED templates
   hard-code "to pick up a newer Claude Code". Reword neutrally (a restart can be
   for session age); RESTARTED may still name the version now running. Update the
   tests and `CLAUDE/development/CcySupervisor.md`.

Also: remove the unused `state_root` parameter of `PluginHost` if nothing needs it.
