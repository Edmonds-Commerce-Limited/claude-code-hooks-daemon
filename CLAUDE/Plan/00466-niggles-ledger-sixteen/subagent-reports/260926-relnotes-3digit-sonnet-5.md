# N109 — three-digit ordinals for pending release-notes callouts

**Worktree**: `worktree-n466-relnotes-3digit` (branched from main)
**Commit**: `42f3d6dc5584e3cfce312b283e184239aa2bcc58`

## What changed

`CLAUDE/UPGRADES/UNRELEASED/release-notes/` named callouts `NN-slug.md`, a
two-digit arrival ordinal, enforced by
`tests/integration/test_pending_release_notes_holding_area.py`'s `^\d{2}-`
regex. Main held 85 notes numbered up to 93 and open branches carried about
20 more, so this release cycle passes 99 — a mixed two- and three-digit
scheme would mis-sort, since `release_slate._pending_release_notes` and the
release fold both sort callouts by filename as a string (`100-` before
`11-`).

Switched to a fixed three-digit ordinal, `NNN-kebab-slug.md`:

- **RED** proven first: tightened the test's regex to `^\d{3}-` and ran it
  against the (still two-digit) files on disk — 86 failed, 3 passed.
- Added `test_callout_names_sort_in_numeric_arrival_order`, asserting a
  plain string sort of callout names equals a numeric sort (the guarantee a
  fixed width gives).
- Renamed every existing callout with `git mv` in a bash loop
  (`NN-*.md` → `0NN-*.md`, zero-padded); fixed two files a bash octal-literal
  bug (`08`, `09`) mis-padded to `000-` before the rename.
- **GREEN**: re-ran the holding-area test — 89 passed.
- Updated every place that stated or built the two-digit form:
  - `CLAUDE/UPGRADES/UNRELEASED/release-notes/README.md` naming section.
  - `CLAUDE/development/RELEASING.md` (the fold-in read, the `git mv` glob,
    and both ABORT-condition sentences for `release-notes/`;
    `post-upgrade-tasks/`'s own `NN` rule was left untouched — a different
    directory).
  - `.claude/agents/release-agent.md:196`, `.claude/skills/release/invoke.sh:83`.
  - Two-digit example filenames in
    `tests/unit/plan_qa/checks/test_release_blocked_plan.py` and
    `.claude/project-handlers/pre_tool_use/test_plan_done_requires_holding_area.py`.
  - The one live-plan link still pointing at a two-digit pending callout:
    `CLAUDE/Plan/00399-supervisor-does-not-see-tab-completed-slash-commands/PLAN.md`.
  - Did NOT touch `subagent-reports/` or `Completed/` references to
    two-digit callouts (per brief, historical) or the one historical
    already-released link in `CLAUDE/Plan/00422-.../NIGGLES.md`
    (`v3.65.0-to-v3.66.0/release-notes/04-…`, already moved out of
    `UNRELEASED/`).
  - `git grep` for `release-notes` + `\d{2}` in `src/` found no shipped
    template or daemon code parsing the callout prefix by digit count, so
    nothing else needed a change.
- Added the N109 write-up to `CLAUDE/Plan/00466-.../NIGGLES.md` and the
  ledger row to `PLAN.md`.

## QA run

- `tests/integration/test_pending_release_notes_holding_area.py`: 89 passed.
- `tests/unit/plan_qa` + `tests/unit/core/test_release_slate.py`: 895 passed.
- `.claude/project-handlers/pre_tool_use/test_plan_done_requires_holding_area.py`
  via `bin/hooks-daemon test-project-handlers --verbose`: 223 passed.
- `bin/hooks-daemon plan-qa --sweep`: 0 findings.
- `bin/hooks-daemon docs-qa --sweep`: 0 findings.
- ruff, black, pyright on the two changed Python files: all clean. mypy on
  `test_plan_done_requires_holding_area.py` fails with a pre-existing,
  unrelated error (`project-handlers contains __init__.py but is not a valid Python package name`) — reproduced identically on main before this
  change, so not a regression.
- Daemon restarted in the worktree; `bin/hooks-daemon status` reports
  `Daemon: RUNNING`.

Gate queued in the background (`gate.sh worktree-n466-relnotes-3digit`); not
waited on.
