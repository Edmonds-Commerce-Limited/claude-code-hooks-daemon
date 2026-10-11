# Plan 00503 report: remove the upgrade owner-approval tier (python-developer, sonnet)

Branch `worktree-rm-upg-approval`. GitHub #112. Not pushed, not merged.

## Scope item 5: which code runs the gate

The TARGET release's code runs the gate, never the installed daemon's.

- `scripts/upgrade.sh` (Layer 1, fetched fresh from `main` by the skill shim) fetches the tags and checks the target out in `.claude/hooks-daemon` at Step 6.
- At Step 8 it runs `$DAEMON_DIR/scripts/upgrade_version.sh`, the checked-out target's own Layer 2, as a child process.
- Layer 2's `run_pre_deploy_phase` runs `$DAEMON_DIR/src/.../upgrade_gate_standalone.py` on a system Python 3.11+, before any venv is built.

So an upgrade from an older install TO this release meets no approval stop. Only an upgrade whose TARGET is still v3.68.0 or v3.69.0 prints the old stop. `CLAUDE/LLM-UPDATE.md` says to move the target to this release or later, never to approve.

## What changed

- **Gate** (`install/upgrade_gate.py`, `upgrade_gate_standalone.py`, `scripts/upgrade_version.sh`):
  - Removed `NEEDS_APPROVAL`, exit 4, `ApprovalState`, `write_approval`, `check_approval`, `run_approval`, `approve_main`, `_approval_lines`, the approval phrase and the `approval-marker=` verdict line.
  - The exit-4 handling, `consume_used_approval` and `APPROVAL_MARKER_USED` are gone from the bash.
  - A MAJOR bump, a breaking manifest, a critical task and an unreadable installed version now fold into the exit 3 reading, listed first under `READ THIS FIRST`.
  - Confirming the digest proceeds. The reading confirmation is otherwise unchanged.
- **Receipt:** the gated-install record is kept, because the "venv stamp already equals the target" check still needs it. It moved from `untracked/upgrade-approvals/` to `untracked/upgrade-gate/` (`GATED_INSTALL_SUBDIR`). `approval_key` is now `release_key`. A project with an old-path receipt is asked for the reading once on a same-version re-run that claims the target is already installed.
- **Phasing advice:** `phasing_advice()` is new. It fires on a MAJOR boundary, or more than 10 minor releases (`PHASE_MINOR_RELEASES`). It names a real intermediate release from the crossed guide dirs, prints as `ADVICE:`, and is stored in `GateReport.advisories`. It is outside the digest and sets no exit code.
- **CLI and handler:**
  - Removed the `approve-upgrade` verb, the `upgrade_approval_guard` handler, its constants, rule IDs, `init_config` entry, config and example entries, and the tests and registrations that named it.
  - Added `upgrade_approval_guard` to `RETIRED_HANDLERS`, so an old config keeps validating.
  - The guard's other rule, `R-UPGRADE-APPROVAL-ENV-BYPASS` (denied env-var steering of the upgrade and hand-moving the clone), goes with it, as the brief said "entirely".
  - Fixed one stale line in `handlers/session_start/version_check.py`.
- **`utils/one_shot_approval.py` is KEPT.** Merge-to-main and plan-close approvals still use it. It left the standalone loader list.
- **Docs and records:**
  - Rewrote `CLAUDE/LLM-UPDATE.md` (the gate section, the exit table, which-code-runs-the-gate, phasing).
  - Updated both `upgrade.md` copies (identical), `HANDLER_REFERENCE.md`, `ARCHITECTURE.md`, `upgrade-template/README.md`, `UPGRADES/README.md`, `RELEASING.md` and the UNRELEASED pre-upgrade-tasks README.
  - Hand-edited the generated `.claude/HOOKS-DAEMON.md` and the CLAUDE.md block to drop the handler (the drift test passes). The daemon was not restarted.

## Deviation from the brief

3.69.0 is already released and tagged, so the release-bound records go in `CLAUDE/UPGRADES/UNRELEASED/`, per RELEASING.md, not `v3.68.0-to-v3.69.0/`:

- release note `022-an-upgrade-no-longer-waits-for-owner-approval.md`;
- a `removed` entry (plus `renamed: []` and `changed: []`) in `UNRELEASED/config-changes/v3.70.0.yaml`;
- a new `UNRELEASED/truth-changes/v3.70.0.yaml`, reusing the id `upgrade-pre-deploy-gate`.

## Verification

- `llm_qa.py changed --base main`:
  - Pass: format, lint, mypy, pyright, docs_qa, the repo-hygiene family and sensitive_content.
  - `changed_tests`: 9548 passed, 1 failed. The failure was the generated-doc drift test; fixed afterwards and it now passes (9 passed).
  - Nine unmapped files are marked "too-broad" (CLAUDE.md, `constants/*`, `cli.py` and so on), plus the new truth-changes file, so a later `changed` run needs `--allow-unmapped`.
  - `plan_qa`: two advisories not caused by this change (a stats recount, 52 vs 53, and a stale journal on plan 00495). The stats recount may be the new plan folder's own README row.
- `tests/integration/test_upgrade_pre_deploy_phase_*.py` ran real upgrades end to end: 48 passed.
- TDD: the gate tests, including `TestPhasingAdvice`, were rewritten before the implementation.

## Round 2 (review round 1 fixes)

- Stale "the guard denies" claims reworded in `scripts/lib/python_discovery.sh` (both messages), `CLAUDE/LLM-UPDATE.md` (`--uv`), `scripts/upgrade_version.sh` (the `-p /tmp` reason kept, guard claim dropped) and `scripts/qa/check_daemon_dir_cd_in_docs.py`. A test docstring in `test_upgrade_pre_deploy_phase_placement.py` had the same claim and was fixed too.
- `phasing_advice`: a MAJOR jump now gives no advice when no release newer than the installed one is known in the current major, so `phasing_advice(empty, '3.70.0', '4.0.0')` is `[]`. Failing tests were written first; the old "generic advice" test now expects `[]`.
- `upgrade_guides.guide_target_release()` is new and parses the target through `_GUIDE_DIR_RE`, padded to a full release. `crossed_guide_dirs` and the gate both use it, and the gate's `-to-v` split is gone. `v3.57-to-v3.58` is named `v3.58.0`.
- QA: `llm_qa.py changed --base main --allow-unmapped`: 37/40 pass; `changed_tests` 9738 passed, 0 failed. The only failure is the same two `plan_qa` advisories as round 1. The first attempt failed on the host-wide QA lock and was re-run with a longer wait.
