# N286 - main CI red after N264/N266 (three tests)

Branch `worktree-ci-red-n264-n266`. Ledger entry: N286 in NIGGLES.md.

## Fixes

1. **Playbook probe #104** (`root_recursion_guard.py` `get_acceptance_tests`). No
   AcceptanceTest field expresses "another handler legitimately denies this probe"
   (`harness_cannot_produce` marks a probe untriggerable, which this is not). The probe
   command changed from `false && grep -rl "needle" "$CLAUDE_PROJECT_DIR"` to
   `false && grep -rl "needle" src`: a project-relative literal root that
   `flaggable_content_channel_guard` can place and that reaches no flaggable path, so the
   full daemon allows it and the root-recursion guard still exercises its allow path for a
   project-scoped recursive scan. The variable root stays pinned by
   `tests/unit/handlers/pre_tool_use/test_root_recursion_guard.py` (line ~106). Any
   expansion root with a recursive search is unplaceable for the flaggable guard, so no
   variable-rooted shape can be allowed there.
2. **Blindness census**. `SubagentWorktreeWriteGuardHandler` recorded as BLIND (it reads
   only `file_path`/`notebook_path` of Write/Edit/NotebookEdit; a Bash redirect, tee,
   heredoc, cp or mv into a sibling worktree is never seen). Resident guidance in
   `get_claude_md` now states only those three tools are judged and that a clean Bash write
   proves nothing. It did not claim unconditional blocking before, so it was extended, not
   corrected, and the handler is not added to `_CORRECTED_UNIVERSAL_CLAIM`.
3. **Skip-list checker**. `flaggable_content_channel_guard.py:509` tested a character
   class, not a skip list; `_SHELL_EXPANSION_CHARS` (a string) became
   `_SHELL_EXPANSION = re.compile(r"[$`\]")`used with`.search(path)\`. Same behaviour.

## Evidence

- RED (venv imports main `/workspace/src`): `test_no_keyed_handler_lacks_a_recorded_verdict`
  and `TestTheCurrentTree::test_the_real_tree_is_clean` failed (2 failed, 89 passed).
- GREEN (worktree, `PYTHONPATH=$PWD/src`, printed `__file__` is the worktree's src):
  blindness census, skip-list checker tests, root_recursion_guard, flaggable guard,
  subagent_worktree_write_guard and tests/unit/daemon/test_playbook_harness: 382 passed.
- Direct handler check (`untracked/scratch/chain_check.py`, cwd = project root): the old
  probe matches the flaggable guard (denied); the new probe matches neither guard.

## QA

ruff, black --target-version py311, mypy: clean on touched files. pyright: one error,
`Import "pytest" could not be resolved` in the touched test file (environment: pyright does
not see the venv's pytest; the src files are clean). audit_error_hiding, check_input_contract,
check_skip_list_substring: pass.

## Not verified

- `tests/acceptance/test_playbook_harness.py` itself: all 5 tests skip without a live daemon
  socket in the worktree. Probe #104's new allow outcome is verified only by the direct
  two-handler check and unit tests, not by the full chain (lsp_enforcement and other
  handlers were not exercised; the pattern and shape of the probe are otherwise unchanged).
- The auto-generated resident-guidance block in CLAUDE.md is regenerated on daemon restart;
  not regenerated here.
- Full suite not run (coordinator's gate).
- Observation: the root-recursion guard's own deny text recommends `grep -rl "x" "$CLAUDE_PROJECT_DIR"`, which the flaggable guard now denies when enabled. Not changed.
