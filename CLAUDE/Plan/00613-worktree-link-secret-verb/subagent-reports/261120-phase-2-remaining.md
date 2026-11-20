# Plan 00613 Phase 2: Tasks 2.2 to 2.5

Branch `agent-a4419afc45dbc6663-82565567`. Not merged.

## Commits

- `d53f3f31d`: Task 2.2 RED (audit tests, failing at import)
- `bb55b1f61`: Task 2.2 GREEN (`LinkAudit`, the audit log, handler wiring)
- `2f6d2e6d6`: Task 2.3 pin (hand-typed `ln -s` / `ln` / `cp` still denied)
- `cacb88a18`: `check-worktree-seed` RED (11 failing)
- `f9ea6da53`: `check-worktree-seed` GREEN (`refused_copies`)
- `544ebf23e`: example fix, release callout 009, PLAN and journal
- `23d657862`: log the unreadable protected set (QA error_hiding)
- `dae92b924`: pre-upgrade task 01, ALLOW controls for the pin
- The last commit holds plan docs only: this report and the follow-up journal entry.

## QA

- **The last complete `llm_qa.py changed` run** covered `544ebf23e` and scored 40/43:
  - All 8853 selected tests passed, with 0 failed.
  - The error_hiding failure was fixed in `23d657862`.
  - The unmapped gate failed. Two files are too broad to map: `secret_file_matching.py` and `config_cli.py`. Their direct tests passed.
- **No targeted run on the final HEAD.** The host-wide lock was held for the whole 600s wait on three attempts, and one attempt was killed with exit 144.
- **Lock-free checks on `dae92b924` are clean:**
  - `audit_error_hiding.py`
  - ruff, black and mypy on the changed source
  - the pin and the upgrade-task schema tests, 85 passed
- **What is left:** the coordinator's full gate is the confirmation still outstanding.

## Decisions

These are recorded in full in the journal entry `JOURNAL/2026-11-20/063718Z-action-6afc35.md`.

- **When links are classified.** Links are classified at placement, never at validation, so a link-only config still reads no protected set.
- **Unreadable protected set.** The link is still placed and is logged as `linked-unclassified`.
- **When the audit line is written.** It is written before the link. If the log cannot be written, the link is refused and seeding raises after `git worktree add`, so the worktree remains.
- **Linked directories.** A linked directory is judged by walking every path reachable through it.

## Open for the coordinator

- **Suggested seed candidates.** `worktree_seed_suggestions` still proposes names that look protected (the `*.secret*` shapes). The report renders those in symlink mode. Changing this is a policy choice, and it relates to the Q5 gate.
- **Report reads raw YAML.** `check-worktree-seed` reads the raw YAML, so a config that is schema-invalid elsewhere passes the report but refuses copies at creation. This is journalled and left as is.
- **Phase 3.** Phase 3 is still gated on Plan 00614, Plan 00623, live verification, and the owner's own confirmation of Q1.
