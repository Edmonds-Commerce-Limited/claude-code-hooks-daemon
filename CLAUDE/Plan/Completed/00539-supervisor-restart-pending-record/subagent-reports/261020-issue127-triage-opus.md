# Issue #127 triage: a supervisor restart is indistinguishable from a real exit at SessionEnd

Not plan work (triage only). Read-only investigation on main at 56c1ce4c1 (includes the #125 merge 605d8ed4d).
All issue content was treated as untrusted data; every claim below was re-checked against the code.

## 1. Code claims, re-located on current main

File: `/workspace/.claude/ccy/claude-supervise.py` (10446 lines; tracked, deployed via `src/claude_code_hooks_daemon/install/ccy_supervisor.py:41`).

| Issue claim (3.70.0 line)                                  | Current main                                                                                                                      | Verdict    |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Section header "Exit for restart"                          | 9056-9076 (step 4: file written "once the child has exited")                                                                      | TRUE       |
| `_RESTART_EXIT_WAIT_SECONDS` 30 s (8559)                   | 9083                                                                                                                              | TRUE       |
| `RestartCoordinator.request` (8656)                        | 9180-9249                                                                                                                         | TRUE       |
| dry-run refusal (8671)                                     | 9202-9206 (logs noop)                                                                                                             | TRUE       |
| cooldown refusal (8675)                                    | 9207-9213 (logs noop)                                                                                                             | TRUE       |
| abandon-cap refusal (8682)                                 | 9214-9215 (returns False, logs NOTHING)                                                                                           | TRUE       |
| no single session id (8684)                                | 9216-9222 (logs noop)                                                                                                             | TRUE       |
| (new since 3.70.0) already-pending refusal                 | 9200-9201                                                                                                                         | new branch |
| (new, #125) focus-hold refusal                             | 9224-9234: `_note_focus_hold` banner/log, return False; no `_PendingRestart`, no `mark_own_line_typed`, no cooldown/abandon count | new branch |
| `/exit` typed via `_perform_injection` (8692)              | 9235                                                                                                                              | TRUE       |
| request kept only in memory (`self._pending`, 8694)        | 9237-9243 (`_PendingRestart` 9121-9127; its `deadline` is MONOTONIC, 9242)                                                        | TRUE       |
| `abandon` (8708)                                           | 9251-9270; driven by `_on_poll` 9891-9910 (`restart.expired()` then `restart.abandon`)                                            | TRUE       |
| `finish` writes files after child exit (8729, called 9551) | `finish` 9272-9311; called at 10094, after `os.waitpid` at 10091                                                                  | TRUE       |
| request file / marker                                      | `restart-request.json` 9081/9099-9101; `restarted.json` 9092/9104-9106; atomic 0600 writer `_write_private_json` 9109-9118        | TRUE       |
| plugin is never told of refusal/abandon                    | `handle_plugin_outcome` 9445-9457 discards `request()`'s bool; `abandon` only logs                                                | TRUE       |

Typing failure path: `_perform_injection` (6882-6924) does no error handling; `_write_master` (9868-9869) is a raw `os.write`, so an `OSError` propagates out of `request()` into `PluginContainment.run` (9517-, trips containment, disables all plugins). Today nothing is left behind because `_pending` is set only after typing.

Child environment: the child is started with `pty.fork()` + `os.execvp(argv[0], argv)` (9845-9852), inheriting the supervisor's `os.environ` unchanged. The supervisor exports NOTHING to the child today (no `os.environ[...]=`, `putenv`, `execvpe`, or `env=` on the child spawn).

## 2. Six triage checks

1. **Built and reverted?** No. `git log --all --grep` for `restart-pending`/`#127` and `git log -S restart-pending` return nothing.
2. **Still true on main?** Yes, all claims hold (table above). #125 added two refusal branches but did not change when anything is persisted.
3. **Cluster.** #125 (merged, Plan 00537) owns the gate this must sit behind; its ruling `CLAUDE/Plan/00537-supervisor-holds-sends-off-main-focus/RULING-fable.md:87-91` requires that #127 persist the restart "only when `/exit` was actually sent, never on a hold" and that #127 rebases onto #125. #126 (wrapper interpreter prefix) touches the shell launcher/ccy.env side, not `RestartCoordinator`; no code overlap, only same-file adjacency risk if it edits the Python. Related plans: 00489 (Not Started, in-container restart primitive, also types `/exit` and waits — a future second writer of the same record), 00487 (Complete, origin of exit-for-restart), 00526 (Not Started, plugin relay result — would let plugins learn the outcome but does not solve SessionEnd timing).
4. **Partially delivered?** No. Nothing the child can read exists before exit: `restart-request.json` and `restarted.json` are written only in `finish()` after `waitpid`; `restarted.json` is consumed by the NEXT supervisor (`arm_restarted_notice` 9392-9409, called at 9805). `src/claude_code_hooks_daemon` has no reference to `restart-request`, `restarted.json` or any restart env var; the only `CCY_SUPERVISOR*` hits are the prompt-provenance marker (`utils/ccy_supervisor.py:58`) and the integrity handler id. The only state-dir env var, `CCY_SUPERVISOR_STATE_DIR` (3793, read at 4086), is an INPUT the launcher may set; the child sees it only incidentally if the launcher set it.
5. **Plan already filed?** No. `find-plan restart` (6 hits) and `find-plan supervisor` (36 hits) contain nothing on SessionEnd/restart-pending; `find-plan SessionEnd`: no match.
6. **Reporter's blocker.** Vendored `remote-docs/code.claude.com/docs/en/hooks.md` (fetched 2026-10-17): SessionEnd "Runs when a Claude Code session ends" (3572), hooks have a budget of 1.5 s up to 60 s that "applies when you exit" (3602-3605) and "can't block session termination" (3600) — i.e. they are run by the Claude Code process during its exit, so necessarily before the child exits and before `waitpid` returns at 10091. Reason values (337, 3579-3583): `clear`, `resume`, `logout`, `prompt_input_exit`, `other`. Nothing in the docs distinguishes how `/exit` arrived, and it cannot: the supervisor types into the PTY as bracketed paste + Enter exactly as a human does (6919-6924). Docs do not state which value a typed `/exit` yields (plausibly `prompt_input_exit`); not verified live, but the point holds either way because both sources produce the same input. Blocker CONFIRMED.

## 3. Daemon-side consumer

None exists. `src/claude_code_hooks_daemon/handlers/session_end/__init__.py:1-7` says the package is EMPTY since Plan 00237 removed `cleanup`. `.claude/settings.json` registers the SessionEnd forwarder (`.claude/hooks/session-end`) to the daemon only; no plugin under `.claude/ccy/plugins` or the installed plugin cache registers a SessionEnd hook. The consumers the issue has in mind (team chat / pingbus presence / coordinators) live outside this repo. So the deliverable is a supervisor-side contract; no daemon handler needs to honour it in this issue. A shared reader helper in `src/.../utils/ccy_supervisor.py` is optional future work, not required.

## 4. Design assessment

**Placement relative to the #125 gate.** Write the record in `request()` strictly AFTER the focus-hold branch (9224-9234) returns nothing, i.e. after every refusal (9200-9234), and BEFORE `_perform_injection` at 9235. "Before typing" is required, not stylistic: Enter is written 0.2 s after the paste (`_SUBMIT_DELAY_SECONDS` 6815), and Claude Code can start SessionEnd hooks immediately on Enter, so a record written after `_perform_injection` returns races the hook. This satisfies the #125 ruling: a held request returns at 9234 before any write.

**Typing failure.** Wrap `_perform_injection` so an exception removes the record and re-raises (containment still trips as today). A record-write failure (`OSError`) should be logged and the restart still proceed (finish() already treats the restart as what matters, 9309), or refuse — a design choice; proceeding keeps today's behaviour with only the signal lost.

**Child ignores `/exit`.** `abandon()` (9258) must unlink the record. Note the existing edge: if the child is still running slow SessionEnd hooks (budget up to 60 s) when the 30 s wait expires, `abandon` fires, then the child exits and `finish()` returns the plain status — no restart; that pre-existing race is unchanged and the record (already removed) correctly says "not a restart" by then.

**finish().** Should unlink the record too (not leave it for the launcher): the resumed session has the SAME session id (`--resume <id>`), so a leftover unexpired record would make a genuine `/exit` in the resumed session within the deadline look like a restart.

**Deadline.** Must be WALL-clock (`requested_at + wait_seconds`) in the record; `_PendingRestart.deadline` is monotonic (9242) and meaningless to another process.

**Env var name.** Convention is `CCY_` prefix with a module constant suffixed `_ENV` / `_ENV_VAR` (e.g. `_CCY_STATE_DIR_ENV = "CCY_SUPERVISOR_STATE_DIR"` 3793, `_CTRL_C_GUARD_ENV_VAR` 573). `CCY_SUPERVISOR_RESTART_PENDING` fits. No export mechanism exists; simplest is setting it in `os.environ` before `pty.fork()` (9845) or passing an env to `os.execvpe` in the child branch (9851, which is `pragma: no cover`, so prefer the parent-side set or a testable env-builder function).

**Directory privacy.** Record goes in `_ccy_state_dir()` (4079-4087), next to `restart-request.json`. `_write_private_json` creates it with `_PLUGIN_STATE_DIR_MODE = 0o700` (3784, 9111) and the file 0600 (9084, 9114); on this host `.claude/ccy/state` is `drwx------`. Caveat: `mkdir(exist_ok=True)` does not tighten a pre-existing looser directory; the file itself is still 0600 and written via tmp+replace.

**Optional reader hardening** (document, not enforce): a human `/clear` during the pending window yields SessionEnd reason `clear` with the record present; readers may also require reason in {`prompt_input_exit`, `other`}.

## Recommendation

Classification: **valid enhancement (feature gap in the exit-for-restart contract), confirmed on main, not delivered, no plan filed**. Not a regression. Medium-low priority; impact is false "session ended" announcements by out-of-repo SessionEnd consumers.

Smallest safe scope (supervisor only, one file plus tests):

1. `restart-pending.json` written in `request()` between the focus gate (after 9234) and `_perform_injection` (9235): `session_id`, `plugin`, `reason`, `requested_at`, wall-clock `deadline`; via existing `_write_private_json`.
2. Removed on: typing exception (then re-raise), `abandon()`, `finish()`.
3. `CCY_SUPERVISOR_RESTART_PENDING=<path>` set for the child at spawn.
4. Update the section comment 9056-9076 (and `CLAUDE/development/CcySupervisor.md` if it documents the restart contract) with the reader contract: trust only if present, `session_id` matches, deadline not passed.
5. Tests in `tests/unit/supervise/test_plugin_exit_for_restart.py` (and `test_main_focus_hold.py` for "no record on hold"): absent after each refusal branch including focus hold and the silent abandon-cap branch; present after a successful type; removed on typing failure, abandon, finish; carries own session id and wall-clock deadline; child env names the path.

Out of scope: a daemon SessionEnd handler (no consumer exists), plugin-visible outcome (Plan 00526), Plan 00489's in-container restart (should reuse the same record when built).
