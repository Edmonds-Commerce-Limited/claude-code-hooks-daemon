# Plan 00501 Phase 4 implementation report (Opus sub-agent)

Worktree `/workspace/untracked/worktrees/worktree-501-phase4-visibility`, branch `worktree-501-phase4-visibility`
(pushed). Base `01087c155`, head `a8bcb2560`. Tasks 4.1, 4.2 and 4.3 are ticked in PLAN.md. The plan stays In
Progress. Nothing is merged, and the daemon was not restarted.

## Task 4.3: transition log and `mode-history`

- **`core/session_mode_log.py`**:
  - It defines `ModeTransition`, `TransitionAction` (`enter`, `exit`, `expire`, `restart-clear`), `TransitionLog`
    and `TransitionLogError`.
  - The log is `session-mode-transitions.jsonl` under the daemon untracked dir. It holds at most 500 records, and each
    append rewrites it atomically through `unique_temp_path` and a rename.
  - An unreadable or malformed log raises `TransitionLogError` when read. An append over a corrupt log renames it
    `*.corrupt`, logs a WARNING and starts a fresh log.
- **Registry** (`core/session_mode_registry.py`):
  - It takes an optional `transition_log`. `enter` and `exit` accept `evidence=`; without it, the log names the
    entry's source.
  - Expiries, restart clears and expiries at load are logged automatically.
  - A failed log append is logged at WARNING and not raised, because the mode change has already been committed.
  - New members:
    - `snapshot()`: every session's live modes.
    - `loaded_at`: raises before `load`.
    - `claim_first_prompt(session_id)`: True once per session.
- **Evidence at every production call site**:
  - The prompt command and IPC, through `enter_focus`/`exit_focus(evidence=)`.
  - The `auto_continue_stop` declaration.
  - The suppressor's exit on a human prompt.
  - The legacy-marker import.
- **Wiring**: `data_layer.session_modes` builds the registry with the log.
- **IPC action `get_mode_history`** (`SessionModeIPC`, with `KEY_LIMIT`, `KEY_SESSIONS`, `KEY_TRANSITIONS` and
  `DEFAULT_HISTORY_LIMIT=20`):
  - It returns every session's live modes and the newest transitions, optionally for one session.
  - A bad limit is an error, and so is a blank session.
  - A missing log is an error ("no transition log"), and so is an unreadable one ("transition log unreadable").
- **CLI `hooks-daemon mode-history [--session] [--limit] [--json]`**:
  - It is registered beside `session-mode` and shares the new `_send_session_mode_ipc` helper.
  - A daemon error or a malformed transition exits 1.
  - The `/mode` SKILL.md names it.

## Task 4.1: status segment

- **The segment**: `handlers/status_line/session_mode_indicator.py` renders `| ⚑ <top mode> +N`. When focus is the
  top mode, its task is shown, shortened to 32 characters. The colour depends on the top label.
- **`utils/session_modes.displayed_policy`** composes three sources:
  - registry entries, from memory (no file read);
  - usage-paused, from the session's pause record, read through `MtimeCachedFile` with the new public
    `usage_pause.parse_usage_pause`;
  - `unattended`, from `get_controller().get_mode()`.
- **Named errors**: an unreadable registry renders a red `⚑ modes unreadable`, and a malformed pause record renders a
  red `⚑ usage-pause record unreadable`. Both are logged at WARNING.
- **`explain_segment`** names every label and the precedence.
- **Registration**:
  - `HandlerID.SESSION_MODE_INDICATOR` and `Priority` 18.
  - `.claude/hooks-daemon.yaml` and `.example`.
  - `init_config.py`.
  - `HANDLER_REFERENCE.md` and `CLAUDE/Architecture/StatusLine.md`.
  - The guidance coverage test.
  - The completeness count, raised from 18 to 19.
  - `.claude/HOOKS-DAEMON.md`, regenerated with `regenerate-docs --project-root`.

## Task 4.2: restart re-statement

- `core/session_mode_statement.pending_mode_statement` is now the only caller of the pop-once `take_notices`. A
  source-scan test pins this.
  - `focus_mode_trigger` calls it on every prompt, whether or not it is a focus command (machine ticks included). It
    returns ONE `SESSION MODE:` line, joined by `;`.
- **What the line covers**:
  - The registry notices: expiries, and what survived or was cleared by a restart.
  - A usage pause recorded before the restart. This is the part the registry does not own. It is detected with
    `paused_at < registry.loaded_at` and checked once per session through `claim_first_prompt`.
  - "the daemon is in unattended mode", added only when the line reports a restart.
- The usage pause and the daemon mode are read lazily, so an ordinary prompt reads neither.

## Red and green

| Area                | Red                                                                                                | Green                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Log                 | `p4-red-log.txt`: ModuleNotFoundError                                                              | `p4-green-log.txt`: 23 passed, 99.3%                        |
| Registry            | `p4-red-registry.txt`: 7 failed, 6 errors                                                          | `p4-green-registry.txt`: 102 passed                         |
| IPC/focus/datalayer | `p4-red-ipc.txt`: 9 failed                                                                         | `p4-green-ipc.txt`: 84 passed, `session_mode_ipc.py` 100%   |
| CLI                 | not captured (the test module was written before `cmd_mode_history` existed)                       | `p4-green-cli.txt`: 26 passed                               |
| 4.1                 | `p4-red-41.txt`: ModuleNotFoundError                                                               | `p4-green-41.txt`: 171 passed, segment and model 100%       |
| 4.2                 | `p4-red-42.txt`: ModuleNotFoundError; `p4-red-42-trigger.txt`: 2 failed, 4 errors                  | `p4-green-42*.txt`: 39 passed, trigger 100%, statement 100% |
| Wider set           | `p4-wide.txt`: 1 failed (a test double lacked `evidence=`), then fixed (`p4-stop.txt`: 191 passed) | 12368 passed in the wider run                               |

All files are under `untracked/scratch/` in the worktree.

## The cov-only failures (`TestCmdRestartModeAdvisory`)

- **Root cause.** After a successful start, `cmd_restart` calls
  `_warn_if_venv_not_built_for_source(get_project_path(None))`. That validates and loads the REAL checkout's
  `.claude/hooks-daemon.yaml` and venv lock. So three tests depended on the repository they ran in, which is a test
  isolation defect.
- **Why it only failed under `--cov=...daemon.cli`.** PyYAML's libyaml `CSafeLoader` composes every node with tag
  `None` ("could not determine a constructor for the tag None") whenever coverage's `--source` names a dotted MODULE.
  - This reproduces with no project code at all: `coverage run --source=yaml.cyaml` on a script that only calls
    `yaml.load("a: 1", Loader=yaml.CSafeLoader)`.
  - `--source=<package>`, a nonexistent name and `--branch` are fine.
  - The cause is upstream, in libyaml or coverage, not in the daemon. It is not fixed here.
- **Fix** (`80076747c`): an autouse fixture in the class patches `get_project_path` and
  `_warn_if_venv_not_built_for_source`, which have their own tests. Result: 19 passed with the module-scoped `--cov`,
  and 19 passed without it. There are no suppressions or skips.

## QA

The one targeted run was
`llm_qa.py changed --range 01087c155..HEAD --allow-unmapped` at `83b57bcbd`. Its summary line was
**`QA: 37/41 PASSED, 2/41 FAILED, 2/41 NOT MEANINGFUL (detector failed: format, lint)`**.

- **format**: the autofix rewrapped 4 files during the run.
- **lint**: B018 in the new registry test (`_ = registry.loaded_at`).
- **changed_tests**: 8062 passed, 0 failed, 5 skipped. It is marked NOT MEANINGFUL only because format and lint
  failed.
- type_check, pyright, docs_qa, plan_qa, doc_truth, generated_doc_drift and handler_reference all passed.

The two failed checks were then re-run on their own:

- `ruff check` passes on the touched trees.
- `black --check src tests` reports no changes needed.
- The 5 reformatted test modules pass (238 passed).

These fixes were committed in `a8bcb2560`.

## Left

- Phase 5 (the supervisor) is not touched.
- `get_mode_history` reads the daemon's in-memory registry, so `mode-history` needs a running daemon (the same as
  `session-mode`).
- The libyaml and coverage interaction above could be raised upstream. The suite's package-scoped `--cov` does not
  trigger it.
