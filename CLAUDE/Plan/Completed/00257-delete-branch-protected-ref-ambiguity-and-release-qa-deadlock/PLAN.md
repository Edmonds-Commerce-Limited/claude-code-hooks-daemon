# Plan 00257: the protected ref nobody qualified, and a QA gate that fails during releases

**Status**: Complete
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
- [x] ✅ **Task 1.3**: Decided — **not a refusal**. `delete-branch`'s contract is
  to refuse when it cannot PROVE safety. After Task 1.2 it can:
  `_protected_base_ref` resolves the base deterministically via
  `show-ref --verify` before any proof runs, so every tier measures the
  intended ref and ambiguity elsewhere in the repo no longer affects
  correctness. Refusing would block a provably-safe deletion because of an
  unrelated repository condition — punishing the user for a hygiene problem
  the tool has already routed around. Telling the human is still worth doing,
  but it is a REPORTING change, not a safety gate, and it belongs with the
  other reporting work rather than in this plan's blast radius.
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
- [x] ✅ **Task 2.4**: DBF — decided, and the answer is **not mechanically
  checkable, so record the convention instead**. Detecting "this fixture
  neutralises an input the handler no longer reads" requires knowing which
  inputs a handler reads, which is dataflow analysis across config, helpers
  and transcript readers. A checker that guessed would fail exactly where this
  one did, only louder.
  - The cheap general form — "an isolation fixture must be LOAD-BEARING, i.e.
    removing it must change the outcome" — is mutation testing, and running it
    across the suite costs more than the class of bug it catches.
  - Convention recorded instead: **a fixture that exists to isolate must
    assert what it isolates against.** Task 2.2's replacement does exactly
    this — it patches `ProjectContext.project_root` and passes WITH a release
    in flight, so the isolation is proved by the test rather than assumed by
    its author. A fixture that merely sets a value proves nothing once the
    matcher moves.

### Phase 3: The abort deadlock (found by living it)

- [x] ✅ **Task 3.1**: Fixed in the deny TEXT, deliberately not in `matches()`.
  The mechanism out already existed — no state file means no release in
  flight, so deleting it releases the guard — and a test now pins that. What
  was missing was any statement of it, and an undocumented escape hatch is
  indistinguishable from none: the agent retries, is denied again, and burns
  turns. The deny text now names the file to delete, uses RELEASING.md's own
  word (ABORT) so the two connect, and requires reporting which gate failed.
  - **Why not widen `matches()`**: no signal in a Stop event distinguishes
    "aborting a failed gate" from "avoiding the acceptance suite", and this
    handler exists specifically to stop the latter. Detecting an abort would
    mean trusting the agent's own say-so about the one thing it is most
    motivated to misreport. A second test asserts the message warns against
    deleting the file merely to end the session, so making the exit
    discoverable does not make it attractive.

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
- [x] ✅ **Task 4.4**: Considered and **declined**, on evidence gathered while
  considering it. Five handler modules import `subprocess`; three do so
  legitimately (`lint_on_edit` and `validate_eslint_on_write` spawn linters,
  not git) and two import it only for exception TYPES while already using
  `run_git`. So an import-graph check would need an allowlist covering the
  majority of its own hits, and an allowlist that large is the "list of
  whatever failed last" this plan's `_EXEMPT` docstring warns against.
  It would also not have caught the real defect: the offender imported
  `subprocess` legitimately-looking and hid in the ARGV, which is a call-shape
  problem. Closing the call-shape guard's remaining hiding place (Task 4.5) is
  narrower, needs no allowlist, and is evidenced by a live instance.
- [x] ✅ **Task 4.5** (found while auditing 4.4): the guard resolved module-level
  STRING constants but not module-level SEQUENCE constants, so
  `subprocess.run(list(_GIT_HOOKS_PATH_CMD))` was invisible. Verified before
  fixing: `_direct_git_spawns` reported "NO direct git spawns" for the whole
  tree while `git_hooks_executable_fixer.py:85` demonstrably spawned git. This
  is the Plan 00246 escape recurring one container out — `list(...)` around a
  constant changes the container and nothing else. Fixed with
  `_module_sequence_constants` + `_argv_words`, covering a bare `NAME`, a
  `list(NAME)`/`tuple(NAME)` wrapper, and the existing literal. Three negative
  controls (another tool, an unbound name, a mixed-type sequence) passed from
  the start, which is what keeps the widening from becoming guessing.
- [x] ✅ **Task 4.6**: fixed what 4.5 exposed. `git_hooks_executable_fixer` now
  routes through `run_git`, so it inherits the declined index lock and the
  timeout. Two follow-on corrections fell out of it:
  - `import subprocess` and its `# nosec B404` are gone from the module
    entirely — `run_git` never raises, so the exception handling it existed
    for is unnecessary.
  - It passed `cwd=None` to `subprocess.run` when the event carried no cwd,
    which inherits the DAEMON's working directory — and that is `/`, never the
    project (the Plan 00237 scoping shape). git then failed in a
    non-repository and the handler silently did nothing, which reads exactly
    like a repo with nothing to fix. `_repo_root` now falls back to
    `ProjectContext.project_root()` and reports visibly when neither resolves.

### Phase 5: Review findings captured, not fixed in the release

RELEASING.md forbids dropping a review finding: each is either fixed before the
release ships, or tracked here with file:line and severity and fixed
immediately after. These two are deliberately NOT fixed in the release — both
are no-op cleanups, and widening a release diff for a no-op is the wrong trade.

- [x] ✅ **Task 5.1** (LOW, dead code): done — all eight sites now read
  `self._languages or self._project_languages`. Unreachability re-verified
  before touching anything rather than taken from the note: `handler.py:124`
  assigns the slot unconditionally in `__init__`, it is declared in
  `__slots__`, and all eight classes call `super().__init__()` exactly once.
  `tests/unit/core/test_handler.py:229` already asserts it reads as `None`
  before injection. 263 tests pass across the affected handlers. No behaviour
  change — the point is that the declared type stops being contradicted by a
  workaround for a state that can no longer occur.
- [x] ✅ **Task 5.2** (UNCONFIRMED → **recorded as not surviving**): the lost
  review labelled an "unreachable `| None` branch". A targeted sweep of every
  `| None` introduced since v3.53.1 found no instance — each candidate is
  legitimately nullable (`tip_moved_since_proof`, `_discard_unused_bundle`,
  `_git_output`, the exclude-path sequences). Closing it as **not reproduced**
  rather than leaving it open: an unrefuted label is not a defect, and a task
  that can never be discharged is indistinguishable from one nobody looked at.
  Reopen if a specific file:line is ever produced.

## Success Criteria

- [x] The reproduction no longer deletes the branch (Task 1.4, verified against
  a real repository: tier `unproven`, `refused` True, `deleted ()`)
- [x] No `branch_safety` proof is measured against a bare refname (Task 1.2 —
  `_protected_base_ref` resolves once, before any proof is computed)
- [x] QA passes with a release state file present (Task 2.2 — the shadowing
  test roots its chain walk at an empty `tmp_path` and patches
  `ProjectContext.project_root`, so it isolates against the file the
  handler actually reads)
- [x] Daemon restart RUNNING (re-verified after every change in this plan)
- [x] A failed BLOCKING gate cannot trap the session (Task 3.1, verified live
  over the socket in both directions)
- [x] No module spawns git outside the bounded runner, and the guard can SEE
  the shapes that occur (Tasks 4.5/4.6)

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed during the v3.54.0 release, from its Step 8 and Step 10 gates.
