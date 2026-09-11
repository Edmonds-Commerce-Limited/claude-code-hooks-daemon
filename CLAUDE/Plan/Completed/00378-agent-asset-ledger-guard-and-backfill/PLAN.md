# Plan 00378: agent asset ledger guard and backfill

**Status**: Complete
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

**The ledger was incomplete, and the test that was supposed to prevent that
could not fail.** `ledger()` derived the CURRENT version's entry from the
bundled file itself:

```python
entries = {spec.version: content_md5(spec_source_path(spec).read_text())}
```

so `test_current_ledger_entry_matches_bundled_file` reduced to
`content_md5(file) == content_md5(file)`. Its docstring claimed the opposite —
"DBF guard: editing a bundled agent without bumping its version and re-recording
its md5 must fail loudly here, never ship silently". Because nothing ever
objected, four template revisions across all three shipped agents were released
without being ledgered. Every deployment made from one of those blobs was
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

- [x] ✅ **Task 1.1**: Pinned the current content md5 as declared DATA on
  `AgentAssetSpec` rather than deriving it from the file. `ledger()` reads the
  declared value. `classify_agent` deliberately still compares against the
  actual file, so a stale declaration can never break a live install — the
  declaration's only job is to be checked, which is what makes it a witness
  rather than a second source of truth.

- [x] ✅ **Task 1.2**: Replaced the tautological check. The comparison moved
  out of the test into `unpinned_agents()`, so the failure path is exercised
  through the same function QA calls rather than an inline comparison that can
  drift from it. Observed failing on a spec carrying a wrong digest before
  being accepted.

### Phase 2: Enforce completeness

- [x] ✅ **Task 2.1**: `tests/integration/test_agent_ledger_completeness.py`
  walks each template's git history and asserts every revision's digest is
  either the declared current md5 or a ledgered historic entry. It FAILS rather
  than skips when history is unavailable, and asserts the checkout is not
  shallow — a history check that silently no-ops on a shallow clone is this
  same defect one layer out. CI's `qa` job uses `fetch-depth: 0`.

- [x] ✅ **Task 2.2**: `test_dedupe_agent_carries_historic_versions`'s
  `len(spec.historic_md5s) >= 5` replaced by the completeness assertion. A
  count check stays green while entries go missing, which is exactly what
  happened.

### Phase 3: Repair the field damage

- [x] ✅ **Task 3.1**: Backfilled the four unledgered digests, each labelled
  with the commit that shipped it so the claim stays checkable:

  | template                         | commit      | digest                             |
  | -------------------------------- | ----------- | ---------------------------------- |
  | `hooks-daemon-docs-qa`           | `129aee179` | `5185213319135de58988d4406569a250` |
  | `hooks-daemon-opus-security`     | `86e4ab319` | `c300a7ed8e89860ee908e1a6d67363d4` |
  | `hooks-daemon-plan-dedupe-scout` | `06077503`  | `19551a26c2fdffc2f00bab3b56ecf7bf` |
  | `hooks-daemon-plan-dedupe-scout` | `daa73a3c`  | `0bff2001a0aa282b98c455db1a33ab0f` |

- [x] ✅ **Task 3.2**: The completeness check reports zero unledgered
  revisions, and the independent prototype written before any of this code
  existed (`untracked/scratch/n10_ledger_audit.py`) agrees — a second opinion
  sharing no code with the test.

- [x] ✅ **Task 3.3**: Release-notes callout written to the holding area.

## Success Criteria

- [x] Editing a bundled agent template without updating its declared md5 fails
  QA, demonstrated by a test that was observed failing before it passed.
- [x] The completeness check reports zero unledgered revisions.
- [x] `classify_agent` returns `OUTDATED`, not `CUSTOMISED`, for a deployment
  made from any of the four backfilled revisions — asserted by deploying each
  historical blob into a temp project and classifying it for real, not by
  checking that a digest is present.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/30-frozen-agent-deployments-upgrade-again.md`
  (audience `operators` — affected deployments start upgrading again with no
  action needed, and the "customised" warning they saw was wrong).

## Delivery & Milestones

- Graduated from Plan 00377 N10, which holds the discovery evidence and the
  audit output. The symptom surfaced during Plan 00377's N7/N8 work
  (`abaa876f`), was recorded in `e64a6577`, and this workspace's own frozen
  agent was restored in `9a4bb0c9`.
- Parent system: Plan 00279 (Generic Agent Install Subsystem) built the ledger
  this plan repairs; it is prior art, not a duplicate.
- Every guard in this plan was watched FAILING on a deliberately broken input
  before being accepted — the one discipline that would have prevented the
  original defect.
