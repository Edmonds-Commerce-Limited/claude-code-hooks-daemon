# Post-B2 ledger marks and plan archival — report (Sonnet 5)

Worked directly on the shared main checkout at `/workspace`, branch `main`.
Everything below is verified against the code and tests on main, not taken
from any report at face value.

## Commits (in order)

1. `1b8cd162` — Ledger 00422: N1/N3/N4/N7 marked terminal (Decided
   unattended 2026-09-24 + built, with delivering commit and merge cited
   for each), N25 and N29 marked ✅ Remedied, Task 2.2 (N5 remedy 2) ticked.
   Moved the six owner questions' full text out of PLAN.md into
   DECISIONS.md (which already held their resolutions) to bring PLAN.md
   from 25,554 to 22,244 bytes — back under the 25,000-byte warning.
2. `34c588dc` — Ledger 00466 N23: added a verification note. Confirmed
   **still genuinely Open**, not fixed by B2 (see below). Left the PLAN.md
   status row unchanged.
3. `e716aa82` + `a20c4139` — Plan 00449: archived (git mv + README rows +
   statistics). Split into two commits because the first `git mv` staged
   the pre-edit PLAN.md content instead of my Status/criterion edits; the
   second commit carries the missed content. Confirmed by content diff
   before each later archive to avoid repeating this.
4. `ee845731` — Plans 00388 + 00394: archived together in one commit
   (see "Why 00388/00394 share a commit" below).

All pushed; CI (run 36066507383, commit `34c588dc`, which is the ancestor
every archived plan's code sits on) came back **success**, confirmed both
via `gh run view --json conclusion` and the team lead's independent check.

## Ledger 00422 — marked (all verified against code, not just reports)

- **N1**: whole-template priority test built
  (`tests/integration/test_template_priorities_match_the_constants.py`);
  `constants/priority.py` and `daemon/init_config.py` now agree — checked
  `SECURITY_ANTIPATTERN = 14` against the template's `priority: 14`
  directly. Commit `c1822548`, merged `d28b25fa`.
- **N3** remedy (2): `correction` journal category confirmed in
  `CLAUDE/Plan/_JOURNAL_TEMPLATE_.md` (both copies). Commit `14bdb525`,
  merged `d28b25fa`.
- **N4**: session-scoped `cron-pause`/`cron-resume` — confirmed by reading
  the owner-b report; not independently re-run live (CLI verbs, marker
  mechanics). Commit `8b388a2a`, merged `63dea9f08`.
- **N7**: `_latch_unattributed_effort_drop` and `note_own_effort_injection`
  confirmed present in `.claude/ccy/claude-supervise.py` by grep. Commit
  `8ffe9ffe`, merged `63dea9f08`.
- **N5 remedy 2 / Task 2.2**: `dispatch_declaration.py` confirmed to name
  the dispatching plan's `subagent-reports/` as the default, tracked
  destination (docstring and `DEFAULT_REPORT_DIR` usage checked directly).
  Commit `f013ac65`, merged `d28b25fa`.
- **N25**: `utils/command_evasion.py` confirmed to define
  `SHELL_RESERVED_COMMAND_PREFIXES` / `strip_reserved_word_prefix`, and
  `pipe_blocker.py` confirmed to import and call it. Commit `319cdd35`,
  merged `fb76d6400`.
- **N29**: `write_clobber_guard.py` read in full — `matches()` now fires on
  every Read/Edit/Write carrying a path, `handle()` records every allowed
  call. `test_write_clobber_guard_dispatch.py` exists. Commit `d2ed30a4`,
  merged `fb76d6400`.

## Ledger 00466 N23 — left Open (NOT fixed by B2)

Read `recovery_cron_advisor.py` directly: `self._cached_phase` is still
set in `matches()` and read/cleared in `handle()` — the exact per-call
state-on-a-singleton shape the entry names. No interleaving/concurrency
test exists in `tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py`
(only `test_matches_then_handle_uses_cached_phase`, not a race test).
Plan 00449's `BoundedFifoMap` work fixed the select-then-evict class at
three OTHER spots in this same file, but its own report says this class
was explicitly excluded from that plan's Non-Goals and recorded here
instead — consistent with what I found in the code. Added a note to
NIGGLES.md recording the check; did not mark it Remedied.

N26 left untouched, as instructed (being fixed on another branch).

## Archives

All three plans' only unticked success criterion was the CI/full-QA gate;
every other criterion was already `[x]` in each PLAN.md, and I did not
re-tick anything else.

- **00449** (`5e3e784f`…`28abcf6e`): unlocked-eviction race, 12 sites
  across 10 handlers via `BoundedFifoMap`, plus a per-thread
  `SideEffectJournal`. Archived into the main README's 30-row completed
  window (it's numbered above the window's floor); the window's new 31st
  row, 00425, aged out to `Completed/README.md`.
- **00388 + 00394** (`9370546f`…`3ffd713c`, same branch, same commits):
  both are numbered below the main README's completed-window floor
  (00425 at the time), so both went straight into `Completed/README.md`,
  in descending numeric position — neither touches the main README's
  window.

**Why 00388/00394 share one commit instead of one each.** I tried a true
split first (unstage one plan's move, reconstruct the shared README diff
for the other). It produced a technically-correct git index but a
filesystem state `llm_qa.py plan_qa docs_qa` legitimately flagged as
broken (those checks scan the working tree, not git's index, so a
plan physically moved but not yet reflected everywhere reads as a stale
link regardless of staging). Rather than commit through unresolved
advisories or fake the filesystem, I combined them into one commit,
verified 0/0 findings on the real combined state, and said so plainly in
the commit message. 00449 did not have this problem (nothing else
referenced it), so it kept its own commit — the mechanics of *that* one
split cleanly except for the staging bug noted above.

**00394's residual notes** ("live crons predate the sentinel", "the
failsafe prompt still says to delete the cron"): checked the d-cron
report's own "Residual risks, stated plainly" section. Both are
consciously accepted as the ruled approach's (2′) residual, not
oversights — a cron created before this landed keeps its old prompt until
re-created, and 00394's own non-goal forbids rewording the canonical
prompt. Neither is closed by anything in B2. I added a note citing this
to both 00388 and 00394's Delivery & Milestones sections rather than
archiving silently over them.

**Statistics**, re-derived from `find`, not guessed, after each commit:
Active 42→41 (00449)→39 (00388+00394); Completed 404→405→407;
39 + 407 + 13 = 459 folders (unchanged); 456 distinct / 469 total
unchanged. `tests/integration/test_plan_index_navigability.py` (4 tests)
passed after both archive commits.

## QA

`./scripts/qa/llm_qa.py plan_qa docs_qa` run before every commit, 0
findings on the actual committed state each time (some intermediate
working-tree states during the 00388/00394 split attempt showed advisory
findings, all resolved before anything was staged/committed). Daemon
restarted before every commit. No exclusions added anywhere.

## Not done / left for the coordinator

- 00422's other open rows (N24, N28, and the graduated N23/N26) were out
  of my brief and untouched.
- 00466 N23 stays Open; a fix needs `recovery_cron_advisor` to stop
  caching per-call state on the instance, per its own candidate remedy.
