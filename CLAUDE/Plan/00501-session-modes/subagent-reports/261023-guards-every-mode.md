# Guards behave identically in every mode: tests (Plan 00501)

Criterion: "Guards behave identically in every mode; no config change is needed". Closes gap (4) and gap 5 of `261023-open-criteria-evidence.md`.

Branch `worktree-501-guards-every-mode` (base e22f53086). Test commit 808f1f562. No source change: every new test passed against existing behaviour, so **no defect was found**.

## 1. `tests/integration/test_guards_identical_in_every_mode.py` (8 tests)

Path: the real `DaemonController.process_event` (mode interceptor, then the router, then the whole discovered handler chain). The fixture project's config names no handler (`handlers: {}`), so every handler runs at its own default. Each run builds a fresh controller and gets its own untracked dir.

Canonical denied calls, each pinned to the guard that must decide it with no mode active:

| Call                                      | Denier                        |
| ----------------------------------------- | ----------------------------- |
| `git reset --hard HEAD~1`                 | `prevent-destructive-git`     |
| `sed -i 's/a/b/' README.md`               | `block-sed-command`           |
| `pytest tests/ 2>&1 \| tail -20`          | `pipe-blocker`                |
| `chmod 777 README.md`                     | `block-dangerous-permissions` |
| Edit of `src/app.py` adding a type-ignore | `qa-suppression-blocker`      |
| `ls` (control)                            | allowed                       |

- `TestBaseline` and `_assert_canonical`: with no mode, each call is denied by its guard and `ls` is allowed. This guard matters. The first draft used an incomplete config, the daemon came up DEGRADED and allowed everything, and the comparison tests passed on nothing. Every comparison now re-asserts the baseline first.
- `test_verdicts_are_identical_to_the_baseline[focus|awaiting-human|goal-blocked|manual-goals|unattended]`: the (decision, decided_by) map under each mode equals the no-mode map exactly. `_assert_mode_is_live` checks first that the mode can be read where the daemon reads it (`session_policy(...).labels == (label,)`, `controller.get_mode()`), so a mode that silently failed to take effect cannot make a comparison vacuous.
- `test_usage_paused_loses_no_deny`: usage-paused ADDS a deny by design. `usage-pause-tool-gate` (terminal, first on the event) decides every call, and every call stays DENY.
- `test_usage_paused_leaves_the_guards_behind_its_gate_unchanged`: with only that gate disabled, the paused verdicts equal the baseline. The guards behind the gate are unchanged.

Not covered: a Write-tool suppression case. With default config, `block-unread-overwrite` (R-WRITE-CLOBBER) decides a Write to an existing file first, so the case uses Edit.

## 2. `tests/unit/handlers/test_session_mode_readers.py` (6 tests)

An AST scan of every module under `handlers/`. It flags imports of the mode modules (`utils.session_modes`, `utils.autonomy`, `core.session_mode_registry`, `core.focus_mode`, `core.manual_goals`, `core.goal_loop_block`, `core.session_mode_statement`, `utils.usage_pause[_gate]`) and references to the accessors (`session_modes`, `session_policy`, `autonomy_verdict`, `autonomy_allowed`, `SessionPolicy`, `SessionModeRegistry`, `displayed_policy`, `is_usage_paused`, `hook_is_usage_paused`, `active_usage_pause`).

- The set of readers must equal `MODE_READERS` exactly. That is 19 modules, each with a stated reason.
- No PreToolUse handler reads mode state, except `usage_pause_tool_gate`. That gate reads only the usage-pause record, never the registry or the policy.
- Vacuity guards: the scan covers more than 100 modules, and it finds `SessionModeRegistry` in `goal_loop_detector`.

Finding: the brief asked for "no handler outside the declared driver inventory reads the registry". That does not hold as worded. 19 modules read mode state and only 2 are in `EXPECTED_DRIVERS`. The rest are mode machinery (focus trigger, suppressor, goal-loop detector, usage-pause gates, status-line indicators), the autonomy notices, and two non-driver handlers that read the autonomy verdict or the policy:

- `background_process_tracker`: wording only.
- `idle_workable_issue_stop_gate`: a Stop gate that stands aside for a blocked or paused session. That is designed behaviour (R-STOP-IDLE-WITH-WORKABLE-ISSUE drives work).

So the test pins an explicit inventory with reasons. It does not reuse the driver list.

## 3. `tests/unit/handlers/test_new_session_after_focus.py` (20 tests), gap 5

Setup: an earlier session's focus entry is still live in the registry, and the environment allows autonomy (container).

- For a NEW session id, the real chain consults each of the 9 real `EXPECTED_DRIVERS` once.
- For a NEW session id, `FailsafeCronBlockageSuppressorHandler` delivers a declared `persistent_crons` tick with no added context.
- Control: the focused session's id still skips every driver and drops the tick, which proves the entry is live.

## QA

`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range e22f53086..HEAD --allow-unmapped` on a clean tree at 808f1f562: `QA: 41/41 PASSED`, no `❌` line, exit 0 (untracked/scratch/qa-501-gem.txt).

Head: the commit that adds this report, on top of 808f1f562 (git log of the branch).
