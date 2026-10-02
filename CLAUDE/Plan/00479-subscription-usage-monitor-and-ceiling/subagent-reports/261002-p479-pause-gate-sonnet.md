# Plan 00479 Phase 4, daemon side: the usage pause gates (Tasks 4.1, 4.2, 4.3, 4.4, 4.6, 4.7)

Branch `worktree-p479-pause-gate`, three feature commits on top of `7d18f7e2b`:

- `265348867` shared logic, `TickKind.USAGE_RESUME`, `CronList`/`CronCreate` tool names
- `99a66d88e` an `Auto: hooks daemon regenerated CLAUDE.md handler guidance` commit made by
  the daemon itself while I worked (adds the three handlers' markers and rule rows to the
  `<hooksdaemon>` block); kept as it is the correct output
- `fb583a823` the three gate handlers, the stand-downs, constants, configs, docs, guard tests
- `3c208bda2` the status-line chip

## One design finding that shaped Task 4.1

`UserPromptSubmit` `decision: "block"` delivers `reason` to the USER only and never adds it to the
model's context (`remote-docs/code.claude.com/docs/en/hooks.md:1393-1394`). A gate that BLOCKS the
tripping prompt would never tell the model to replace its crons. So the entry directive travels as
`additionalContext` on an ALLOWED prompt (the formatter emits it,
`core/hook_result.py:824-854`), and the directive says "Do NOT act on the request that arrived with
this message". Every LATER prompt while paused is blocked before the model. The Stop gate is the
re-delivery channel if the model did not finish (a Stop `deny` reason does reach the model).

## Per task

**4.1 entry** (`handlers/user_prompt_submit/usage_pause_gate.py`, `UsagePauseGateHandler`,
`HandlerID.USAGE_PAUSE_GATE`, `Priority.USAGE_PAUSE_GATE = 9`, non-terminal). `handle` is at
`:146`; `_maybe_enter` at `:183` finds breaches with
`utils/usage_pause_gate.py:115 find_breaches` (at or above the limit, `>=`), builds the record with
`:159 build_pause` and writes it through the existing `utils/usage_pause.py write_usage_pause`.
`resume_at` = latest `resets_at` among breached windows + `RESUME_MARGIN_SECONDS = 120.0`
(`usage_pause_gate.py:69`). Hostname: `session_ceiling` (`:134`) uses
`utils/cron_hosts.py:67 effective_hostname(hook_input)` (payload stamp
`hooks_daemon_hostname`, else this process's env), the same call the cron enforcers make
(`stop/cron_stop_enforcer.py:131`), then `resolve_host_usage_ceiling`.

**4.2 tool gate** (`handlers/pre_tool_use/usage_pause_tool_gate.py`, `UsagePauseToolGateHandler`,
priority 9, terminal). `matches` (`:77`): allowed tools `CronList`, `CronDelete`, `CronCreate`
(`usage_pause_gate.py:72`) pass; anything else while paused returns
`GatingResult.deny_and_halt(...)` (`:83`), from the already merged
`core/result_types.py` helper. A unit test asserts the wire form has `continue: false`, a
`stopReason` and `permissionDecision: deny`.

**4.3 stop** (`handlers/stop/usage_pause_stop_gate.py`, `UsagePauseStopGateHandler`, priority 6,
non-terminal, `scope=MAIN` like `cron_stop_enforcer`). `handle` (`:91`): allow when `session_crons`
holds exactly one cron whose prompt classifies as `TickKind.USAGE_RESUME`; absent `session_crons` is
"no information" and allows; stop re-entry (`stop_hook_active`) allows with a warning, so the session
is never trapped (the `cron_stop_enforcer` pattern); else deny with `render_stop_directive`.
Stand-down via ONE predicate, `utils/usage_pause_gate.py:234 is_usage_paused` (and
`:243 hook_is_usage_paused` for a payload): `auto_continue_stop.py:613`,
`cron_stop_enforcer.py:137`, `cron_subagent_stop_enforcer.py:116` return `False` from `matches`
while paused.

**4.4 nothing re-arms** `persistent_cron_assertor.py:108`, `failsafe_cron_session_advisor.py:120`
(both SessionStart, so the post-compact SessionStart is covered: the test parametrises
`source: compact`), and `recovery_cron_advisor.py:553` (PostToolUse; unreachable while paused
because of the tool gate, but stands down anyway so a project with the tool gate off is still quiet).

Reuse vs `cron_pause`, decided: **read `usage_pause`, one predicate, `cron_pause` untouched.**
`cron_pause` is CLI-set, 24 h TTL, keyed per declared job id; a usage pause is daemon-written,
per SESSION, ends at a window reset, and the supervisor must read it too (Task 4.5 already built that
record). Reusing `cron_pause` would need a synthetic job id per declared job and a TTL that is wrong by
construction. Documented in `usage_pause_gate.py`'s module docstring and
`usage_pause.py`'s existing "Relation to cron_pause" note.

**4.6 resume** `UsagePauseGateHandler._resume` (`:214`): the resume cron's prompt is
`USAGE_RESUME_PROMPT` (`usage_pause_gate.py:80`), first line `[tick:usage-resume]`. I added
`TickKind.USAGE_RESUME` to `utils/cron_tick.py`, so the tick is a recognised daemon tick (never reads
as the owner, `failsafe_cron_blockage_suppressor._handle_other_tick` allows it). On the tick usage is
re-read via `latest_usage(now=)` (a window past `resets_at` is absent): no breach (or no ceiling,
no snapshot) clears the record and delivers `render_resume_lifted_directive`, which carries the
declared `persistent_crons` jobs for this host (via `declared_tick_prompt`) and the canonical failsafe
prompt when the recovery advisor is on and the failsafe is not declared (so the re-establish step does
not depend on the SessionStart advisors, which stay quiet during the pause). Still over: record
refreshed with the new `resume_at`, `render_still_over_directive`.

**4.7 data safety** No ceiling for the host, unknown hostname (`session_ceiling` returns no limits),
no snapshot, snapshot with no windows, below the ceiling, no `ProjectContext`, or a record that fails
to write all return ALLOW with no directive; each logs a distinct debug line
(`usage_pause_gate: no usage ceiling for host ... not pausing`, `no usage snapshot ... not pausing`,
`usage below the ceiling`, `no project context`) and a write failure logs a warning. Status line:
`handlers/status_line/usage_indicator.py:122 _pause_chip` leads with a red `⏸ usage HH:MM` (local
time) chip while the session's record is live, also when there is no snapshot; no session id in the
payload means no lookup, so existing renders are unchanged. `prompt_cache_indicator.py` was not touched.

## The exact directive text (entry; `render_pause_directive`, `usage_pause_gate.py:272`)

```
USAGE CEILING REACHED - this session is PAUSED until <local_text> (<utc_text>).

Usage: <window> window at <N>% (ceiling <M>%). This host stops taking on work at its ceiling so the
account is not driven into its hard limit; the window resets, and a single resume cron brings the
session back then.

Do NOT act on the request that arrived with this message (a prompt, a cron tick or a supervisor
message): it is refused for now. Every tool except CronList, CronDelete and CronCreate is denied
until the pause ends. Do exactly this and nothing else:

  1. CronList - list every cron in this session.
  2. CronDelete EVERY cron listed: the failsafe recovery cron, every persistent_crons job, the
     watchdog, anything else. They are re-established when the pause lifts, so deleting them is correct.
  3. CronCreate ONE cron: schedule `<m> <h> <dom> <mon> *` (local time; <local_text>, which is
     <utc_text>), recurring: false, durable: false, with this exact prompt, first line included:
       [tick:usage-resume]
       USAGE PAUSE RESUME CHECK: the subscription usage window this session paused on should have
       reset. The daemon re-reads usage and tells you whether to resume or to schedule another
       resume cron.
     Check that CronCreate reports a next run of <local_text>.
  4. Stop with `STOPPING BECAUSE: usage paused until <HH:MM>`. The stop is accepted once exactly
     that one cron remains.
```

Percentages are rounded DOWN (`_percent`), matching the status line, so 79.9 never reads as 80.
The Stop-block variant (`render_stop_directive`) opens "USAGE PAUSE NOT COMPLETE - session_crons holds
N crons, and a paused session may stop only when exactly ONE cron remains: the resume cron." and then
repeats the same steps. The still-over variant opens "USAGE STILL OVER THE CEILING". The lifted variant
opens "USAGE PAUSE LIFTED - usage is back under the ceiling and the session may work again." and lists
CronList, re-create the failsafe and each declared job (schedule + prompt verbatim), continue the work.

## Resume-cron schedule logic (`resume_schedule`, `usage_pause_gate.py:184`)

`resume_at` is rounded UP to a whole minute (never fires early), converted with
`datetime.astimezone(tz)` (`tz=None` = the daemon machine's local zone), and expressed as a pinned
5-field one-shot `"<minute> <hour> <day-of-month> <month> *"`, so it fires once at that wall-clock
instant; `recurring: false`. The directive prints the local time, the zone name and the UTC time side
by side so the model can check what `CronCreate` reports.

**Verification gap**: the scheduled-tasks doc is not vendored (`remote-docs/.../scheduled-tasks.md`
absent). That CronCreate reads 5-field expressions in LOCAL time rests on the repo's own model
(`config/models.py:2147` "Standard 5-field cron expression, local time" for `persistent_crons`), not on
a CronCreate doc I could read; that `recurring: false` makes a one-shot is from the tool's own
parameter names in the existing handlers' advice. Task 4.8's live probe should confirm both, and that
the daemon's local zone equals the session's. The directive's "check the reported next run" step
is the runtime guard.

## Tests

TDD, tests first. New: `tests/unit/utils/test_usage_pause_gate.py` (46),
`tests/unit/handlers/user_prompt_submit/test_usage_pause_gate.py` (30),
`tests/unit/handlers/pre_tool_use/test_usage_pause_tool_gate.py`,
`tests/unit/handlers/stop/test_usage_pause_stop_gate.py` (17),
`tests/unit/handlers/test_usage_pause_stand_down.py` (control match when unpaused, no match when
paused, no effect from another session's pause, for all seven handlers incl. post-compact),
status-line cases in `tests/unit/handlers/status_line/test_usage_indicator.py`, tick cases in
`tests/unit/utils/test_cron_tick.py`. Every test uses `tmp_path` and patches
`ProjectContext.daemon_untracked_dir` and an injected usage loader: nothing reads or writes the live
snapshot or a real session's record.

Guard tests updated for the new handlers (each answers a declared requirement rather than loosening it):
`test_claude_md_guidance_coverage.py` (verdicts), `test_handler_scope_defaults.py`
(`usage-pause-stop-gate` is MAIN), the priority-band doc rows in `CLAUDE/HANDLER_DEVELOPMENT.md` and
`docs/guides/CONFIGURATION.md`, acceptance tests (deny cases declare `harness_cannot_produce`
because a probe cannot create a pause record; near-miss ALLOW cases are real).

## QA run

- black (py311), ruff, mypy, pyright on all 20 touched `.py` files: clean.
- Targeted pytest, all green: 1297 (stand-down + stop + subagent_stop + session_start + recovery),
  626 status_line, 761 (constants/config/registry/probe), 4676 (core/install/docs_qa/rule_explain),
  810+728 targeted integration guards (acceptance contract/negative/coverage, guidance coverage,
  scope defaults, priority bands, stop-chain shadowing, handler reference, dogfooding/example config,
  response validation, doc truth, instantiation).
- `./scripts/qa/llm_qa.py changed` could NOT run: it queued behind the host-wide QA lock held by
  another agent (`worktree-gh68-glob-prefix`) for 300 s and I cancelled it when the coordinator asked
  for a quiet window.
- One integration ERROR I did not resolve: `test_config_changes_manifest_examples.py::...v3.29.0.yaml: handlers.post_tool_use.background_process_tracker` errored in `no_test_writes_tracked_generated_docs`
  ("rewrote tracked generated doc(s): CLAUDE.md, .claude/HOOKS-DAEMON.md"). Throughout this work those
  two files were rewritten from outside my commands (twice reverted to a version lacking the new
  handlers); I could not attribute it, the guard itself says an external editor/daemon can land inside
  a test. I committed correct generated content by `git hash-object`/`update-index` for
  `.claude/HOOKS-DAEMON.md` (regenerated with `generate-docs --output`, verified to list the three
  handlers) and relied on the daemon's own Auto commit for `CLAUDE.md`. The coordinator's restart will
  regenerate both anyway; please confirm after the merge that `CLAUDE.md` holds the three handlers'
  rows. I did not restart any daemon.

## Residual risks and for Task 4.8 (live acceptance, coordinator)

1. A synthetic snapshot above the ceiling: write `untracked/usage-snapshot.json` (or feed a Status
   event) with a window at/above a `hosts:` entry's limit for the probe host
   (`HOOKS_DAEMON_HOSTNAME`), then submit a prompt: expect `additionalContext` with the directive, a
   `<session>.usage-paused` record, then `CronList`/`CronDelete`/`CronCreate` allowed and `Bash` denied
   with `continue: false`.
2. Stop with the wrong crons must repeat the directive once, then allow on re-entry.
3. Fire the resume tick with the snapshot absent (lift) and with a weekly window still over (refresh).
4. Confirm the two unverified CronCreate facts above (local-time interpretation, `recurring: false`
   one-shot) and that the daemon and session share a time zone.
5. If `clear_usage_pause` fails after a lift (disk error) the record stays live until
   `resume_at` + 1 h and prompts keep being blocked; it is logged as a warning, and is the one place a
   lifted-in-words pause is still held. I judged an unremovable file too rare to add a second
   mechanism (YAGNI) but flag it.
6. A human prompt while paused is blocked like any other (the ruling said cron ticks and supervisor
   messages are included; a human is not exempted). The block reason names the resume time. There is
   no override CLI; lifting the pause early means deleting the record or editing `hosts:` and
   restarting.
7. `CLAUDE.md`, `.claude/HOOKS-DAEMON.md` regeneration: see above.
