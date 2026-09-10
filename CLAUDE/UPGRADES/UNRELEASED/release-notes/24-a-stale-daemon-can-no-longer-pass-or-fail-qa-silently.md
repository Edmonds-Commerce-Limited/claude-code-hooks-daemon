# Callout: a stale daemon can no longer pass or fail QA silently

**Plan**: 00371
**Audience**: everyone

The acceptance harness dispatches every probe through the live daemon socket
rather than in-process handler code, so it was silently grading whatever code
the daemon happened to have loaded at startup, not the working tree. A daemon
never hot-reloads: every handler module is imported once, at startup, and a
source edit afterwards has no effect until it is restarted.

Both directions of that gap were real. A stale daemon holding pre-merge code
produced a **false failure** — a real incident: `SelfMatchingProcessProbeHandler`
was denied for a reason nothing in the harness could explain, because the code
on disk was correct but the running daemon predated the fix. The dangerous
direction was the same gap in reverse: a genuinely broken working tree could
sail through because a stale daemon still answered with the old, correct code
— a **false pass** on the exact release gate meant to catch it.

The daemon now computes a content fingerprint of the code it loaded at
startup (its own package plus, when enabled, the project's
`.claude/project-handlers/`) and reports it over the existing `_system`/`health`
socket action. Every acceptance test that dispatches through a live daemon
socket compares that fingerprint against the current working tree and fails
loudly, by name — `STALE DAEMON: ...`, with the exact remediation
(`bin/hooks-daemon restart`) — before any probe-specific assertion can
produce a confusing symptom instead. The same comparison is reachable
directly via a new `bin/hooks-daemon check-source-fresh` CLI verb, which
`scripts/qa/run_smoke_test.sh` now runs before its own probes.

QA stays read-only: nothing here restarts the daemon automatically. The
daemon a QA run would restart is very often the same one gating the live
agent session running that QA, so an auto-restart risked disrupting hook
dispatch for in-flight tool calls mid-run — detect-and-fail, with a clear
message naming the fix, was the safer design.
