# Plan 00408: handler hygiene from the release review

**Status**: Not Started
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Quality findings from the v3.64.0 release code-review gate that are NOT
user-visible breakage. They were deliberately graduated out of
[Plan 00407](../00407-niggles-ledger-twelve/PLAN.md) N6 rather than fixed
inside a release being cut: every one of them is internal consistency or cost,
none changes a verdict a user receives, and a release is the wrong moment to
take on a broad mechanical edit.

The four defects from that same review that WERE user-visible — two false
positives, a silently blind drift detector and a hole in the upstream filing
gate — were fixed in 00407 and shipped. This plan is the remainder.

## Goals

- Each item below is either fixed, or ruled not worth fixing with the reason
  recorded where the next reader will find it.

## Non-Goals

- Re-auditing the handlers already covered by the release review. This plan
  carries its leftovers, not a fresh sweep.

## Tasks

### Phase 1: Single source of truth

- [ ] ⬜ **Task 1.1**: Raw hook-field string literals where `HookInputField` is
  declared the single source of truth, plus two duplicate `_CWD_FIELD`
  constants. Mechanical, but worth doing as one pass so the declaration stops
  being aspirational. Check whether a test can hold the line afterwards —
  a rule nothing enforces drifts back.

### Phase 2: Cost on the hook budget

- [ ] ⬜ **Task 2.1**: `merge_qa_report` builds the full docs corpus inside a
  PostToolUse hook. The contradiction is what makes it worth a task rather than
  a shrug: a sibling handler argues against exactly that, in its own docstring,
  in the same release. Decide which position is right and make both agree —
  the answer may be that this one is fine and the sibling's caution is
  overstated, which is a legitimate outcome.

### Phase 3: A quoted destructive operand

- [ ] ⬜ **Task 3.0**: `destructive_git` does not recognise a QUOTED operand:
  `git checkout "--" f.txt` is allowed where the unquoted spelling is denied,
  and bash removes the quotes before git ever sees them. Graduated from
  [Plan 00407](../00407-niggles-ledger-twelve/PLAN.md) N8.

  Two things make it a task rather than an emergency. It pre-dates the release
  — the plain quoted form fails identically with no `-m` present, which is how
  it was separated from 00407 N7's regression — and it needs deliberate quoting
  rather than being a spelling a model emits by accident. It is nonetheless a
  data-loss guard that can be walked past, so it should not sit indefinitely.

  A strict `xfail` in `test_destructive_git_prose.py` pins it: fixing this
  turns that test green, and it fails loudly if the behaviour changes by
  accident. Check the sibling rules for the same gap before closing — the
  pattern of "fixed in one, missed in the neighbour" recurred four times in the
  review that produced this plan.

### Phase 3b: A stats check no fast gate can see

- [ ] ⬜ **Task 3.2**: Port `plan-stats-arithmetic` from
  `scripts/qa/check_repo_hygiene.py` into the daemon's `plan-qa` checks, so the
  session sweep, the edit-time lint and the commit gate all see it. Graduated
  from [Plan 00407](../00407-niggles-ledger-twelve/PLAN.md) N11.

  The case for it is a measured recurrence, not a preference. Plan 00405 N4
  fixed the plan index's closing self-check; one release later the same line in
  the same file was stale again, and `plan-qa --sweep`, the commit gate and
  `tests/unit/` all reported clean against it. Only a full `tests/` run fails,
  so the defect reaches CI every time — the fast gates an agent actually runs
  between edits are blind to exactly the file they most often edit.

  Consider also whether the bullet's closing line should be GENERATED rather
  than hand-maintained. A hand-derived figure carrying a ✅ that asserts it was
  verified is the specific shape that went stale twice; a check that catches it
  sooner is worth more than a third correction, and generating it would end the
  class outright. Either remedy closes this — prefer whichever leaves fewer
  hand-maintained numbers behind.

### Phase 4: The sub-bar items, carried so they are not lost

- [ ] ⬜ **Task 3.1**: Four items the reviewer put below the filing bar, each
  to be fixed or explicitly declined:
  - `utils/process_probe.py` lists `env` in `_WRAPPER_PID_SPECS`; GNU `env`
    execs without forking, so `env VAR=1 ./job & wait $!` draws an advisory for
    a pid that genuinely IS the job's. Noise tuning, not correctness.
  - `handlers/session_start/lsp_noise_checker.py:107` reads
    `float(info["create_time"])` outside the `try` that catches psutil errors.
    `process_iter` sets inaccessible attributes to None rather than raising, so
    the theoretical failure is `float(None)`. Almost certainly unreachable on
    Linux; one line to make it certain.
  - `handlers/pre_tool_use/tdd_enforcement.py` `_append_unique` compares
    `Path`s, so on a case-insensitive filesystem `tests/` and `Tests/` appear as
    two entries in the "locations searched" list. Cosmetic, but the list exists
    to be acted on.
  - `handlers/session_start/persistent_cron_assertor.py:74` hardcodes the config
    path rather than asking `ProjectContext.config_path()`. Pre-existing house
    style (three other handlers do the same), noted only because the argument
    against it is made in this same release by `daemon_sync_after_merge`.

## Success Criteria

- [ ] ⬜ Every task above is terminal: fixed, or declined with the reason
  recorded in the code or the plan rather than only here.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from Plan 00407 N6. The split is the point: the release review
  produced eight findings, and separating "a user is denied something they
  should be allowed" from "this is inconsistent with itself" is what let the
  first four ship the same day.
