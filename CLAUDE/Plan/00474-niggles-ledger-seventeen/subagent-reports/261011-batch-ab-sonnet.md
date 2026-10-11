# Plan 00474 batch AB: N409 residuals, N409 protected paths, N393

Branch `agent-af1c12470409e5406-40cbc5fa`. Test first throughout; the new N409 tests were 62 red before the change.

## 1. N409 residuals (`subagent_full_qa_blocker.py`)

All five shapes now deny when they run a full QA, and the targeted forms of each stay allowed.

- **List edits.** A change to a tracked list now carries an optional edit function, applied in `_states_after` in the same single pass as `.append`/`.extend`/`+=`: `.insert(i, x)` (literal index; otherwise the item lands at the end), `.pop()`/`.pop(i)` (literal index; otherwise nothing is removed), and `a = a + [...]` / `a = [...] + a` (a spliced `+` chain that names the target once). `d.pop("key")` is no list change. `_grown_list` became `_changed_list`; an edited list passes nothing on by itself (`_process_arguments`, `_bindings`), as a grown one does.
- **Standalone literals.** `_ListState` records the list literal and the splice values built since, so only the value in effect at a running call is set aside from standalone judging. The set-aside is shared and incremental, so it stays linear. This also removes an existing false deny: a list grown to a targeted run and then passed to `os.exec*`, `pty.spawn` or `create_subprocess_exec(*a)` used to be judged as its bare first literal.
- **`os.exec*` and `pty.spawn`.** `execv/execve/execvp/execvpe` take the program from the call's path (else the list's first word) and the argv from the second argument: a tracked list, or a literal. `execl/execle/execlp/execlpe` share the asyncio spread path, dropping argv0 and, for the `e` forms, the trailing env. `spawn` joins `_ARGV_SINKS`.
- **`f = open(p); exec(f.read())`** and `p = Path(p); exec(p.read_text())` are named files, like the `with open(p) as f` form.
- **Budget.** The 64-word cap and the charge to the parse meter are unchanged. Batch X perf probes on this branch: `perf.py 1500` alias_chain 0.14 s, the rest 0.00 s (over the parse cap); `perf2.py` 0.17 s, 0.21 s, 0.36 s. New shapes at 2500 edits each followed by a run: insert 0.42 s, pop 0.39 s, prepend 0.52 s, splice 0.51 s, exec 0.53 s, open/exec 0.60 s. The timing tests added are under the 1.5 s the existing ones use.
- **Batch X reviewer probes** (`test_probe_x*.py` against this branch): 18 fail, down from 22 on the batch X branch. No probe fails that passed before. Four now pass (`append_execvp`, `append_pty`, `insert`, `pytest_removed_target`); the 18 left are known residuals (copy/slice/tuple, `' '.join`, attribute lists, parameters) and the existing parameter false denies.
- **Restart idiom.** `os.execv(sys.executable, [sys.executable] + sys.argv)` is judged exactly as `subprocess.run([sys.executable] + sys.argv)` is (pinned by a test).

Left unfixed, as before: `cmd.extend(other_named_list)`, a grown list returned from a function, `' '.join(grown)` run with a shell, grown attribute lists, `list(a)`/slice/tuple copies, `**kw`, `os.spawn*`, an asyncio program given by keyword.

Four allowed `n409-python-heredoc-*` rows (insert, concatenation, `execvp`, `pty.spawn`, all targeted pytest) were added to `tests/fixtures/ordinary_command_corpus.yaml`.

## 2. N409 protected paths

`_read_new` asks `secret_file_matching.path_is_protected(target, resolve_configured_patterns())` first (the accessor `lint_on_edit` and the other readers use; it resolves the real path, so a symlink to a protected file is caught). A protected file returns `_UNSEEN_CODE` without being opened, so every route that reads a file by name (`python3 <path>`, in-process read and run, `runpy.run_path`, the `f = open(...)` and `with` forms) follows the handler's `unseen_policy` for an unreadable script. Tests (`TestAProtectedFileIsNeverRead`) patch the configured globs to `*.sealed` and make `Path.open` fail the test if that file is opened; they also cover a symlink, an unprotected control, and the shipped defaults. No protected path was read or named in a command.

## 3. N393

Instantiated every handler and kept those with more than one rule (22). Read each deny site. Each now sets `rule=` (not `under_rule`, which would print the `BLOCKED [id]` headline a second time): `ancestry_preserving_merge`, `conflict_marker_commit_gate` (finding, unchecked, timed out), `github_issue_assignment_guard`, `host_command_guard`, `pipe_blocker` (four deny paths), `reference_repo_freshness` (`_verdict` takes the rule), `secret_file_guard` (both paths), `security_antipattern`, `self_matching_process_probe`, `upgrade_approval_guard`, `validate_instruction_content`, `validate_eslint_on_write` (3), `markdown_organization` (3), `npm_command` (2), `plan_number_helper` (3), `sensitive_content` (2) and `auto_continue_stop` (5). Already complete: `destructive_git`, `failsafe_cron_blockage_suppressor`, the rest of `auto_continue_stop` and `sensitive_content`. Single-rule handlers get it from the chain. Still null: `ancestry_preserving_merge`'s unreachable defensive fallback. Each handler's existing test file asserts `result.rule` on its deny paths.

## Counts and QA

- `tests/unit/handlers` + `tests/unit/core` + the corpus gate: 20148 passed, 1 failed (below). Earlier run of `tests/unit/handlers/pre_tool_use` + the gate: 11431 passed. Final re-run of the handler test file and the gate after the corpus rows: 1799 passed; the other three corpus consumers: 297 passed.
- black (formatted 3 files), ruff on `src/.../handlers` and `tests/unit/handlers`, `mypy src` (718 files), pyright on the touched files (with the shared venv's interpreter), `scripts/qa/audit_error_hiding.py`, `check_magic_values.py`: all clean.
- **One failure, not caused by this batch (new ledger entry N413):** `test_safety_handlers_hostile_input_performance.py::...[nesting]` reports `PipBreakSystemHandler cost grew 41x for 8x input` on the main checkout, and 45x to 46x here, alone and in the full run. It is outside this batch's files; not fixed.

## Notes for the coordinator

- The ledger entry number N413 is the next after N412 on this branch; other batches may have taken it.
- Daemon restart (the handlers load at start) is the coordinator's.
