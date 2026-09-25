# Plan 00470 research: an always-on session

Owner intent: one session on a datacentre server runs permanently, monitors
GitHub issues and resolves them. This file is the evidence base; PLAN.md holds
only the decisions and tasks.

**Notation.** `[V]` = verified in this repository or the vendored docs, with the
citation. `[I]` = inference or design proposal, not verified. Vendored docs are
under `remote-docs/code.claude.com/docs/en/` (abbreviated `docs/`).

## 1. Cron expiry

### What the platform gives us

- `[V]` CronCreate jobs are session-scoped, and "restored on `--resume` or
  `--continue` if unexpired" (`docs/tools-reference.md:35`). So a restart with
  `--continue` keeps unexpired jobs; a fresh `startup` does not.
- `[V]` The 7-day auto-expiry of recurring jobs and the no-op `durable`
  parameter are recorded as known facts in
  `src/claude_code_hooks_daemon/handlers/session_start/persistent_cron_assertor.py`
  (module docstring). The vendored corpus does not hold `scheduled-tasks.md`, so
  the expiry figure is not re-checked here. **Task: vendor it**
  (`bin/hooks-daemon remote-docs add https://code.claude.com/docs/en/scheduled-tasks`).
- `[V]` `Stop` and `SubagentStop` inputs carry `session_crons`, each entry
  `id`, `schedule`, `recurring`, `prompt` (prompt capped at 1000 chars)
  (`docs/hooks.md:2564-2590`, `2421`). **There is no creation time and no
  expiry time in the entry.** The daemon therefore cannot compute a job's age
  from the payload alone.
- `[V]` SessionStart gets `source` = `startup|resume|clear|compact|fork`
  (`docs/hooks.md:1166`) but no `session_crons`
  (`failsafe_cron_session_advisor.py` docstring: "SessionStart receives no
  `session_crons`").
- `[V]` PreCompact / PostCompact events exist with `trigger` manual/auto
  (`docs/hooks.md:73-74, 325`). This repo has `handlers/pre_compact/` but no
  `post_compact/` package.

### What exists today

- `[V]` `persistent_cron_assertor` (SessionStart) states declared
  `persistent_crons` and asks for a CronList reconcile; it asserts by
  instruction, never by verification.
- `[V]` `cron_stop_enforcer` (Stop, priority 7, `terminal=False`) compares
  declared jobs with `session_crons` **on schedule + prompt, never on id**
  (`cron_stop_enforcer.py:238-242`), and blocks the stop naming the exact
  CronCreate. `hooks-daemon cron-pause` is the sanctioned gap. That is how the
  daemon already knows a declared cron is "missing".
- `[V]` `cron_subagent_stop_enforcer` is the SubagentStop twin.
- `[V]` The failsafe-cron family: `recovery_cron_advisor` (PostToolUse on plan
  lifecycle), `failsafe_cron_session_advisor` (SessionStart, Plan 00394),
  `failsafe_cron_blockage_suppressor` (UserPromptSubmit, Plans 00298/00337/00388).

### Consequence

- `[V→I]` An **expired** job simply vanishes from `session_crons`, so
  `cron_stop_enforcer` already catches expiry *after the fact*, at the next
  Stop. The gap: in an idle always-on session, the only thing that produces a
  Stop is a cron tick. If every recurring job expired together (they were all
  created in the same session-start reconcile), **nothing fires any more, so no
  Stop ever arrives** and the enforcer never runs. Expiry is silent death.
- `[I]` Proactive refresh is therefore required: delete + recreate each job
  before it reaches the expiry age, while ticks are still arriving.

### Proposed mechanism (most robust found)

1. `[I]` **Record creation.** A PostToolUse handler on `CronCreate` writes
   `{session_id, cron_id, schedule, prompt_hash, created_at}` to a daemon state
   file (untracked, per project). `tool_response` should carry the new id;
   confirm its shape in a probe before relying on it (unverified).
   CronDelete PostToolUse removes the record.
2. `[I]` **Refresh on Stop.** Extend `cron_stop_enforcer` (it already owns
   the declared-vs-live comparison and the correct priority) with an age check:
   for each live `session_crons` entry whose id has a record older than a
   configurable `refresh_after` (default 6 days, below the 7-day expiry), block
   the stop with "CronDelete <id>, then CronCreate \<schedule, prompt>". Ticks
   keep arriving until expiry, so the block lands on a tick well before death.
3. `[I]` **Unknown age = treat as old.** A live entry with no record (created
   before the handler shipped, or the state file lost) gets a record stamped
   *now* and a one-off advisory; it is not blocked. Conservative in the
   duplicate direction.
4. `[I]` **Compaction.** Compaction does not delete crons (they live in the
   session task registry, not the context) — unverified, probe it. The state
   file is outside context, so compaction loses nothing daemon-side. The
   SessionStart `compact` source re-runs `persistent_cron_assertor`, which is
   enough to re-teach the model the declared jobs.
5. `[I]` **Restart.** On `resume`, jobs return if unexpired and the records
   still match by id. On `startup`, the old records are orphaned: key records
   by session id and prune those of dead sessions at SessionStart.
6. `[I]` **Last-resort external watchdog.** Nothing inside the session can
   revive a session that has no pending tick. The ccy supervisor (a PTY
   wrapper outside Claude Code) can: if it sees no hook traffic for N hours
   while the daemon's cron records say all jobs are past expiry, it types the
   reconcile prompt. This is the only mechanism that survives total expiry.

## 2. Other always-on failure modes

| Mode                                  | Evidence                                                                                                                                                                                                                                                                            | Status           | Proposal                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Context growth / compaction           | `[V]` auto-compaction exists; `SessionStart source=compact`, `InstructionsLoaded load_reason=compact` (`docs/hooks.md:1166,1330`). `[V]` `pre_compact/compaction_signal.py` exists                                                                                                  | partial          | `[I]` Durable state (queue, ledger, crons) must live in files so compaction is lossless; add a PostCompact/`compact` SessionStart re-brief listing queue + live agents                                                                                                                                                                                              |
| Usage limits (5-hour, weekly)         | `[V]` `StopFailure` fires with `error: rate_limit` etc. (`docs/hooks.md:64,332,2664`). `[V]` Notification types `quota_auto_resume_fired/_stale/_disabled` and setting `autoContinueAtUsageLimit` (`docs/hooks.md:2292-2294`). `[V]` no `stop_failure` handler package in this repo | gap              | `[I]` StopFailure handler records limit hits to a durable file; Notification handler records resume. Enable `autoContinueAtUsageLimit` on the server. After resume, the orchestrator reads the queue and re-dispatches dead sub-agents. Note `_disabled` fires when the reset is >24 h away — weekly limits may hit that, leaving the failsafe cron as the only net |
| Sub-agents lost at a limit or restart | `[V]` owner report: every sub-agent died at the weekly limit with no auto-resume                                                                                                                                                                                                    | gap              | `[I]` a durable work queue file (issue, branch, worktree, agent name, phase, last report path). `subagent_report_persistence` already saves replies; the queue references them. Re-dispatch reads the queue, not memory                                                                                                                                             |
| Process / server restart              | `[V]` crons survive `--continue`/`--resume` only (`docs/tools-reference.md:35`)                                                                                                                                                                                                     | gap              | `[I]` run under a systemd unit/ccy supervisor that restarts with `--continue`; SessionStart `resume` path re-briefs from the queue                                                                                                                                                                                                                                  |
| Stale worktrees and daemons           | `[V]` 4 stale `.claude/worktrees/agent-*` dirs present in this checkout today                                                                                                                                                                                                       | gap              | `[I]` a housekeeping tick (existing `idle_housekeeping_advisor`, opt-in) extended to list worktrees whose branch is merged/abandoned, report-first                                                                                                                                                                                                                  |
| Disk and log growth                   | `[I]` daemon logs, `subagent_report_persistence` files, transcripts, command captures in `untracked/` all grow unbounded over weeks                                                                                                                                                 | unmeasured       | `[I]` measure first; then size caps/rotation with a status-line indicator                                                                                                                                                                                                                                                                                           |
| `/goal` supervisor                    | `[V]` `goal_injection` writes a `.goal-intent` signal the ccy supervisor types as `/goal`; the goal ledger is per `(plan, session)`                                                                                                                                                 | interaction risk | `[I]` a restart changes session id; confirm the ledger re-fires on the first plan write of the new session (docstring says it does) and that a permanent issue-monitoring loop does not keep an ever-open goal                                                                                                                                                      |
| Idle-tick cost                        | `[V]` `failsafe_cron_blockage_suppressor` blocks a tick at UserPromptSubmit when the `[awaiting-human]` marker is live, and backs off when no work is owed (Plan 00337 truth table)                                                                                                 | largely solved   | `[I]` measure the real per-tick cost on the server; the issue-poll tick itself is the expensive one (see §3)                                                                                                                                                                                                                                                        |
| Prompt-cache TTL                      | `[V]` cache TTL is 5 min or 1 h (`docs/prompt-caching.md:257-263`)                                                                                                                                                                                                                  | fact             | `[I]` an hourly tick on a large context always misses the 5-minute cache: every idle tick pays full input for the whole context. This is the strongest argument for keeping the orchestrator context small (frequent compaction) and cheap                                                                                                                          |
| Auth expiry                           | `[V]` StopFailure `authentication_failed`, `cloud_credential_error` (`docs/hooks.md:332`)                                                                                                                                                                                           | gap              | `[I]` StopFailure handler writes an alert file + a status-line flag; a human must re-login (`! claude /login`), so this sets `[awaiting-human]` legitimately                                                                                                                                                                                                        |
| `[awaiting-human]` set by teammates   | `[V]` marker is session-keyed, written by `auto_continue_stop` from a `STOPPING BECAUSE:` line (Plan 00298 docstring)                                                                                                                                                               | risk to verify   | `[I]` if a teammate's stop in the same session id writes the marker, it silences the orchestrator's ticks while real work is owed. Test: a SubagentStop/teammate stop must never write the lead's marker                                                                                                                                                            |

## 3. Orchestrator model choice

### Facts

- `[V]` Sub-agent model resolution: per-invocation `model` param, then
  frontmatter `model`, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the main
  model (`docs/sub-agents.md:358-376`). Aliases `sonnet|opus|haiku|fable` or full ids.
- `[V]` Built-in Explore inherits the main model, capped at Opus
  (`docs/sub-agents.md:49-53`). With a Haiku main loop, Explore runs on Haiku
  unless a project `Explore` agent pins a model.
- `[V]` A family alias resolves to the main model when the main model is of that
  family (`docs/sub-agents.md:368-371`) — irrelevant for Haiku main + `opus`
  sub-agents, which resolves to the alias target.
- `[V]` The main-loop model is switchable mid-session (`/model`); hooks
  `PreModelSwitch` (can block) and `PostModelSwitch` exist (`docs/hooks.md:75-76,780`).
  `/model` on a warm cache asks to confirm, because a switch discards the cache
  (`docs/prompt-caching.md:93`).
- `[V]` This repo already has `model_fallback_detector`,
  `model_downgrade_recorder` and `handlers/utils/model_context.py`.
- `[V]` Plan 00418 dogfoods an orchestrator-only mode (main thread routes,
  does not implement) in simulate mode.

### Analysis

- `[I]` **Idle-tick cost.** Per tick cost ≈ context size × input price, uncached
  (§2, TTL). A Haiku main loop is several times cheaper per input token than Opus;
  a small context matters as much as the model. The ideal idle tick is zero
  tokens (already achieved by the suppressor when nothing is owed).
- `[I]` **Judgement risk.** Triage (is this issue real, duplicate, in scope) and
  review verdicts (merge or not) are the high-stakes calls. A weak orchestrator
  that rubber-stamps an Opus reviewer's "approve" adds nothing, and one that
  mis-reads a "reject" merges a defect. The risk is not the routing, it is the
  verdict. Mitigation: verdicts are *structured* (a reviewer writes
  `VERDICT: approve|reject` into a file) and the orchestrator merely executes
  a mechanical rule; no free-text judgement in the cheap model.
- `[I]` **Rule-following risk.** This project's hook surface is large
  (CLAUDE.md above). Weaker models trip guards more often; each deny costs a
  turn. Unmeasured — Plan 00418's simulate record is where to measure it.
- `[I]` **Context window.** Sonnet and Opus offer larger windows than Haiku
  (check `/docs/en/model-config`, not vendored). A long-lived orchestrator on a
  smaller window compacts more often — acceptable if state is file-based.

### Recommendation (uncertain)

`[I]` **Sonnet main loop, Opus sub-agents for implement/review/triage verdicts,
structured verdict files, measured before committing.** Haiku is tempting for
cost but is the likeliest to mis-route and to trip guards; Sonnet is the
middle ground. Do not rely on escalating the main loop to Opus with `/model`:
a switch discards the cache and there is no documented way for the model to
switch itself. Instead, escalation = dispatch an Opus sub-agent with
`model: opus`. Pin `model:` in the project agent frontmatter so the
orchestrator cannot forget it, and set a project `Explore` agent's model
deliberately. Decide from a measured A/B (Phase 4), not from this reasoning.

## 4. Open probes (unverified, each a task)

1. CronCreate `tool_response` shape — does it carry the id?
2. Do crons survive compaction? (expected yes)
3. Does `autoContinueAtUsageLimit` re-dispatch in-flight sub-agents? (expected no)
4. Does a teammate's STOPPING BECAUSE write the lead's `[awaiting-human]` marker?
5. Vendor `scheduled-tasks.md`, `model-config.md`, `interactive-mode.md`.
