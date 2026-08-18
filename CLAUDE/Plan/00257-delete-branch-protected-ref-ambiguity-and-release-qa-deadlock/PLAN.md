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

- [ ] ⬜ **Task 1.1**: RED — a test with a tag shadowing the PROTECTED REF,
  asserting the branch is not classified safe. The existing suite covers a tag
  shadowing the branch under test but has no case for the base.
- [ ] ⬜ **Task 1.2**: GREEN — resolve `protected_ref` once, using the same
  `show-ref --verify` probe shape as `git_sync._merged_base_ref`: qualify to
  `refs/heads/<name>` when it exists, otherwise pass through unchanged, since
  it may legitimately be `origin/main`, a sha, or `HEAD~3`.
- [ ] ⬜ **Task 1.3**: Decide whether an ambiguous protected ref should be a
  blocking `REFUSAL_*` rather than merely qualified. Git emits a warning the
  engine currently discards; failing safe with a message a human can act on may
  be the better contract.
- [ ] ⬜ **Task 1.4**: Verify by re-running the reproduction, not only the
  unit tests.

### Phase 2: Blocker B — restore test isolation

- [ ] ⬜ **Task 2.1**: RED — confirm the three failures reproduce with a state
  file present and pass without one.
- [ ] ⬜ **Task 2.2**: GREEN — isolate the tests against the handler's CURRENT
  input (the state file), not its former one (the working tree), and correct
  the stale docstring that describes the old mechanism.
- [ ] ⬜ **Task 2.3**: DBF — a handler whose matcher changes should not be able
  to silently invalidate the fixture that isolates it. Decide whether a guard
  is possible here or whether this is inherently a review-time concern.

### Phase 3: The abort deadlock (found by living it)

- [ ] ⬜ **Task 3.1**: `release_blocker._is_awaiting_publish_authorisation`
  only stands down at `last_completed_step >= 13`. RELEASING.md mandates ABORT
  on any failed gate (Steps 8-12), when the step is still below 13 — so the
  agent is denied the Stop it needs in order to REPORT the abort. Name deleting
  the state file as the abort action in the deny text, and allow the stop.

## Success Criteria

- [ ] The reproduction no longer deletes the branch
- [ ] No `branch_safety` proof is measured against a bare refname
- [ ] QA passes with a release state file present
- [ ] Daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed during the v3.54.0 release, from its Step 8 and Step 10 gates.
