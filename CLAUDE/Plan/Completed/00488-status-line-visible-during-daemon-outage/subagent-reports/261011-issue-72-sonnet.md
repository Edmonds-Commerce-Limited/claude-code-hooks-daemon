# Report: GitHub #72, status line visible during daemon outage (Plan 00488)

Worktree: worktree-issue-72-sl. Commits say "Addresses #72"; nothing pushed or merged.

## Phase 1 (Tasks 1.1-1.3): done

- RED/GREEN: new `EventIDMeta.daemon_down_exit_code` (default 1) in `constants/events.py`; STATUS_LINE sets 0. `_render_raw_stdout_daemon_down_block` emits `exit {meta.daemon_down_exit_code}`.
- Tests: `test_forwarder_generator_raw_stdout.py` (status-line now `exit 0`, worktree-create keeps 1, a catalogue test pins the rule: display = 0, value = 1). Two other tests pinned the defect and were changed: `test_forwarder_status_line_loading.py`, `test_status_line_loading_while_daemon_starts.py`.
- Regenerated `.claude/hooks/status-line` (exit 1 -> exit 0) and `.claude/hooks/worktree-create` (comment only; exit unchanged).

Every event's resulting daemon-down exit code:

| Event kind                               | Exit | Changed?           |
| ---------------------------------------- | ---- | ------------------ |
| status-line (raw_stdout, display)        | 0    | yes, was 1         |
| worktree-create (raw_stdout, value)      | 1    | no                 |
| every JSON-decision event (all the rest) | 0    | no, path untouched |

Only two events are `raw_stdout`; the rewrite applies to nothing else.

## Phase 2 (Tasks 2.1-2.3): done

- `init.sh` (`.claude/init.sh` is a symlink to it, so there is no second copy to sync) sets `_HOOKS_DAEMON_STATUS_DOWN_TEXT` in `ensure_daemon`: venv building (self-heal state started or running), venv missing (any other state, and an orphan venv), version mismatch. Not provisioned was already there. Texts are three constants beside the variable.
- Tests: new `tests/integration/test_init_sh_status_down_text.py` (drives the real ensure_daemon). `test_init_sh_needs_provision.py::test_a_venv_less_clone_...` pinned the generic marker for a state that now has its own text; updated.
- Docs: new table in `CLAUDE/Architecture/StatusLine.md` (Troubleshooting) as the canonical home. `status-line-explained` describes segments, not down texts, so nothing there needed changing.

## Task 3.3: already satisfied by N371

`mkplan.bash` (and its template) already advances a lagging counter to the disk maximum rather than refusing (batch K, N371). Added regression tests in `test_mkplan_counter_drift.py` for the issue's shape (counter 414, plan 487 in Completed/) and for forward-only movement. I could not reproduce a refusal; the field report was likely an older deployed script.

## Also

Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/023-...md`. Plan checkboxes ticked (1.1-1.3, 2.1-2.3, 3.3), header set to In Progress. Targeted QA: pytest on touched areas, black, mypy, shellcheck, `llm_qa.py changed`: see the final reply for the last result.

## Remaining (out of scope, not done)

Task 3.1 (fresh-clone acceptance test), Task 3.2 (build-window policy, owner decision), Task 4.1 (live session check), Task 4.2 (push, issue comment and close).
