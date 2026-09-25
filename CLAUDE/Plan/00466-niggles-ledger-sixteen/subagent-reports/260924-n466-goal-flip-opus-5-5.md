# Subagent report: Ledger 00466 N3/N7 — goal_injection real-flip fix, CLAUDE.md guidance order

**Agent**: Claude Opus 5.5 (N3, N3 follow-up), Claude Sonnet 5 (N7, review fix-up)
**Task**: Fix `goal_injection` firing on any edit of an already-In-Progress
plan (niggle N3), then fix the CLAUDE.md guidance block's nondeterministic
order (niggle N7), then fix everything the pre-merge review found against
this branch, TDD-first, in worktree
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
4. `624f859b` — this report, first version.
5. `6699fbbd` — follow-up 1 (below).
6. `4813adc8` — follow-up 2 (below).
7. `52e6d534` — ledger/release-note update for the follow-up.

## Follow-up after review

The review accepted the flip-detection design but rejected two things:
keeping the `error_hiding_exclusions.json` entry, and treating
`recovery_cron_advisor`'s sibling defect as "only an advisory, leave it".

### 1. Dropped the exclusion, restructured instead (commit `6699fbbd`)

`_head_plan_text` caught `RuntimeError`/`OSError` around
`ProjectContext.project_root()` and `ValueError`/`OSError` around
`.relative_to()`, both `return None` on catch — exactly what
`error_hiding`'s `return-none-on-error` check exists to flag, and my
original report's own exclusion reason said one branch was "silently
expected", which is the tell. Restructured per the review's three asks:

- Path membership: `Path.is_relative_to()` instead of a caught
  `ValueError` from `.relative_to()` — a plain boolean comparison, never an
  exception.
- `ProjectContext.project_root()`: called unguarded. It raises only when
  `ProjectContext` was never initialised, which does not happen on the
  normal handler-dispatch path (the daemon always initialises it before
  dispatching any hook event) — so a `RuntimeError` here is a genuine
  misconfiguration, not a routine "nothing to compare against". Verified
  against `core/chain.py`'s dispatch loop: every `handler.matches()` /
  `handler.handle()` call already sits inside a `try/except Exception` that
  logs and either fails open (non-strict mode, the default) or fails closed
  with a `SYSTEM ERROR` deny (strict mode) — so letting it propagate is
  strictly safer than silently returning a wrong answer, and loses no
  observability (`chain.py` already logs the exception).
- The git read itself already returned a typed absent answer from git's
  own exit code (`GitFactsBase.head_file_text`/`_git_output`), never a
  caught exception — no change needed there.

I extracted the whole lookup to
`utils.git_facts.project_relative_head_text(file_path: Path) -> str | None`
rather than leaving it as a `goal_injection`-private method, anticipating
follow-up 2 needing the identical logic. `error_hiding` now reports 0
violations for this code, with no exclusion.

Added `TestProjectRelativeHeadText` (4 tests) to
`tests/unit/utils/test_git_facts.py` for the extracted function itself
(committed-path, never-committed-path, outside-project-root, and a nested
path — the last matching `CLAUDE/Plan/NNNNN-name/PLAN.md`'s actual shape).

### 2. Fixed the sibling instead of leaving it (commit `4813adc8`)

`recovery_cron_advisor`'s Write-path completion check
(`_STATUS_COMPLETE_RE.search(content)` against the whole new file) shared
the identical state-vs-transition shape my original report described and
declined to fix. Added `_write_is_real_completion(file_path)`, which calls
`project_relative_head_text` (the function extracted in follow-up 1) and
answers `True` only when the plan was NOT already `Complete[d]` at HEAD.
`_detect_lifecycle_phase`'s Write branch now checks this before returning
`LifecyclePhase.COMPLETION`; when the content reads Complete but the plan
already was at HEAD, the event now matches **no phase at all** (it does not
fall through to PROGRESS/CREATION — there is nothing lifecycle-relevant to
report, matching `goal_injection`'s "not a flip, so nothing fires" answer
for the equivalent case).

RED-first: added `TestWriteCompletionIsTransitionBased` (4 tests) to
`tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py`. The
first — rewriting an already-committed Complete plan — failed against the
pre-fix code (`LifecyclePhase.COMPLETION` instead of the expected `None`)
and passes after the fix; the other 3 pin the no-repository/new-file and
never-committed-transition cases, plus that the already-correct Edit path
is untouched.

This file's `_detect_lifecycle_phase` tests had never needed
`ProjectContext` before (it is a pure function over `hook_input` in every
existing test, using hardcoded `/workspace/...` paths with no real
filesystem or git backing). Since the Write-COMPLETE branch now calls
`project_relative_head_text`, which calls `ProjectContext.project_root()`
unguarded, I added one module-level `autouse` fixture mocking
`project_root` to `tmp_path` for the whole test file. None of the
pre-existing hardcoded paths fall under that `tmp_path` root, so
`Path.is_relative_to` answers `False` for every one of them —
`project_relative_head_text` returns `None` exactly as it would with no
mock and no repository at all — and every pre-existing assertion is
unaffected. The real HEAD-comparison scenarios get their own git-backed
fixture in the new test class, rooted at the same `tmp_path`.

### Targeted QA after the follow-up

```
./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding docs_qa plan_qa
```

`QA: 8/8 PASSED` — `error_hiding` now 0 violations with the exclusion
removed (an intermediate run surfaced one `ARG001` lint warning, an unused
`new_content` parameter left over from an earlier draft of
`_write_is_real_completion`; dropped the parameter and re-ran clean, and
pyright separately flagged a fixture/attribute name collision in the new
test class — `_root` naming both the fixture method and the instance
attribute it set — renamed the fixture to `_capture_root`).

Test runs after the follow-up:

- `tests/unit/handlers/post_tool_use/` (whole directory) — 631 passed.
- `tests/unit/utils/test_git_facts.py` — 18 passed (14 pre-existing + 4
  new).
- `tests/unit/handlers/stop/test_goal_ledger_stop_defence.py` +
  `tests/unit/utils/test_goal_ledger.py` — 26 passed.
- `tests/unit/plan_qa/test_gitfacts.py` +
  `tests/integration/test_qa_package_dependency_direction.py` — 31 passed
  (checked because `git_facts.py` gained a new import,
  `core.project_context.ProjectContext`; confirms no forbidden `plan_qa`
  edge and the plan-specific `GitFacts` subclass is unaffected).

Daemon restarted and confirmed `Daemon: RUNNING` before each follow-up
commit.

## N7 — CLAUDE.md guidance block order was not deterministic

After N3 was committed and reported, the coordinator queued N7 on the same
branch. Merged `main` (commit `0b226357` and later) first, to pick up the
ledger's N7 finding entry; resolved two conflicts (`PLAN.md`'s niggle table,
and the JOURNAL day-file's conflict markers — deletion-only, per
`plan_journal_guard.py`'s documented exemption) in merge commit `f80e9956`.
Restarted the daemon post-merge and re-ran the N3/N3-follow-up test suites
(177 tests) to confirm the merge left that work intact before starting N7.

### Root-cause trace

`ClaudeMdInjector._collect_tiers()` (`core/claude_md_injector.py:642`)
iterated `self._handlers` and appended straight into the `promoted`,
`progressive` and `fallback` tier lists with no sort at all — the block's
order was whatever order the constructor's `handlers` argument arrived in.
Traced that argument back through the call chain:

- `daemon/controller.py:327` built it as
  `[h for chain in self._router._chains.values() for h in chain._handlers]`
  — reading `HandlerChain`'s **private**, insertion-order `_handlers` list.
- `HandlerChain` already has a **public** `handlers` property
  (`core/chain.py`) that sorts by `(priority, name)` on first access after
  any `.add()` and caches the result — the correct pattern, and the one
  `EventRouter.get_all_handlers()` (`core/router.py:261`) already uses.
  `controller.py` was bypassing it.
- Even with sorted-by-priority input, handlers sharing a priority still tie,
  and `_collect_tiers()` had no tiebreaker of its own — so the true fix has
  to live in `_collect_tiers()` regardless of what `controller.py` does.
- The ultimate root of *why* two daemons ever disagreed on an initial order
  is `HandlerRegistry.discover()` (`handlers/registry.py:309`), which uses
  `pkgutil.walk_packages()` over the filesystem — directory-entry order is
  not guaranteed stable across processes or checkouts. Chose not to try to
  make filesystem scanning itself deterministic; instead made every
  downstream consumer (chain, injector, docs generator) independently
  order-invariant, per the brief's "fix it at the right layer" — the layer
  that actually renders output is the layer that must guarantee determinism,
  regardless of what upstream hands it.

### The fix

1. `_collect_tiers()`: sorts each of the three tier lists
   (`promoted`, `progressive`, `fallback`) by handler name
   (`item[0]`) before returning. Name alone is a complete total order within
   one tier — two active handlers never share a name — so no further
   tiebreaker is needed; priority is deliberately not consulted here because
   handlers from different event chains are mixed into one flat CLAUDE.md
   tier, where priority carries no meaningful ordering across event types.
2. `daemon/controller.py:327`: `chain._handlers` → `chain.handlers`, so the
   input `_collect_tiers()` receives is already the correctly-sorted public
   view rather than raw insertion order — defence in depth, not required for
   correctness given (1), but closes the actual point where the
   nondeterminism entered.
3. `.claude/HOOKS-DAEMON.md`'s sibling tie problem, per the brief's explicit
   ask: `daemon/docs_generator.py`'s `_render_handler_table()` sorted
   `handlers.sort(key=lambda h: h[3])` — priority only, no tiebreaker.
   Same-priority handlers kept whatever order the (also nondeterministic)
   `HandlerRegistry.list_handlers()` produced. Fixed to
   `key=lambda h: (h[3], h[1])` — priority, then `config_key` (the value
   actually rendered in the table's "Handler" column).

### RED evidence

- `tests/unit/core/test_claude_md_injector.py`:
  `TestGuidanceOrderIsIndependentOfDiscoveryOrder` (4 tests —
  promoted-tier, progressive-tier, fallback-tier, all-three-together), each
  injecting the same handler set in forward and reversed constructor order
  into separate `tmp_path` subdirectories and asserting byte-identical
  `<hooksdaemon>` block content. `pytest ... -k TestGuidanceOrderIsIndependentOfDiscoveryOrder -q` → **4 failed, 65
  deselected** against the pre-fix code, each diff showing handler entries
  positioned by input order rather than a stable order.
- `tests/unit/daemon/test_docs_generator.py`:
  `test_same_priority_handlers_are_order_independent` — two priority-30
  handlers (`aaa-handler`, `zzz-handler`) built via two registries in
  opposite orders; asserts identical `generate_markdown()` output. Failed
  against the pre-fix code with the two table rows swapped between runs.

After the fix, both suites are green:
`tests/unit/core/test_claude_md_injector.py` — 69 passed;
`tests/unit/daemon/test_docs_generator.py` — 56 passed. Also re-ran the full
controller test suite (`test_controller.py` +
`test_controller_agent_sync.py` + `test_controller_degraded_mode.py` +
`test_controller_modes.py` + `test_controller_plugin_loading.py` +
`test_controller_project_handlers.py` +
`test_controller_directory_role_rules_sync.py`) since `controller.py`
changed — 110 passed.

### Regeneration and idempotence

Restarted the worktree daemon (`./bin/hooks-daemon restart`, confirmed
`Daemon: RUNNING`), then ran `./bin/hooks-daemon regenerate-docs`. Result:
`.claude/HOOKS-DAEMON.md` changed only in the expected, unrelated way (one
row's description text picked up N3's earlier docstring wording change,
"flips to" → "TRANSITIONS to" — not a reorder); the CLAUDE.md
`<hooksdaemon>` block itself had **zero diff** against what was already
committed, confirming the committed block already matched the new
deterministic order. Ran `regenerate-docs` a second time immediately after:
identical diff (none beyond the first run), confirming idempotence.

### Targeted QA

```
./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding docs_qa plan_qa
```

Result: `QA: 8/8 PASSED`, no exclusions added. `run_autofix.sh` run over the
touched files first; no formatting changes were needed.

### Commit

`0dba7bfb` — the N7 fix: `_collect_tiers()` sort, `controller.py`'s
`chain.handlers` fix, `docs_generator.py`'s tiebreaker, the RED tests, and
the regenerated `.claude/HOOKS-DAEMON.md`. Ledger update (PLAN.md row →
Remedied, NIGGLES.md N7 Remedy paragraph, journal entry via `mkplan.bash --journal`, this report) lands in the commit that follows it.

Daemon restarted and confirmed `Daemon: RUNNING` before the commit.

## Pre-merge review fix-up (majors M2/M3, minors m4/m5/m6, nits n3/n6/n7)

The review at `subagent-reports/260924-n466-review-opus-5-5.md` (0 blocker,
4 major, 7 minor, 7 nit across both the N3/N7 and N4/N5/N6 fix branches)
found real regressions against this branch. Fixed all of them; merged main
first to pick up its restored N3/N7/N8 headings and the N10/N11 rows
before resolving three further conflicts (JOURNAL day-file, NIGGLES.md,
PLAN.md) the same way as the earlier merge.

### M2 — retirement refresh did not survive a daemon restart

`_maybe_refresh_on_retirement` gated on `self._fired`, an in-memory latch
a restart empties; N3's flip-only rule meant a later non-flip write never
re-latched either. Added `GoalLedger.has_live_entry(session_id, plan_number)` (read-only, no reconciliation) and
`GoalInjectionHandler._session_ledgered_plan`, which asks the persisted
ledger instead. RED: `test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal`
uses a FRESH `GoalInjectionHandler` instance for the completing write (in-
memory latch genuinely empty, same ledger/untracked dir) — failed against
the pre-fix code, `00296` stayed in the combined signal after completing.

### M3 — a resumed session lost its `/goal` entirely

Plan 00269 Task 2.1's own PLAN.md records the intended trade: "the first
edit to an already-In-Progress plan in a NEW session re-fires... that is
what makes the goal survive session restarts." N3's flip requirement
removed that path outright, and my own docstring/release-note claims that
nothing changed were wrong (M3's own finding). Chose option (a) from the
review's fix direction — reassert from the ledger, no displacement —
implemented as two new `GoalLedger` methods:

- `session_has_entries(session_id)` — has the ledger EVER recorded an
  emission for this session (retired entries count too — a session that
  fully completed one plan is not "new" either).
- `reassert_session(session_id, plan_number)` — finds the plan's still-
  live entry (if any) and reassigns its `session_id`, with ZERO
  displacement bookkeeping — the defining difference from
  `record_emission`, pinned by its own unit test
  (`test_does_not_displace_any_other_live_plan`).

`GoalInjectionHandler._maybe_reassert_for_new_session` calls both: a
session with no entries at all that touches an already-live plan without
producing a real flip gets `reassert_session` called and, if it found an
entry, its own combined signal written via the existing
`_write_combined_signal` — no `_ledger_record`, no advisory. RED:
`TestNewSessionReassertion.test_a_new_session_touching_an_already_live_plan_gets_its_own_signal`
failed with `FileNotFoundError` against the pre-fix code (no signal file
ever appeared for the new session). Two more tests pin the two ways this
could go wrong silently: a session with its OWN live goal must not
reassert an unrelated plan, and reasserting must not displace some OTHER
live plan (checked directly against the ledger, not just the reasserting
session's own signal, since nothing re-renders another session's stale
signal file).

Corrected release note 13 and the module docstring, which both said "no
action needed" / "exactly as before" — false once M3 was understood.

### m4 — `old_string` carrying only the bare status value

`PlanDoc.parse(old_string)` needs the whole `**Status**:` line; an agent
quoting just `"Not Started"` as `old_string` has no Status line in the
parsed fragment, so the old code read "never touched it". Added
`_reconstruct_pre_edit_text(tool_input, post_edit_text)`: reverses the
edit against the file's current (post-edit) on-disk content — the exact
inverse of `would_be_content`'s forward transform, honouring
`replace_all` — and parses THAT when `old_string` alone has no Status
line. `None` (irreversible: `new_string` not found in the post-edit text)
reads as "not a flip", the same conservative default the old code used.
RED: `test_edit_whose_old_string_is_only_the_status_value_still_emits`
failed against the pre-fix code (no signal). A no-op control test pins
that a value-only edit which never actually changed the status still
emits nothing.

### m5 — a Write in a nested repository read the wrong repo's HEAD

`project_relative_head_text` resolved membership against the PROJECT
ROOT, then ran `git show HEAD:...` against that SAME root's repo — wrong
whenever the file's real containing repo is a nested one (a linked
worktree under `untracked/worktrees/`, any nested clone): the project
root's repo never tracked that path, so it always answered "absent",
misreading the write as a genuine flip. Fixed with `GitRepo.resolve_for`
(already-centralised `git -C <dir> rev-parse --show-toplevel`) to find
the file's OWN toplevel before reading HEAD; a project root that is
itself a plain checkout is unaffected (resolves to itself). RED:
`test_a_file_in_a_nested_repository_reads_from_its_OWN_head` in
`test_git_facts.py` — asserted `None` against the pre-fix code where the
real committed content was expected. Fixes `recovery_cron_advisor`'s
Write-path COMPLETION check for the same reason, since it shares the
helper.

### m6 — N7's own narrative misattributed the root cause

The review checked this claim against the actual `pkgutil` source:
`_iter_file_finder_modules` calls `filenames.sort()`, so `pkgutil` was
never the unsorted source. The real one is `HandlerRegistry.register_all`'s
own two `event_dir.glob("*.py")` loops (`registry.py:467`, `:511`), which
iterate in raw `os.scandir` order — a THIRD loop in the same file
(`iter_builtin_handler_classes`, line 198) already wraps its glob in
`sorted(...)`, so the inconsistency was local to this one function.
Wrapped both remaining loops in `sorted(...)`. RED:
`test_register_all_handler_order_is_independent_of_glob_order` patches
`Path.glob` to return a reversed listing and asserts registration order
is unaffected — failed against the pre-fix code (`normal_order != reversed_order`). Corrected the N7 ledger entry and commit-message
narrative; the injector- and docs_generator-level sorts from the first
pass were already sound regardless of this misattribution (the review's
own assessment, verified independently).

### n3 — `git_facts.py` stopped being core-free

Its own docstring claims "docs QA depends on this module alone"; my
earlier `project_relative_head_text` addition imported
`core.project_context` to call `ProjectContext.project_root()`, silently
breaking that claim (not caught by
`test_qa_package_dependency_direction.py`, which only forbids `plan_qa`
imports, not `core` ones — a real gap, but out of this branch's scope to
close). Fixed by taking `project_root: Path` as a parameter instead; both
callers (`goal_injection.py`, `recovery_cron_advisor.py`) already resolve
`ProjectContext.project_root()` unguarded for other purposes, so nothing
is lost. Updated both call sites and every test that monkeypatched
`utils.git_facts.ProjectContext.project_root` to patch the CALLER's own
import instead (or, in `test_git_facts.py`, to just pass the fixture's
`repo` path directly — no monkeypatch needed at all now).

### n6 — the promoted tier lost the config author's intent

Alphabetising the promoted tier (the N7 fix) satisfies determinism but
discards WHY a handler is promoted at all — the author's own
`promoted_handlers` list order, chosen so the most-triggered guidance
reads first. Kept the frozenset for the O(1) membership check in the
per-handler loop, and added `self._promoted_handlers_order: tuple[str, ...]` alongside it purely for the sort key, computed once over the much
smaller `promoted` list. RED:
`test_promoted_tier_follows_the_authors_promoted_handlers_order` (a
config with `zzz` listed before `aaa`) failed against the alphabetical
code (`zzz` sorted after `aaa` despite the config saying otherwise).

### n7 — release note title said "terminal-status"

In Progress is not a terminal status; the filename's own wording was
already correct. Retitled the note body's H1 to match, and rewrote it
comprehensively to describe M2/M3's preserved (not just removed)
behaviour instead of the stale "no action is needed" line.

### n4 — read, understood, deliberately left as designed

The two failure conventions genuinely differ (`_is_inside_project` fails
open on an uninitialised `ProjectContext`; `project_relative_head_text`
lets `RuntimeError` propagate) because the FIRST review pass explicitly
chose propagation for `project_relative_head_text`, reasoning that
`ProjectContext` is always initialised on the real dispatch path and a
`RuntimeError` there means genuine misconfiguration `core/chain.py`
already handles safely. The review itself filed this as the LOWEST
severity (nit) and noted it is "only reachable uninitialised". Rather
than re-litigate that design decision, made the two NEW M2/M3 helpers
(`_session_ledgered_plan`, `_maybe_reassert_for_new_session`) follow the
SAME propagate convention as `project_relative_head_text` — partly for
internal consistency, partly because `error_hiding` flagged the
None-returning `try`/`except RuntimeError` I had originally written in
`_maybe_reassert_for_new_session` (return type `-> None`, so a bare
`return` in the except branch is literally "return None on error"); the
existing `_ledger_record`/`_write_combined_signal` pattern (pre-existing,
unmodified) returns `[]`/calls a fallback instead of `None` and was not
flagged, which is why it hadn't surfaced before.

### Targeted QA and regression

```
./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding docs_qa plan_qa
```

`QA: 8/8 PASSED`, zero new exclusions (`error_hiding` needed the
`_session_ledgered_plan`/`_maybe_reassert_for_new_session` restructure
above before it passed clean).

Combined regression across every touched test file — `test_goal_injection.py`,
`test_recovery_cron_advisor.py`, `test_git_facts.py`, `test_goal_ledger.py`,
`test_claude_md_injector.py`, `test_docs_generator.py`, `test_registry.py`,
and the full controller test suite (`controller.py` was not touched again
this pass, but the earlier N7 fix stands) — **518 passed**.

Regenerated `.claude/HOOKS-DAEMON.md` and the CLAUDE.md `<hooksdaemon>`
block in this worktree; byte-identical to the already-committed tree (this
project's actual `promoted_handlers` config and on-disk handler file
listing were unaffected by the m6/n6 ordering fixes — the general fix is
what the new tests pin, not a visible diff here). Daemon restarted and
confirmed `Daemon: RUNNING` before the commit.

Commits: `7eb246dc` (the review fix-up); ledger update follows in the
commit that adds this section.

HEAD SHA at report time: see the commit that adds this update.
