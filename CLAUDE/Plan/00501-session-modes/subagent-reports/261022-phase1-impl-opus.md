# Plan 00501 Phase 1 implementation report and handoff (Opus sub-agent)

Worktree `/workspace/untracked/worktrees/worktree-501-phase1-model`, branch `worktree-501-phase1-model` (pushed).
Head at handoff: `9e53bbd21` (Task 1.1). Tasks 1.2 and 1.3 are NOT started; this agent stopped at the context budget.
Targeted QA has NOT been run yet (run it once after 1.3, as the brief says).

## Environment notes for the next agent

- There is no `python` on PATH. Use `/workspace/.venv/bin/python` with `PYTHONPATH=$PWD/src:$PWD` from the worktree
  root (verified: it then imports the worktree's `src`, not `/workspace/src`).
- Black must be run as `/workspace/.venv/bin/python -m black -q <files>` (the Python 3.11 safety warning is benign).
- Recursive greps must name explicit literal roots (`src/...`, `tests/unit`); a `$VAR` root or `.` trips the
  flaggable-content guard.
- Commits need `&&` chaining (bash safe-mode guard).

## Task 1.1: delivered

- `src/claude_code_hooks_daemon/utils/session_modes.py` (pure, no I/O):
  `SessionMode` (focus, blocked, usage-paused, unattended; `registry_owned` true for focus and blocked only),
  `BlockReason` (declared, goal-loop), `ModeSource`, `Lifetime` (daemon, session), `ModeLabel` (declared in the
  precedence order usage-paused > goal-blocked > awaiting-human > focus > unattended; `rank`, `by_precedence()`),
  frozen `SessionModeEntry` (validates: session id, expires_at > entered_at, blocked needs a reason, others refuse
  one, focus needs its task; `label`, `renewal_ttl` (focus only, `FOCUS_TTL_SECONDS` = 12 h), `is_live`,
  `renewed`), `describe_entry`, `TickAction` (deliver < deliver-naming-focus < thin < drop),
  `SessionPolicy.from_entries` (one session, each label once, held in precedence order; `drives_work`,
  `unattended_block_applies`, `focus_task`, `badge()`, `explain_clause()`, `tick_action()`), and
  `is_genuine_human_prompt` (prompt text + `EXCLUDE_CONTENT_MARKERS`, no file read).
- Tick truth table (`tick_action`, most suppressive mode wins): no mode = deliver (cadence stays the suppressor's);
  focus drops declared jobs (even `runs_while_awaiting_human`), delivers the failsafe naming the task, delivers
  watchdog/stand-in/usage-resume; blocked (either reason) drops declared jobs unless `runs_while_blocked`, thins the
  failsafe when work is owed and drops it otherwise (today's rows 2/3), delivers the rest; usage-paused delivers only
  the usage-resume tick (matches `usage_pause_gate`, which holds every other prompt); unattended changes nothing.
- Tests: `tests/unit/utils/test_session_modes.py`.
- RED evidence: `ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.session_modes'` (pytest exit 2).
  GREEN: 80 passed, module coverage 99.48% then the one missing branch was covered; mypy --strict and ruff clean.

## Task 1.2: design to implement (TDD; test file first)

Put the registry in `src/claude_code_hooks_daemon/core/session_mode_registry.py` (beside `disclosure_tracker.py`),
tests in `tests/unit/core/test_session_mode_registry.py`. Wire into `DaemonDataLayer` as a lazily built
`session_modes` property (add `_session_modes` to `__slots__`; reset in `reset()`), built from
`ProjectContext.daemon_untracked_dir() / "context-sidecar"` and calling `load()` once on first build. A
`RuntimeError` (no project context: CLI processes, most unit tests) propagates from the property; the caller in
Task 1.3 logs it at DEBUG and treats the session as having no modes (same convention as `autonomy._project_config`).

- `SessionModeRegistry(state_dir: Path, *, clock: Callable[[], float] = time.time)`, guarded by `threading.RLock`.
- File per session: `<state_dir>/<stem>.session-modes` (suffix deliberately not `.json`; reuse the stem rule from
  `utils/usage_pause._session_stem`, ideally by extracting a shared helper rather than copying it). JSON shape with
  named field constants (Phase 5 pins them to the supervisor reader):
  `{"version": 1, "session_id": ..., "modes": [{"mode", "reason", "source", "lifetime", "entered_at", "expires_at", "detail"}]}`.
  Write atomically with `utils/temp_names.unique_temp_path` + `replace`, as `write_usage_pause` does. Write FIRST,
  then update memory, so a failed write (OSError propagates: fail loud) never leaves memory and disk disagreeing.
  A session with no entries left has its file deleted.
- API: `enter(entry)` (refuses a non-`registry_owned` mode with ValueError; replaces the same label for that session),
  `exit(session_id, label) -> SessionModeEntry | None`, `active(session_id) -> tuple[SessionModeEntry, ...]`
  (expires lazily), `policy(session_id) -> SessionPolicy`, `note_prompt(session_id, prompt) -> bool` (renews
  renewable entries only when `is_genuine_human_prompt`; returns whether it was genuine; no file read, one write
  only when something renewed), `reap() -> int` (drops expired entries across sessions), `load()`,
  `take_notices(session_id) -> tuple[ModeNotice, ...]` (pop-once).
- One-time statements: `ModeNotice(kind, entry)` with `NoticeKind` EXPIRED / SURVIVED_RESTART / CLEARED_BY_RESTART
  and a `text()` built from `describe_entry`. Expiry text for focus per ruling 02: "focus expired after 12 h; type
  `hooks-daemon focus <task>` to renew". Every expiry (lazy in `active`, or in `reap`) queues exactly one EXPIRED
  notice; `take_notices` returns it once.
- `load()`: for every `*.session-modes` file: parse and validate (unknown mode, wrong types, a session id that does
  not match the file's stem, a non-registry mode, an entry `SessionModeEntry` refuses) -> on failure log at WARNING
  and rename to `<name>.corrupt` (never read as "no modes" silently; if the rename itself fails, log at ERROR and
  continue). `daemon`-lifetime entries are dropped with a CLEARED_BY_RESTART notice; surviving live entries get a
  SURVIVED_RESTART notice (ruling 01, consumed by Task 4.2); expired entries get an EXPIRED notice and are dropped;
  the file is rewritten (or deleted) to match.
- Tests to write: enter/exit/active round trip; write-through file content and field names; per-session isolation;
  thread safety (many threads entering/exiting, final state consistent); lifetime on load; restart notices once;
  TTL expiry with one EXPIRED notice; renewal by a genuine prompt and NOT by a tick / supervisor line; reap deletes
  emptied files; malformed JSON, wrong schema and mismatched session id each logged at WARNING (caplog) and renamed
  `*.corrupt`; a write failure (read-only dir) raises and leaves memory unchanged; data-layer property builds once
  from a tmp `daemon_untracked_dir` (monkeypatch `ProjectContext.daemon_untracked_dir`).

## Task 1.3: design to implement

- `utils/autonomy.py`: `AutonomyVerdict` gains `environment_allowed: bool` and `session: SessionPolicy`;
  `allowed = environment_allowed and session.drives_work`. `autonomy_verdict(..., session_modes: Iterable[SessionModeEntry] | None = None)`:
  when None, read `get_data_layer().session_modes.active(session_id)` for the payload's `session_id` (no session id
  or no project context -> no modes, DEBUG log). Usage-pause is NOT folded into the verdict in Phase 1 (it would
  change today's behaviour for a usage-paused session; it is shown, not migrated).
- `explain()`: with no mode, return today's exact text (pin it with an equality test against the current string).
  Environment allowed but a mode halts work: "AUTONOMY PAUSED FOR THIS SESSION: \<policy.explain_clause()>, so no
  crons, failsafe-recovery advice, goal injection, goal-ledger stop challenges or stand-in crons run in this session.
  Guards are unaffected." plus the mode's exit. Both: today's text + " This session is also in <clause>."
- `handlers/status_line/environment_indicator.py`: switch to `.environment_allowed` so "no autonomy" keeps meaning
  the environment (modes get their own segment in Task 4.1); test that a focus mode does not add "no autonomy".
- Route coverage tests (each with no mode = identical to today, and with a mode = suppressed): chain gate
  (`core/chain.py` `autonomy_allowed`, extend `tests/unit/core/test_chain_autonomy_gate.py`),
  `auto_continue_stop._stand_in_block` and `_goal_ledger_challenge` (two direct calls), `background_process_tracker`
  (protective advisory instead of the driving one), `autonomy_notice` (fires and explains the mode). Inject modes
  through a tmp-dir registry on the data layer (`reset_data_layer()` in teardown) so the real lookup path is tested.

## Left

Tasks 1.2 and 1.3, then the one targeted QA run
(`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped > untracked/scratch/qa-501-p1.txt 2>&1`),
commit any autofix output, tick 1.2 and 1.3 in PLAN.md, and complete this report with the QA line and head sha.
