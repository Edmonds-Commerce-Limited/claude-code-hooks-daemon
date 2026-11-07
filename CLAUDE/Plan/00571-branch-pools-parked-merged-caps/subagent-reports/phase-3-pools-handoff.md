# Phase 3 (Tasks 3.1-3.3) handoff: implementation design, no code written yet

The first Phase 3 agent read PLAN.md, DESIGN.md, ROOTCAUSE.md and every module
below, then stopped at its context budget before writing code. This file is the
resolved implementation design, so the next agent can start at the failing
tests. Paths are relative to `src/claude_code_hooks_daemon/` unless they start
with `tests/`, `docs/` or `CLAUDE/`. Worktree venv is built (`bin/hooks-daemon repair` ran).

## Readings of DESIGN.md that needed a decision

1. **Unkept merged branch = stale from day 0** (DESIGN §3 "no age allowance ...
   the deny names from day 0"), **except when a worktree holds it**
   (`record.worktree is not None`). Without the exception, every live sub-agent
   isolation worktree (branch at main's tip reads as merged, DESIGN §3 table)
   would deny all creation, and `--clean` spares those (Task 2.8), so the deny
   would point at a command that cannot clear it. If the worktree is unknown,
   the branch is not stale (do not deny on missing information).
2. **Pool caps compare `>= cap`**, as `wip.cap` does (DESIGN §3: "denies ... when
   the pool is at its cap or holds a stale member").
3. **A stale kept merged branch is a `--clean` candidate** (open question 2's
   recommendation: a lapsed keep is an unkept merged branch). A kept branch
   inside its age is skipped by `--clean` and `--clean --remote`, and the skip
   is reported.
4. **Rule IDs:** two new ones, each covering its pool's cap AND its stale
   members: `R-BRANCH-PARKED-POOL` and `R-BRANCH-MERGED-POOL`
   (`constants/rule_ids.py`, beside `BRANCH_DORMANT`). Deny precedence in
   `creation_verdict`: WIP_CAP, DORMANT, PARKED_POOL, MERGED_POOL. All lines
   from every tripped pool are emitted.

## config/models.py (beside BranchWipConfig, ~line 2263)

- `BranchPoolConfig(BaseModel)`, `extra="forbid"`: `cap: Annotated[int, Field(ge=1)] | None = None`,
  `max_age_days: Annotated[int, Field(ge=1)] | None = None`, `mode: Literal["block","warn","off"] = "block"`.
  Subclasses `BranchParkedConfig` and `BranchMergedConfig` (docstrings only).
- `BranchesConfig`: `parked`, `merged`, `bot_owned: list[str] = Field(default_factory=lambda: ["dependabot/*"])`.
- Methods: `effective_pool_cap(pool)` returns the set cap, else `self.effective_wip_cap()`
  (this already honours the legacy `max_open_branches`).
  `effective_pool_max_age(pool)` returns the set value, else `self.dormancy.effective_days[2]`.
- `daemon/init_config.py` template gains the `parked:`/`merged:`/`bot_owned:` blocks (DESIGN §5).

## core/branch_keep.py (new; write tests/unit/core/test_branch_keep.py FIRST, the TDD gate needs it)

- `KEEP_NOTES_REF = "refs/notes/hooks-daemon/keep"`.
  `keep_tracking_ref(remote) = f"refs/notes/hooks-daemon-remote/{remote}/keep"`.
- `Keep(reason, by, at: int)`. `parse_keep_note(body)` reads `Kept-Reason:`/`Kept-By:`/`Kept-At:` (UTC ISO).
  A body holding several (after `notes merge -s union`) takes the latest `Kept-At`.
- `read_keeps(repo, tips, remote) -> dict[tip, Keep]`: `git notes --ref=<R> list` for the local
  ref and the tracking ref (a missing ref yields an empty result, not an error), intersected with
  `tips`, then `git notes --ref=<R> show <tip>` per kept tip only. Offline. Newest `Kept-At` wins
  across the two refs.
- `fetch_keeps(repo, remote) -> str | None` (error text): `git fetch <remote> +refs/notes/hooks-daemon/*:refs/notes/hooks-daemon-remote/<remote>/*`. It uses a glob refspec, so a
  remote without the ref succeeds and fetches nothing. A forced fetch into the tracking namespace
  never clobbers local, unpushed keeps.
- `keep_branch(repo, tips, reason, remote, user, now)`: validates a single-line, non-empty reason
  (`BranchKeepError`). If the reason equals the current keep's reason on the tip, it raises
  `BranchKeepSameReason(BranchKeepError)`, which the CLI maps to exit 2 (DESIGN §4).
  Otherwise it runs `git notes --ref=KEEP_NOTES_REF add -f -m <body> <tip>` for each distinct tip,
  then `git push <remote> KEEP_NOTES_REF`. On rejection it runs `fetch_keeps`, then
  `git notes --ref=KEEP_NOTES_REF merge -s union <tracking ref>`, and retries once.
  If that fails too, it returns the retry command and the local keep stands (DESIGN open question 3).

## core/branch_inventory.py

- `BranchState.BOT_OWNED = "bot-owned"`. `_never_work` returns it right after EXEMPT when
  `matches_any_glob(name, config.bot_owned)`, so `is_work_branch` (the creation guard) excludes bot
  branches for free. Add it to `_UNGROUPED`. In `containment_of`'s `vouching`, exclude BOT_OWNED:
  a bot branch must not vouch for containment.
- `class Pool(StrEnum)`: OPEN/PARKED/MERGED. `pool_of(state)` maps MERGED_DEFAULT,
  MERGED_LINE and PATCH_EQUIVALENT to MERGED, PARKED to PARKED, LIVE/DORMANT/UNCLASSIFIED to OPEN
  (fail closed), and every never-work state to None.
- `BranchRecord` new defaulted fields: `kept_reason`, `kept_by`, `kept_at: int | None`,
  `stale: bool = False`, `park_count: int | None`.
- After `_with_same_tips` in `build_inventory`, a `_with_pools` pass:
  - Parked: `stale = parked.mode != "off" and age_days >= max_age`. The tip IS the park commit, so
    `age_days` is the park age. `park_count` is one `git log --first-parent -n 64 --format=%T%x1f%(trailers:key=Parked-Reason,valueonly,unfold)` per parked tip. It counts the
    leading lines that carry a trailer and whose tree equals the next line's tree. The sweep prints
    `re-parked N times` when the count is above 1.
  - Merged: the keep is `read_keeps` on the local or the remote tip (either one counts, which is the
    conservative choice). `stale` (merged.mode != off): if kept, `(moment - kept_at)/DAY >= max_age`;
    if unkept, `worktree is None and worktree_known`.
  - Call `read_keeps` only when merged records exist.

## core/branch_sweep.py

- `_group_name`: BOT_OWNED becomes "bot-owned". `SweepGroups.bot_owned` gets its own section that
  is always printed, not only with `--all` (DESIGN §7: "visible rather than silent").
- Generalise `open_work_count` to `pool_count(inventory, pool)`, using the same-tip union within the
  pool, and keep `open_work_count = pool_count(OPEN)`.
- render: merged lines append `kept: <reason> (<n>d)` or `STALE: ...`. Parked lines append
  `STALE (past branches.parked.max_age_days N)` and `re-parked N times`. The footer prints three
  count lines, one per pool, each naming its own key.
- JSON: add `pool`, `stale`, `kept_reason`, `kept_at`, `park_count` to `JSON_RECORD_KEYS`, plus
  top-level `pools: {open|parked|merged: {count, cap}}`.
- session_summary (new_session): stale parked and stale kept-merged entries, and pool-at-cap
  notes. Each note offers only that pool's actions.

## core/branch_creation.py (hook path: no inventory, stays cheap)

- `_FORMAT` gains `%(trailers:key=Parked-Reason,valueonly,unfold,separator=%x1f)` (5 fields).
  `_Ref.parked`.
- One extra `for-each-ref --merged=<A> [--merged=<B>] --format=%(refname) refs/heads refs/remotes/<remote>` over the existing default refs (remote first, then local).
  Untested whether repeated `--merged` ORs; verify that before relying on it, or make two calls.
- Per ref: in the merged set, or labelled merged/patch-equivalent, means MERGED. A parked trailer
  means PARKED. Anything else is OPEN. Per work group: OPEN if any ref is open, else PARKED if any
  is parked, else MERGED.
- Parked group stale: `(now - committed)/DAY >= max_age`, computed live.
  Merged group stale: any of its names has a truthy `stale` in the labels snapshot.
- `write_labels` adds `"stale": "true" | None` from the record. `clear_label_stage` also clears
  `stale`. Add `clear_label_stale(path, name)` for `branch-keep`.
- The WIP-cap lines list OPEN groups only ("Finish, park or delete one" is now true).
  Parked lines name `branch-park <name> --clear` then merge, or `delete-branch`.
  Stale-parked lines add a re-park with a NEW reason. Merged lines name
  `sweep_clean_line(remote=any on_remote)`, and the stale-merged lines add `branch-keep <name> --reason`.
  Use `daemon_cli_command_for_docs` for the spellings.
- **Existing tests to rewrite:** `tests/unit/core/test_branch_creation.py`
  `TestCapNamesTheCleanCommand` and `test_labels_order_merged_first_with_action`. A merged branch no
  longer counts toward the WIP cap, so the clean line moves to the merged-pool deny.
  `TestLabels.test_round_trip` must gain `"stale": None`.

## core/branch_cleanup.py

- `clean_sweep`: when `remote`, call `fetch_keeps` BEFORE `build_inventory`. If the fetch fails,
  skip the whole remote half with a reported reason (DESIGN §2). The local half still runs.
- Candidates (local and `_proven_remote`) exclude records with `kept_reason and not stale`, which
  are reported as `kept: <reason>`, and any name matching `bot_owned` (defence in depth: the state
  already excludes them).

## park and CLI

- `core/branch_park.park_branch`: refuse a re-park whose reason equals the tip's current
  `Parked-Reason` (`BranchParkSameReason`). `cmd_branch_park` maps it to exit 2.
- `daemon/cli.py`: `cmd_branch_keep` plus a `branch-keep <name> --reason` parser (next to
  branch-park, ~line 13180). It builds the inventory offline. A name with no record exits 1. A
  state outside `CLEAN_STATES` exits 1 ("not merged; park it instead"). A same reason exits 2.
  On success it prints the keep and any push failure plus the retry command, then clears the label.
- `handlers/pre_tool_use/branch_creation_guard.py`: two more `Rule`s and a
  rule_id-to-Rule map in `handle`, and `get_claude_md` text for three pools.
  `handlers/worktree_create/worktree_create_handler.py:180` already passes `verdict.rule_id` through.

## Tests to write first (Task 3.1), new modules

`tests/unit/core/test_branch_pools.py` (own small fixtures; the inventory module fixture is shared,
so do not extend it), `tests/unit/core/test_branch_keep.py`, `tests/unit/daemon/test_cli_branch_keep.py`
and config-model tests. Each item in the PLAN.md 3.1 list is one test, plus: bot-owned in no pool and
never cleaned; a same-reason re-park or re-keep exits 2; `--clean` skips a kept branch and deletes a
stale kept one; a failed keep-ref fetch refuses the remote half.

## Task 3.3

`docs/guides/CONFIGURATION.md` (~line 300-350, the branches section; the line saying a parked branch
still counts becomes false). `docs/guides/HANDLER_REFERENCE.md` mentions R-BRANCH-WIP-CAP: check
whether it is generated before editing. Release note
`CLAUDE/UPGRADES/UNRELEASED/release-notes/007-*.md`; config-changes (seven keys `added`,
`breaking: false`); and three truth-changes (DESIGN §5). Read `CLAUDE/UPGRADES/UNRELEASED/README.md`
for the format. The root CLAUDE.md rule table is auto-generated: do not edit it.
