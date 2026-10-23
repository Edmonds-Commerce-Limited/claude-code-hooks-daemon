# Release v3.71.0 Step 7 (Opus documentation review) and Step 9 decision

Worktree `untracked/worktrees/worktree-r371-docs`, branch `worktree-r371-docs`, base `ea8259cd0` (release/3.71.0 head).

## Verdict

APPROVED after the fixes below. The open findings are fixed on this branch. Nothing is left for the coordinator except merging and the later release steps.

## Step 7 checklist

| Item                                                 | Result                                 | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Version numbers consistent                           | PASS                                   | `tests/unit/qa/test_version_bump_completeness.py`: 7 passed (venv python). `pyproject.toml:7`, `version.py:3` and the README badge all read 3.71.0.                                                                                                                                                                                                                                                                                                                                                                                |
| README stats                                         | PASS                                   | README carries only durable stats ("30,000+ tests", "95% coverage required"), and the version badge reads 3.71.0. Nothing is release-specific and stale.                                                                                                                                                                                                                                                                                                                                                                           |
| Changelog accurate and categorised                   | FAIL, fixed                            | (1) The retired `marker_expiry_hours` option was attributed to `auto_continue_stop`. It belongs to `idle_workable_issue_stop_gate` (`constants/handlers.py:1666`, `tests/unit/config/test_retired_handler_options.py:24`, and in v3.70.0 `handlers/stop/idle_workable_issue_stop_gate.py`). (2) The retired options were filed under Changed, but under the v3.70.0 precedent they belong under Removed. (3) The entry was written at `fd2cf727a`, so none of the review fixes merged since then were listed. All three are fixed. |
| Release notes comprehensive                          | FAIL, fixed                            | The notes had the same wrong handler name in three places (Read this first, Highlights callout 020, Changes). They had no section for the post-`fd2cf727a` review fixes. Both are fixed: see "Changes made".                                                                                                                                                                                                                                                                                                                       |
| Security/breaking marked                             | PASS (after Step 9 edits)              | "Read this first" states "No breaking change". The removal is now named, with the reason it is not breaking. There is no security entry and nothing in the range calls for one.                                                                                                                                                                                                                                                                                                                                                    |
| Upgrade instructions clear                           | FAIL, fixed                            | The guide `CLAUDE/UPGRADES/v3/v3.70.0-to-v3.71.0/v3.70.0-to-v3.71.0.md` has summary, steps, verification and rollback. It had the same wrong handler name, and its summary did not mention the removals. Both are fixed.                                                                                                                                                                                                                                                                                                           |
| UNRELEASED post-/pre-upgrade-tasks only README.md    | PASS                                   | `ls CLAUDE/UPGRADES/UNRELEASED/*/`: each of config-changes, post-upgrade-tasks, pre-upgrade-tasks, release-notes and truth-changes holds only `README.md`. No tasks shipped, so there is no task index to populate and no post-upgrade reference is needed.                                                                                                                                                                                                                                                                        |
| claude-code-versions.yaml entry with existing report | PASS                                   | `v3.71.0` entry: reviewed_through 2.1.309. Its `review_report` is `CLAUDE/Plan/00474-niggles-ledger-seventeen/subagent-reports/261023-claude-code-review-v3.71.0.md`, and the file exists.                                                                                                                                                                                                                                                                                                                                         |
| Moved callouts' substance in RELEASES                | PASS                                   | 27 callouts sit in `v3.70.0-to-v3.71.0/release-notes/`. Two of them are numbered 002, which is harmless. A script checked each callout's first body sentence against `RELEASES/v3.71.0.md`: 27/27 found. `UNRELEASED/release-notes/` holds only README.md.                                                                                                                                                                                                                                                                         |
| truth-changes v3.71.0 present                        | PASS                                   | `CLAUDE/UPGRADES/truth-changes/v3.71.0.yaml` (rules `paths:` vs `description`).                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| config-changes v3.71.0 present and dated             | PASS (with `removed` added for Step 9) | `date: "2026-10-23"`, with no UNRELEASED placeholder. Its recommended entries are `relay_binary_checker`, `relay_source` and `relay_enabled` (recommended_value true).                                                                                                                                                                                                                                                                                                                                                             |

Additional defects found beyond the checklist:

- `.claude/hooks-daemon.yaml.example:941` still advertised the retired `marker_expiry_hours` as a commented option of `idle_workable_issue_stop_gate`. The line is removed.
- `docs/guides/HANDLER_REFERENCE.md:4772` gave the same wrong handler name. Fixed.

## Step 9 decision: NOT breaking

- **Detection:** this check fires. With the categorisation fixed, the new CHANGELOG entry has a `### Removed` section (Step 9 detection item 1). No `@abstractmethod` was added to `Handler`, and no "BREAKING", "incompatible" or "renamed" keyword appears.
- **Decision: not breaking.**
  - RELEASING.md (Step 6, "breaking: true in a config-changes manifest halts the fleet") reserves `breaking: true` for a removal that "breaks an existing config". A non-empty `removed` list is necessary for that, but it is not enough on its own.
  - Both options are in `RETIRED_HANDLER_OPTIONS`. A config that still sets them validates, the daemon starts, and the only effect is a WARNING at startup and in `config-validate`. `tests/unit/config/test_retired_handler_options.py` passes.
  - The v3.70.0 precedent is the same shape: `upgrade_approval_guard` was retired, still validates, appears under Removed in the CHANGELOG and under `removed` in the manifest, with `breaking: false`.
- **Made consistent:**
  - CHANGELOG: `### Removed`.
  - RELEASES "Read this first", "Changes > Removed" and "Upgrade Instructions": all say removed but not breaking, and why.
  - Upgrade guide summary and "What changes" section: same.
  - `config-changes/v3.71.0.yaml`: two `removed` entries with full dotted paths (`handlers.user_prompt_submit.failsafe_cron_blockage_suppressor.options.expiry_hours` and `handlers.stop.idle_workable_issue_stop_gate.options.marker_expiry_hours`, matching the test's paths), with `breaking: false` kept.
- **ABORT condition:** none. The breaking question is answered "No", and the upgrade guide exists anyway.

## Changes made

- `CHANGELOG.md` (3.71.0):
  - Wrong handler name fixed. Retired options moved to a new `### Removed` section, and the summary line updated to match.
  - Changed: footprint `truncated` / "loads only its start" plus the contract re-audit at 2.1.309 (N535); the manual-goals message wording.
  - Fixed: session-modes registry, one-time clear attribution across a restart, exempt-straggler cap and mid-line checkpoint, relay-repair pid/reap and the banner's named defect, the lint gates' shared working dir and binary (N538), the footprint daemon-block regex, the `session_mode_indicator` pause-path error, and the ccy supervisor Meta-chord hold and untyped-clear record. The supervisor entry says explicitly that it is HOST code and takes effect only when ccy is relaunched.
- `RELEASES/v3.71.0.md`:
  - Wrong handler name fixed in three places, and "Read this first" rewritten for the removal.
  - The ccy bullet now names the two HOST-only review fixes.
  - New section "Fixes from the release review" (six bullets, including the `truncated` flag at the 40,000-character limit and the 2.1.309 contract re-audit).
  - The Changes section mirrors the CHANGELOG (Changed, Removed, Fixed).
- `CLAUDE/UPGRADES/v3/v3.70.0-to-v3.71.0/v3.70.0-to-v3.71.0.md`: handler name fixed, removal and non-breaking status stated.
- `CLAUDE/UPGRADES/v3/v3.70.0-to-v3.71.0/release-notes/020-awaiting-human-is-a-session-mode.md`: handler name fixed, so the callout matches the notes it was folded into.
- `CLAUDE/UPGRADES/config-changes/v3.71.0.yaml`: `removed` entries added.
- `docs/guides/HANDLER_REFERENCE.md`: handler name fixed.
- `.claude/hooks-daemon.yaml.example`: the retired commented option line removed.

## Verification

- The targeted run passed 473, with 1 skipped. Files: `test_config_changes_manifest_examples.py`, `test_config_migrations_integration.py`, `test_config_migrations.py`, `test_repo_hygiene_check.py`, `test_version_bump_completeness.py` and `test_retired_handler_options.py`.
- QA: see the reply that hands this branch back (`untracked/scratch/qa-r371-docs.txt`).
