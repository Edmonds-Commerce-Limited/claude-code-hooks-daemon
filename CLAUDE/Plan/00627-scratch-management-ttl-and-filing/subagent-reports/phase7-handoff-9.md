# Phase 7 handoff 9 (7.3 done; 7.1 slice 1 done; 7.4 partly done)

## Done

- Task 7.3 (commits 014a4dfe5 and the follow-up): docs QA check `untracked-evidence-citation`
  (`src/claude_code_hooks_daemon/docs_qa/checks/untracked_evidence_citation.py`), EDIT stage, ADVISE, never blocks.
  It skips documents under `untracked/`, fences, bare directories. Table row in both `DocumentationStrategy.core.md`
  copies (R9).
- Task 7.1 slice 1 (98b034c3b): `SCRATCH_LIFECYCLE_GUIDANCE` in `utils/scratch_dir.py`, which states DESIGN section 12's
  three points and Plan 00560 Task 2.1's wording. `project_containment` rule `fix`, `verbose` and `get_claude_md` use
  it. Plan 00560 had no branch or worktree; its PLAN.md was not edited. Tell its owner that 00627 carried Task 2.1's
  wording.
- Task 7.4 (partial): note 017 no longer says "report only". It now covers `--apply` behind a typed TTY confirmation,
  restore and keep. Note 020 covers the new check and the guidance. The v3.77.0 manifest has entries for `scratch.caps`,
  `scratch.sweep.unowned_entry`, `scratch.archive`, `scratch.keep` and `scratch.filing`, and the stale "read-only"
  wording in the `scratch` entry is fixed.

## Remaining

- 7.1: use `SCRATCH_LIFECYCLE_GUIDANCE` (or matching wording) in `pipe_blocker` guidance, the `plan_journal_guard` rule
  fix, `subagent_context_budget` handoff text and `DEFAULT_HANDOFF_GLOBS` (a behaviour change, so it needs a test),
  the `curl_pipe_shell` example and `issue_report/reproduction.py`. Then update `install/templates/PlanJournalling.md`,
  `core/PlanWorkflow.core.md`, `mkplan.bash`, the `src/.../skills/**` files (`git grep -c untracked/scratch -- src`
  lists them), and the probe/harness guidance ("fixture trees go in a `scratch new` entry; remove your tree when done").
  Leave 7.1 unticked until every one is done.
- 7.4: handler guidance (`get_claude_md`) and `docs/` for the scratch handlers (scratch_sweep, scratch_cap_guard,
  scratch_unowned_entry, scratch_keep_marker_guard, scratch_inventory_refresher), checked against what exists.
  Release notes for the caps and keep-marker handlers, if 017 is not enough.
- Pre-existing failure, not caused here: `tests/integration/test_documented_commands_are_not_self_denied.py` flags
  `docs/guides/HANDLER_REFERENCE.md:1340` (`touch untracked/scratch/<session>/probe/.scratch-keep`, denied by
  project_containment). The `test_project_containment.py` polluter/victim child-pytest test hit an INTERNALERROR at
  child session start in this venv. That looks environmental.
