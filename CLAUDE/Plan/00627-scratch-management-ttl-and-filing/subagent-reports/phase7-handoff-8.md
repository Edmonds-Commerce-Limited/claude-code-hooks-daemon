# Phase 7 handoff 8 (Task 7.2 done; 7.3, 7.1, 7.4 not started)

## Done

- Task 7.2 (commit d468d815e, pushed): `idle_housekeeping_advisor.scratch_sweep_report(project_root)` reads only
  the cached inventory (`untracked/scratch-inventory.json`): due entries counted by verdict plus the `scratch-sweep`
  dry run; quiet when nothing is due and the inventory is complete; never quiet when it is incomplete, or unusable
  while `untracked/scratch/` exists. The age walk, `collect_scratch_report`, `DEFAULT_SCRATCH_DAYS` and
  `SCRATCH_RELATIVE_PATH` are gone from `utils/stale_litter.py`; `stale_scratch_days` is no longer an option
  (`removed` entry in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`; dropped from
  `.claude/hooks-daemon.yaml.example`). The handler's scratch report no longer takes the shared `ScanDeadline`.
- Tools: there is no `.venv` in the worktree. Use `/workspace/untracked/venv-workspace-py313-0d6d49c6/bin/{pytest, black,ruff,mypy,pyright}` with `PYTHONPATH=src` from the worktree root.
- A sub-agent launched with another cwd must call `EnterWorktree` with this worktree's path before Edit/Write, or
  `subagent_worktree_write_guard` denies every edit here.

## Next: Task 7.3 (design worked out, nothing written)

- New docs QA check `untracked-evidence-citation` in `src/claude_code_hooks_daemon/docs_qa/checks/`, registered in
  `checks/__init__.py` `all_checks()`. Template: `plan_promotion_disposition.py` (STAGED) or
  `unlisted_fake_value.py` (`_run_edit` uses `context.file_path`, `file_content`, `file_content_before`).
- Proposed contract: EDIT stage, markdown only, Severity.ADVISE; flag a line NEW in this edit (absent from
  `file_content_before`), outside fenced code blocks, that names a file path under `untracked/` (has a file
  extension; a bare directory such as `untracked/scratch/` is an instruction, not evidence) AND an evidence word
  (evidence, source, measured, findings, results, verified, proof). Remediation: copy the figures into the tracked
  doc, or file the artefact into the plan folder (`subagent-reports/`), because untracked files expire (scratch 24h).
- Add a row to the check table in BOTH `CLAUDE/core/DocumentationStrategy.core.md` and
  `src/claude_code_hooks_daemon/install/templates/core/DocumentationStrategy.core.md` (they are byte-identical; R9
  "Plan citations are provenance, not storage" is the nearest rule). Test file
  `tests/unit/docs_qa/checks/test_untracked_evidence_citation.py`; build contexts with
  `CheckContext(project_root=..., policy=DocumentationPolicy(), file_path=..., file_content=..., file_content_before=...)`.

## Then

- Task 7.1: read Plan 00560 Task 2.1/2.3 state first (`bin/hooks-daemon find-plan 560`); edit the DESIGN section 12
  places at `src/` originals.
- Task 7.4: `CLAUDE/UPGRADES/UNRELEASED/release-notes/017-scratch-sweep-dry-run-and-untracked-ttls.md` still says
  the sweep is "a report only in this release", which is now false (Phases 3 to 6 added `--apply`, caps, the
  SessionStart handler, R-SCRATCH-CAP, R-SCRATCH-KEEP-MARKER). Next free note number is 020. The config-changes
  manifest has `scratch` added entries only for TTLs/sweep; the `scratch.caps`, `scratch.archive`, `scratch.keep`,
  `scratch.filing` keys and the new handlers still need entries.
- Carried over from handoff 7: Task 6.2 needs an owner decision; 6.3 blocked on 00623; the module docstring of
  `tests/unit/daemon/test_cli_scratch_apply.py` still says `--apply` runs only in the main checkout.
