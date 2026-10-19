# Issue #124 scope ruling (stand-in, Fable 5.1)

Stand-in engineering-scope ruling for the issue-sdlc loop. Not the owner's ruling.
Verified against `src/claude_code_hooks_daemon/core/bounded_dispatch.py` (DISPATCH_MAX_INFLIGHT = 16, non-blocking acquire returning DispatchSaturated).

## Implement now under #124 (one plan, one worktree)

- **(1) Recovery command through a saturated pool.** This is the root of the incident: the documented escape hatch did not work. Fix daemon-side (check the recovery carve-out before `dispatch`, so `restart`/`health` never need a permit) AND widen the client carve-out so a well-formed `DispatchSaturated` deny on a recovery command is treated like a transport failure. Strengthens a safety control; pure engineering.
- **(3, first half) `max_inflight` configurable + bounded queue-with-deadline instead of instant refusal.** Config key with the current 16 as default; acquire with a short deadline (bounded by the chain's existing timeout budget) before returning `DispatchSaturated`. Narrow, same code path as (1), same tests.
- **(6) SIGTERM grace > active-request wait.** One constant change in `cli.py` (grace must exceed `server.py`'s 5s drain, e.g. 8s) so a graceful restart actually completes without SIGKILL. Trivial, directly caused the SIGKILLs in the report, belongs in the same fix.
- **(3, watchdog) Sustained-saturation signal.** Log a loud, rate-limited WARNING with inflight count and duration when saturation persists past a threshold. Logging only; the watchdog *acting* (self-restart) is a follow-up, below.

## Split to follow-up plans

- **(2) Stop/SubagentStop semantics under saturation.** Not implemented under #124 and NOT an engineering-only call. Failing open on Stop weakens cron_stop_enforcer and the other SAFETY+BLOCKING stop handlers; "fail once then allow" is a weakened control with a different name. File a plan that lays out the options with the risk of each; the choice stays with the human (see below).
- **(3, watchdog acting on saturation — self-restart/shedding).** Autonomous daemon restart under load is a liveness-vs-safety trade with its own failure modes (restart storms under 12 sessions). Separate plan after (1)/(6) land and the saturation log exists to design against.
- **(4) Upgrade handover without rebuilding venv/checkout under a live daemon.** Real defect but a different subsystem (upgrade/provisioning), different tests, different reviewer. Own plan.
- **(5) Persistent rotating log / saturation journal surviving restart.** Observability feature, not a fix; own plan. The in-memory WARNING from (3) above gives #124 what it needs for diagnosis meanwhile.

## Stays agent-needs-human

- **(2) the actual policy choice** (fail open vs fail-once vs keep fail-closed) for Stop under saturation. Every option except "keep fail-closed" weakens a safety control; the stand-in may not approve that. Recommendation to put before the owner: keep fail-closed, and rely on (1) + queue-with-deadline to make saturation rare and recoverable.
- **Raising the default `max_inflight` above 16.** Making it configurable is engineering; changing the shipped default is a capacity decision the owner should make with host data.

## Rationale for the split

#124's incident has one causal chain: saturation -> recovery command denied -> graceful restart impossible. Items (1), (3-config/queue), (6) and the saturation warning break that chain and share a worktree cleanly. Everything else either changes safety semantics or lives in another subsystem.
