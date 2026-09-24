# Subagent report: Ledger 00466 N3 — goal_injection real-flip fix

**Agent**: Claude Opus 5.5
**Task**: Fix `goal_injection` firing on any edit of an already-In-Progress
plan (niggle N3), TDD-first, in worktree
`worktree-n466-goal-flip`.

## RED evidence

Added `TestStatusFlipDetection` to
`tests/unit/handlers/post_tool_use/test_goal_injection.py` (8 tests) and ran
it against the pre-fix code. 3 failed, matching exactly the defect
scenarios:

- `test_edit_unrelated_to_status_line_on_in_progress_plan_emits_nothing`
- `test_edit_whose_replaced_span_already_read_in_progress_emits_nothing`
- `test_write_rewriting_an_already_committed_in_progress_plan_emits_nothing`

The other 5 (a real Not-Started→In-Progress Edit flip, a brand-new Write, an
uncommitted-repo Write, a committed-Not-Started→In-Progress Write, and the
terminal-flip refresh path) already passed, pinning behaviour that must not
change. Full pytest output captured at the time in
`untracked/scratch/red_run.txt` (untracked, not committed) showed
`3 failed, 5 passed`.

## The fix

`GoalInjectionHandler._is_real_flip_to_in_progress` gates the existing
in-progress branch of `handle()`, added right after the whole-file
`_STATUS_IN_PROGRESS_RE` check and before the once-per-session latch, the
ledger record and the displacement advisory — so a non-flip touches none of
them.

- **Edit**: reads `tool_input.old_string` (the only witness of the pre-edit
  text available without reconstructing the whole file) with
  `PlanDoc.parse`. No Status line in that fragment → this edit's replaced
  span never touched it → not a flip. A Status line present and not
  `PlanStatus.IN_PROGRESS` → a flip.
- **Write**: by the time PostToolUse runs the file has already landed on
  disk, so there is no unmodified copy left to diff against. `_head_plan_text`
  reads the file's content at git HEAD instead, via
  `utils.git_facts.GitFactsBase.head_file_text` (already used elsewhere in
  this codebase, read-only, declines the optional index lock via
  `run_git`). `None` (no repo, unresolvable path, or a path HEAD has never
  seen) reads as "nothing to flip FROM" — a brand-new or never-committed
  In-Progress PLAN.md is a genuine flip, matching the pre-existing
  single-plan contract.

## Before-state source for Write: why git HEAD, not `tool_response`

I checked this codebase's own fixture-verification record
(`CLAUDE/Plan/Completed/001-test-fixture-validation/ POSTTOOLUSE_FIXTURE_VERIFICATION.md`) and the input schema
(`core/input_schemas.py`) rather than assume a shape. Neither pins what a
Write/Edit `tool_response` actually carries — the verification doc documents
Bash/Read/Glob/Grep shapes only, and `budget_exhaustion_detector.py`'s own
comment says Edit/Write/NotebookEdit responses "echo AUTHORED file content
back" without specifying old vs. new. This project has already shipped a
handler (`bash_error_detector`) that silently never matched real events
because of exactly this kind of unverified-payload assumption — the
verification doc exists because of that incident. git HEAD is a stable,
already-relied-upon interface (`utils/git_facts.py`, used by both QA commit
gates) with a documented, tested "fact not available → None" contract, so I
used it instead of guessing at `tool_response`'s shape. This is also why the
Edit path does NOT use `tool_response` either, and instead reads
`old_string` directly from `tool_input`, which the daemon has always
trusted for Edit's own semantics (`would_be_content.py` does the same for
the PreToolUse side).

The tradeoff this choice accepts: a plan flipped to In Progress by an
uncommitted Edit earlier in the SAME session, then touched by an unrelated
Write later in a NEW session (daemon restarted, latch reset) before ever
being committed, would be read as a fresh flip by the Write path (HEAD still
shows the old, uncommitted status). This is bounded to a working style this
project's own git hygiene discourages (long-lived uncommitted plan flips
across a daemon restart) and is strictly no worse than the pre-fix
behaviour, which fired on literally *every* first touch in a new session
regardless of content.

## Sibling audit

Searched `post_tool_use/` and `pre_tool_use/` for other uses of
`_STATUS_IN_PROGRESS_RE` or an equivalent status-line regex:

- **`recovery_cron_advisor.py`**: its Edit-path COMPLETION detection
  (`_edit_results_in_status_complete`) already requires the edit's own
  `old_string`/`new_string` to assert Complete (either `new_string` itself
  reads `**Status**: Complete`, or `old_string` targeted the Status-line
  prefix and `new_string` supplies the bare value) — already
  transition-based, not state-based. Its Write-path
  (`_STATUS_COMPLETE_RE.search(content)` against the whole new file content)
  IS state-based in the same shape as this bug, but two things make it a
  materially different risk: its dedup latch
  (`_should_advise_once`/`_creation_seen`/`_completion_seen`) fires **once
  ever per plan folder**, not once per session, so it cannot re-displace
  anything on a later touch the way the ledger-backed goal signal could; and
  its consequence is a single advisory message with no ledger write, no
  goal-slot write, and nothing another plan can be displaced by. Left as
  documented existing behaviour (Decision D2 in its own module docstring
  already calls CREATION/COMPLETION "state TRANSITIONS", which is imprecise
  in the same way goal_injection's old docstring was, but the blast radius
  does not justify folding into this fix). Recorded in NIGGLES.md's N3
  remedy paragraph rather than silently dropped.
- **`plan_close_approval.py`**: `_is_terminal_flip` is already correctly
  transition-based — it reads the CURRENT on-disk content (this handler runs
  PreToolUse, before the write lands) and the PROPOSED content via
  `would_be_content`, then compares `PlanDoc.parse(current).status` against
  `PlanDoc.parse(proposed).status`. No defect.
- **`plan_qa_edit.py`**: its two "In Progress" occurrences are guidance
  prose listing the allowed status tokens, not status-detection logic. Not
  applicable.

## Targeted QA (Plan 00463 policy — no full suite run)

```
./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding docs_qa plan_qa
```

Result: `QA: 8/8 PASSED`. (`error_hiding` initially flagged the two new
`return None` branches in `_head_plan_text`; added a documented exclusion in
`scripts/qa/error_hiding_exclusions.json` matching the style of the two
existing `goal_injection.py` entries. `format` initially flagged the two
edited files pre-autofix; resolved via `./scripts/qa/run_autofix.sh`, not
`ruff format` directly, per `ruff_format_blocker`'s guidance — Black is this
project's formatter of record.)

Test runs:

- `tests/unit/handlers/post_tool_use/test_goal_injection.py` — 71 passed (63
  pre-existing + 8 new).
- `tests/unit/handlers/post_tool_use/` (whole directory) — 627 passed.
- `tests/unit/handlers/stop/test_goal_ledger_stop_defence.py` +
  `tests/unit/utils/test_goal_ledger.py` — 26 passed.

Did not run `./scripts/qa/llm_qa.py all` or `run_all.sh` (denied by
`enforce_llm_qa` and out of scope under Plan 00463 — the coordinator runs
one full gate over the merged batch).

## Daemon restart

Restarted (`./bin/hooks-daemon restart`) and confirmed `Daemon: RUNNING`
before each commit.

## Commits (this worktree, branch `worktree-n466-goal-flip`)

1. `5676772d` — the fix: `_is_real_flip_to_in_progress` +
   `_head_plan_text`, docstring/`get_claude_md()`/acceptance-test updates,
   the RED-first test class, and the `error_hiding_exclusions.json` entry.
2. `84085fa2` — ledger update: PLAN.md row → Remedied, NIGGLES.md N3 Remedy
   paragraph naming commit 1, and the release note.
3. `04a7ae91` — journal entry for N3 (via `mkplan.bash --journal`).
4. This report.

HEAD SHA at report time: see the commit that adds this file.
