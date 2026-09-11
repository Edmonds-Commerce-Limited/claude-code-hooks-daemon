# Plan 00378: agent asset ledger guard and backfill

**Status**: Not Started
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Main Thread

## Overview

The agent-asset subsystem (built by Plan 00279) decides whether a deployed
daemon-owned agent may be refreshed. A deployed file whose md5 is the current
bundled content is `CURRENT`; one whose md5 is in `historic_versions` is
`OUTDATED` and safe to overwrite; anything else is `CUSTOMISED` and is never
touched again. That last classification is permanent and load-bearing, so the
ledger's completeness is what separates "your edits are protected" from "your
pristine install is frozen for ever".

**The ledger is incomplete, and the test that was supposed to prevent that
cannot fail.** `ledger()` derives the CURRENT version's entry from the bundled
file itself:

```python
entries = {spec.version: content_md5(spec_source_path(spec).read_text())}
```

so `test_current_ledger_entry_matches_bundled_file` reduces to
`content_md5(file) == content_md5(file)`. Its docstring claims the opposite —
"DBF guard: editing a bundled agent without bumping its version and re-recording
its md5 must fail loudly here, never ship silently". Because nothing ever
objected, four template revisions across all three shipped agents were released
without being ledgered. Every deployment made from one of those blobs is now
frozen as `CUSTOMISED`, refused by every future upgrade, and told by the deny
message that it was hand-edited — when it was not.

This was found from the field symptom, not from the code: a `regenerate-docs`
run in the daemon's own repository accused `.claude/agents/hooks-daemon-docs-qa.md`
of being customised. It was a stale shipped blob. Recorded as Plan 00377 N10
and graduated here.

## Goals

- Editing a bundled agent template without recording its md5 fails QA loudly.
- Every revision each template has ever had is either the current content or a
  ledgered historic entry — enforced, not harvested once.
- The four already-shipped unledgered revisions are ledgered, so existing
  pristine deployments classify `OUTDATED` and upgrade instead of staying
  frozen.

## Non-Goals

- Changing the `CUSTOMISED` refusal itself. Refusing to clobber a genuinely
  customised file is correct and stays (Plan 00377 N4 added the explicit
  `--force` escape for the deliberate case).
- Making the classifier able to distinguish "user edited this" from "template
  moved on" in general. A complete ledger makes that distinction reliable for
  daemon-owned agents; the wider drift-visibility question is Plan 00377 N6.
- Repairing deployed files in client projects automatically. Ledgering the
  revisions is what lets a normal upgrade do it.

## Tasks

### Phase 1: Make the guard real

- [ ] ⬜ **Task 1.1**: Pin the current content md5 as declared DATA on
  `AgentAssetSpec` rather than deriving it from the file. `ledger()` reads the
  declared value; nothing in the comparison path may read the template again,
  or the tautology returns in a new shape.

- [ ] ⬜ **Task 1.2**: Rewrite `test_current_ledger_entry_matches_bundled_file`
  so it compares the DECLARED md5 against the file on disk, and prove it fails:
  mutate the bundled template in a temp copy and assert the check reports it.
  A guard that has never been seen to fail is not known to work — that is the
  whole lesson of this plan.

### Phase 2: Enforce completeness

- [ ] ⬜ **Task 2.1**: Add a check that walks each template's git history and
  asserts every revision's digest is either the declared current md5 or a
  ledgered historic entry. The prototype used to find this
  (`untracked/scratch/n10_ledger_audit.py`) is the reference implementation.
  CI's `qa` job checks out with `fetch-depth: 0`, so full history is available
  — confirm that before relying on it, and fail loudly rather than skipping if
  history is absent, because a silent skip is how this defect survived.

- [ ] ⬜ **Task 2.2**: Replace `test_dedupe_agent_carries_historic_versions`'s
  `len(spec.historic_md5s) >= 5` with the completeness assertion. A count check
  stays green while entries go missing, which is exactly what happened.

### Phase 3: Repair the field damage

- [ ] ⬜ **Task 3.1**: Backfill the four unledgered digests, each labelled with
  the commit that shipped it:

  | template                         | commit      | digest                             |
  | -------------------------------- | ----------- | ---------------------------------- |
  | `hooks-daemon-docs-qa`           | `129aee179` | `5185213319135de58988d4406569a250` |
  | `hooks-daemon-opus-security`     | `86e4ab319` | `c300a7ed8e89860ee908e1a6d67363d4` |
  | `hooks-daemon-plan-dedupe-scout` | `06077503`  | `19551a26c2fdffc2f00bab3b56ecf7bf` |
  | `hooks-daemon-plan-dedupe-scout` | `daa73a3c`  | `0bff2001a0aa282b98c455db1a33ab0f` |

- [ ] ⬜ **Task 3.2**: Re-run the Phase 2 check and confirm it reports zero
  unledgered revisions across all three agents.

- [ ] ⬜ **Task 3.3**: Write the release-notes callout. Audience is
  `operators`: a deployment frozen as `CUSTOMISED` by this defect starts
  upgrading again after this release with no action, and the previous
  "customised" warning about a file they never edited was wrong.

## Success Criteria

- [ ] Editing a bundled agent template without updating its declared md5 fails
  QA, demonstrated by a test that was observed failing before it passed.
- [ ] The completeness check reports zero unledgered revisions.
- [ ] `classify_agent` returns `OUTDATED`, not `CUSTOMISED`, for a deployment
  made from any of the four backfilled revisions.

## Delivery & Milestones

- Graduated from Plan 00377 N10, which holds the discovery evidence and the
  audit output.
- Parent system: Plan 00279 (Generic Agent Install Subsystem) built the ledger
  this plan repairs; it is prior art, not a duplicate.
