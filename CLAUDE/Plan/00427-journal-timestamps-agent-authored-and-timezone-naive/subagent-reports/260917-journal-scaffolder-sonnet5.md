# Plan 00427 Phase 2 — `mkplan.bash --journal` implementation report

**Worktree**: `untracked/worktrees/worktree-j427` (branch `worktree-j427`, off `main` at
`baddc0dd`). Not merged — left for the owner to review and merge.

## What was built

1. **`mkplan.bash --journal <plan-number> <category> <body-file> [--ref R] [--title T]`**
   (`CLAUDE/Plan/mkplan.bash`, mirrored byte-for-byte in
   `src/claude_code_hooks_daemon/install/templates/mkplan.bash`):

   - Reads the clock itself via `date -u`, never accepts a time argument (D2).
   - Normalises to UTC for both the day-file's date component and the entry's
     `HH:MM` (D3).
   - Creates today's UTC day-file from `_JOURNAL_TEMPLATE_.md` when absent;
     otherwise only ever appends (D4).
   - Validates the category against a fixed array (`action finding decision thought blocker handoff`) mirrored from the template's grammar prose (D5).
   - All validation (plan-number shape, category, body-file existence/non-empty,
     plan-folder lookup, `_JOURNAL_TEMPLATE_.md` presence) happens before any
     filesystem mutation — a rejected call writes nothing.
   - Does **not** call `acquire_lock` and never touches
     `hooksdaemon.latestPlanNumber` (D6a). Implemented by extracting the
     existing plan-dir self-location logic into a shared `resolve_plan_dir()`
     function, reused by both the plan-creation path and `--journal`.
   - The existing plan-creation flow's own first journal entry (the "plan
     scaffolded" seed) was switched from local `date` to `date -u` too, so
     every day-file the scaffolder ever produces is consistently UTC under the
     sentinel's promise.

2. **Sentinel (D1)**: one line added to `_JOURNAL_TEMPLATE_.md`'s preamble
   (`CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`, mirrored in
   `src/claude_code_hooks_daemon/install/templates/_JOURNAL_TEMPLATE_.md`):
   `` _Scaffolded by `mkplan.bash`; timestamps in this file are UTC._ `` — plus
   an update to the grammar bullet that used to say "local 24h", now stating
   UTC and naming the sentinel's absence as the legacy marker. Since the
   template is rendered exactly once per day-file (creation only; every later
   append is body-only), a file can never accumulate a second sentinel line —
   pinned by test (`test_a_second_append_the_same_day_adds_no_extra_sentinel`,
   `test_the_template_preamble_is_written_only_once_ever`).

3. **Tests**: `tests/unit/scripts/test_mkplan_journal.py`, 20 tests, real `bash`
   subprocess against a real temp git repo (mirrors the existing
   `test_mkroutine_scaffolder.py` pattern). Covers: D5 validation (each
   rejection asserted to write nothing), D6a counter/lock isolation (byte-
   identical counter before/after, unset counter stays unset, no `.mkplan.lock`
   left behind), D1 sentinel-exactly-once (fresh file and second append),
   D4 append-only (byte-prefix check across two calls, not just "one call
   worked"), entry shape (`--ref`/`--title`, zero-padded plan number), and the
   **cross-zone regression case**: two `--journal` calls in the same test with
   `TZ=UTC` and `TZ=Asia/Kolkata` (and separately `America/Los_Angeles`)
   landing on the *same* UTC day-file, plus a test asserting the recorded
   `HH:MM` matches `datetime.now(UTC)` within tolerance rather than the
   Kolkata-local reading. A single-clock test could not have distinguished
   "reads UTC" from "happens to agree with today's host zone" — that is why
   every zone-sensitive test drives `TZ` explicitly rather than relying on the
   test machine's own zone.

   - RED evidence: before this change `--journal` was not a recognised flag at
     all, so every one of these invocations fell into the existing `$# -ne 1`
     branch and exited 1 with "expected exactly one argument" — verified by
     inspection of the pre-change script rather than replaying via `git stash` (stash is blocked here per `R-GIT-STASH-PUSH`, and the diff makes
     the pre-image unambiguous).

4. **Docs kept in sync**: `CLAUDE/PlanJournalling.md` (and its bundled copy)
   — the "Entry grammar" `HH:MM` bullet and the "Lifecycle touchpoints" table
   row were updated to state UTC and mention `--journal`, since that file
   independently asserted "local 24-hour time" (this project's own doc the
   `check-truth-changes` CLI flagged for reconciliation).

5. **Truth-changes**: `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.66.0.yaml`
   (topic `plan-journalling`, id `journal-entry-timestamp-zone`). Verified with
   `./bin/hooks-daemon check-truth-changes --from 3.65.0 --to 3.66.0 --include-unreleased`, which correctly named `PlanJournalling.md`'s "local
   24h" line as the one to reconcile — reconciled per above.

6. **Release note**:
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/04-mkplan-journal-flag-stamps-utc-timestamps.md`.

## Verification

- `shellcheck -x` clean on both `mkplan.bash` copies.
- `diff` confirms both `mkplan.bash` copies and both `_JOURNAL_TEMPLATE_.md`
  copies and both `PlanJournalling.md` copies are byte-identical.
- `tests/unit/scripts/test_mkplan_journal.py`: 20/20 passed.
- `tests/unit/install/test_plan_workflow.py`,
  `tests/unit/handlers/session_start/test_deployed_artefact_drift.py`,
  `tests/unit/scripts/test_mkroutine_scaffolder.py`,
  `tests/unit/plan_qa/checks/test_journal_entry_ordering.py`: 126/126 passed
  (no regression from the UTC/sentinel changes).
- Full `./scripts/qa/llm_qa.py all`: 31/35 categories green. The 4 red
  categories are pre-existing/environmental, not caused by this work:
  - `format`: flagged exactly the new test file, which black auto-fixed in
    the same run (re-run confirms `black --check` passes).
  - `tests`: 10 errored — all `tests/acceptance/*` release-gate tests and
    `test_forwarder_socket_stdin.py`, which need a live daemon; this nested
    worktree's socket path exceeds the 104-byte `AF_UNIX` limit
    ("Socket path too long ... Using /tmp for runtime files"), which is a
    known constraint of deeply-nested worktree paths, not a code defect.
  - `docs_qa`: 1 advisory `duplicate-block` finding in an unrelated plan
    (00422's `NIGGLES.md`/journal), pre-existing.
  - `smoke_test`: fails for the same daemon-socket-path reason as the
    acceptance tests above.
    After restarting the daemon inside the worktree, one full acceptance file
    (`test_acceptance_contract.py`) still failed on `LintOnEditHandler` for
    several languages (shell/go/rust/ruby/php/dart) — traced to missing
    toolchains in this environment (no `shfmt`/`golangci-lint`), unrelated to
    `mkplan.bash`/journal code and pre-existing.

## Things worth the owner's attention (not implemented, flagged per instructions)

- **D6a lock**: `--journal` deliberately takes **no lock at all**, not even a
  journal-scoped one. Two concurrent `--journal` calls against the *same*
  plan on the *same* UTC day could race on "day-file absent -> create from
  template" (last writer wins on the `printf > file` for the fresh-file case)
  before either reaches the append step. The existing plan-creation flow's
  own journal-seed write has the same property today (no dedicated lock, only
  the counter lock which does not protect this file). Given D6a's directive
  to keep the journal path OUT of the counter lock's critical section, and
  that append-mode (`>>`) is safe for concurrent writers once the file
  exists, I judged inventing a *third* lock file out of scope for this plan
  and YAGNI unless the owner has evidence of concurrent same-plan journalling
  actually happening. Flagging rather than silently deciding.
- **Owner's two open questions**:
  1. *Existing byte-identity test for `mkplan.bash`* — yes, one already
     existed: `tests/unit/install/test_plan_workflow.py::TestMkplanDeployment ::test_deployed_mkplan_matches_bundled_template` (and
     `test_mkplan_overwritten_on_upgrade`,
     `test_idempotent_redeploys_mkplan`), all still green.
  2. *Other consumers of the `{{TIME}}` placeholder* — searched the whole
     tree; the only producer is `mkplan.bash` itself (both the plan-creation
     flow and, now, `run_journal_mode`), and the only consumer is
     `_JOURNAL_TEMPLATE_.md`. No other script or handler reads/writes
     `{{TIME}}`, so switching it to a UTC value breaks nothing else.

## Files changed

- `CLAUDE/Plan/mkplan.bash`
- `src/claude_code_hooks_daemon/install/templates/mkplan.bash`
- `CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`
- `src/claude_code_hooks_daemon/install/templates/_JOURNAL_TEMPLATE_.md`
- `CLAUDE/PlanJournalling.md`
- `src/claude_code_hooks_daemon/install/templates/PlanJournalling.md`
- `tests/unit/scripts/test_mkplan_journal.py` (new)
- `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.66.0.yaml` (new)
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/04-mkplan-journal-flag-stamps-utc-timestamps.md` (new)

Nothing has been committed or merged — the worktree is dirty with these
changes, ready for the owner's review.
