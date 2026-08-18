# Plan 00257: the protected ref nobody qualified, and a QA gate that fails during releases

**Status**: In Progress
**Created**: 2026-08-18
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

Two blockers found by the v3.54.0 release's own gates, both code rather than
documentation. They are filed together only because they hold the same release;
they are unrelated defects.

The first is severe. `hooks-daemon delete-branch` measures every proof against
an UNQUALIFIED `protected_ref`, so a tag named `main` makes the whole engine
prove a property of the tag and then act on the branch. That mis-verdict is not
new — but until this cycle it produced tier `merged`, which delegates to
`git branch -d`, and git's own ancestry check refused. Plans 00249 and 00253
added `merged-unpushed` and `merged-not-in-head`, which return `--force`
precisely to bypass git's refusal. **This release removed the backstop that was
containing a pre-existing bug**, which is what turns it from latent to
destructive.

Plans 00254 and 00255 fixed exactly this defect class on the other two axes in
this same cycle — the branch under test, and `git_sync`'s merge base. The
protected ref is the third axis, and nobody looked at it.

The second is circular rather than dangerous: the QA suite now fails whenever a
release is in progress, which is the one moment RELEASING.md requires it to
pass.

## Goals

- No proof in `branch_safety` is measured against an ambiguous refname.
- A mis-proof can never reach a force-delete.
- QA passes while `untracked/release-state.json` exists.

## Non-Goals

- Not revisiting the tier model itself. `merged-unpushed` and
  `merged-not-in-head` are correct and well-argued; the defect is the base they
  are measured against.
- Not the documentation round — that is Plan 00256.

## Context & Background

### Blocker A: the unqualified protected ref

Reproduced end to end against real git 2.39.5. Repository with branch `main`,
branch `feat` holding a unique file, and a lightweight tag `main` pointing at
`feat`'s tip:

| Version | Tier                 | Delete argv     | Outcome                    |
| ------- | -------------------- | --------------- | -------------------------- |
| v3.53.1 | `merged`             | `git branch -d` | git REFUSED — branch lived |
| v3.54.0 | `merged-not-in-head` | `git branch -D` | deleted; unique file gone  |

`--dry-run` reports the same wrong verdict, so the human preview agrees with it.

Sites passing `protected_ref` unqualified: `branch_safety.py:420` (`cherry`),
`:519` (ancestry proof), `:545` and `:559` (object and path walks).
`DEFAULT_PROTECTED_REF = "main"` at `:86`.

Git itself warns `refname 'main' is ambiguous.` on every one of those commands,
and the engine discards that stderr.

### Blocker B: QA fails during a release

Three tests fail whenever `untracked/release-state.json` exists:

- `tests/integration/test_stop_chain_terminal_shadowing.py::TestThisProjectHasNotFallenIntoTheTrap::test_nothing_is_registered_after_the_handler_that_breaks_the_chain`
- `tests/acceptance/test_tool_use_error_recovery.py::test_tool_use_error_recovery_branch_fires`
- `tests/acceptance/test_tool_use_error_recovery.py::test_tool_use_error_recovery_branch_skipped_on_success`

One root cause. The shadowing test's docstring states it stubs git to a clean
tree "so the release guard's own" matcher stands down. This cycle changed
`release_blocker` to read the state file instead of the working tree, so
stubbing git no longer neutralises it. `release_blocker` is priority 8 and
terminal, so it shadows `auto_continue_stop` at 10 — which is precisely what
that test exists to detect. The test is right; its isolation went stale.

## Tasks

### Phase 1: Blocker A — qualify the protected ref

- [x] ✅ **Task 1.1**: RED — three tests in
  `TestASameNamedTagCannotHijackTheProtectedRef`. Two failed as predicted
  (`assert ('feat',) == ()` — the branch was force-deleted); the third, a
  legitimate `--protected-ref origin/main`, passed from the start and is what
  makes a blind `branch_ref(protected_ref)` wrong.
- [x] ✅ **Task 1.2**: GREEN — `_protected_base_ref` resolves the base once,
  immediately after the tip is recorded, probing with `show-ref --verify`
  exactly as `git_sync._merged_base_ref` does and falling back to the value as
  given. 78 tests in the file pass.
- [ ] ⬜ **Task 1.3**: Decide whether an ambiguous protected ref should be a
  blocking `REFUSAL_*` rather than merely qualified. Git emits
  `warning: refname '<x>' is ambiguous.` on every proof command and the engine
  discards that stderr, so the information is there for free. Qualifying is
  now correct either way; this would additionally TELL the human their repo
  has an ambiguous ref, which is worth knowing.
- [x] ✅ **Task 1.4**: Verified against a real repository, not only the unit
  tests: tier `unproven`, `is_safe` False, `deleted ()`, `refused` True, and
  `secret-work.txt` correctly named as content existing nowhere else.

### Phase 2: Blocker B — restore test isolation

- [x] ✅ **Task 2.1**: RED — confirmed. All three failed only because
  `untracked/release-state.json` existed.
- [x] ✅ **Task 2.2**: GREEN — the shadowing test now roots the chain walk at
  an empty `tmp_path` and patches `ProjectContext.project_root`, so it
  isolates against the state file the handler actually reads; the stale
  docstring describing the git stub is corrected. It passes WITH a release in
  flight, which is the only meaningful proof.
- [x] ✅ **Task 2.3** (widened by what it found): the acceptance pair exposed a
  PRODUCTION defect, not just a fixture one. `release_blocker` is terminal at
  priority 8, so during a release an agent hitting a `tool_use_error` received
  "a release is in progress" instead of the actionable Read-then-retry
  directive — the release message says nothing about the error just hit. It
  now stands down for that case, reusing `get_transcript_reader` so the two
  handlers cannot disagree about what a tool error is. Both deny the stop, so
  the release loses nothing and the guard fires again on the next attempt.
  The remaining negative-control test skips with a full explanation during a
  release, because the DEFAULT branch is genuinely unobservable over the
  socket while a terminal guard sits ahead of it — its real assertion (Branch
  2.5 must not fire on a clean turn) still runs.
- [ ] ⬜ **Task 2.4**: DBF, still open — a handler whose matcher changes
  silently invalidated the fixture isolating it, and nothing caught that. The
  general shape ("this fixture neutralises an input the handler no longer
  reads") may not be mechanically checkable; decide, and record either way.

### Phase 3: The abort deadlock (found by living it)

- [ ] ⬜ **Task 3.1**: `release_blocker._is_awaiting_publish_authorisation`
  only stands down at `last_completed_step >= 13`. RELEASING.md mandates ABORT
  on any failed gate (Steps 8-12), when the step is still below 13 — so the
  agent is denied the Stop it needs in order to REPORT the abort. Name deleting
  the state file as the abort action in the deny text, and allow the stop.

### Phase 4: The guard that could not see a module constant

- [x] ✅ **Task 4.1**: RED — four tests in
  `TestAModuleConstantIsNotAHidingPlace`. The two positives failed as
  predicted; the two negative controls (another tool's binary, an IMPORTED
  name) passed from the start and are what keep the fix from becoming the
  guessing the scanner's docstring rules out.
- [x] ✅ **Task 4.2**: GREEN — `_argv_starts_with_git` now resolves
  module-level string constants via `_module_string_constants`, reading only
  the module body. Applied to the real tree it found exactly one spawn and no
  false positives: `plan_qa/gitfacts.py:132`.
- [x] ✅ **Task 4.3**: Fixed that spawn — `_git_output` now routes through
  `run_git`, so the declined index lock applies and a wedged git yields the
  `None` the method already documents instead of a `TimeoutExpired` escaping
  into hook dispatch. `CHANGELOG.md`'s Plan 00246 entry corrected: it claimed
  the guard covered all of `src/`.
- [ ] ⬜ **Task 4.4**: Consider whether `run_git` should be the only *importable*
  path to git at all — an import-graph check would catch a future
  `import subprocess` in a module that has no business spawning anything,
  which is a strictly stronger guard than matching call shapes.

### Phase 5: Review findings captured, not fixed in the release

RELEASING.md forbids dropping a review finding: each is either fixed before the
release ships, or tracked here with file:line and severity and fixed
immediately after. These two are deliberately NOT fixed in the release — both
are no-op cleanups, and widening a release diff for a no-op is the wrong trade.

- [ ] ⬜ **Task 5.1** (LOW, dead code): eight handlers still read
  `self._languages or getattr(self, "_project_languages", None)` —
  `lint_on_edit.py:82`, `qa_suppression.py:87`, `error_hiding_blocker.py:94`,
  `security_antipattern.py:79`, `comment_changelog.py:202`,
  `comment_size.py:141`, `tdd_enforcement.py:189`, `pipe_blocker.py:329`.
  Plan 00251 made `Handler.__init__` set `self._project_languages = None`
  unconditionally, and all eight classes call `super().__init__()`, so the
  `getattr` default is provably unreachable. Replace with plain attribute
  access. No behaviour change — the point is that the declared type stops
  being contradicted by a workaround for a state that can no longer occur.
- [ ] ⬜ **Task 5.2** (UNCONFIRMED): the lost review also labelled an
  "unreachable `| None` branch". A targeted sweep of every `| None` introduced
  since v3.53.1 found no instance — each candidate is legitimately nullable
  (`tip_moved_since_proof`, `_discard_unused_bundle`, `_git_output`, the
  exclude-path sequences). Either find it or record that the label did not
  survive; an unrefuted label is not the same as a defect.

## Success Criteria

- [ ] The reproduction no longer deletes the branch
- [ ] No `branch_safety` proof is measured against a bare refname
- [ ] QA passes with a release state file present
- [ ] Daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed during the v3.54.0 release, from its Step 8 and Step 10 gates.
