# Plan 00408: handler hygiene from the release review

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Quality findings from the v3.64.0 release code-review gate that are NOT
user-visible breakage. They were deliberately graduated out of
[Plan 00407](../Completed/00407-niggles-ledger-twelve/PLAN.md) N6 rather than fixed
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

- [x] ✅ **Task 1.1**: Raw hook-field string literals where `HookInputField` is
  declared the single source of truth, plus two duplicate `_CWD_FIELD`
  constants. Mechanical, but worth doing as one pass so the declaration stops
  being aspirational. Check whether a test can hold the line afterwards —
  a rule nothing enforces drifts back.
  - Fixed across 35 modules. There were six `_CWD_FIELD` copies by then,
    not two. `tests/unit/constants/test_hook_input_field_single_source.py`
    holds the line with an AST scan of every read of `hook_input`. The one
    literal left is inside the project-handler scaffold that `cli.py`
    writes out as a string, so it is client code rather than a read.

### Phase 2: Cost on the hook budget

- [x] ✅ **Task 2.1**: `merge_qa_report` builds the full docs corpus inside a
  PostToolUse hook. The contradiction is what makes it worth a task rather than
  a shrug: a sibling handler argues against exactly that, in its own docstring,
  in the same release. Decide which position is right and make both agree —
  the answer may be that this one is fine and the sibling's caution is
  overstated, which is a legitimate outcome.
  - **Decided (unattended, 2026-09-24)**: both are right about different
    builds, so `merge_qa_report` now follows the cold-index rule. It still
    refreshes a warm index, and it stands down when there is no index. Measured
    on this repository: 0.19s warm and 3.7s cold, against a 5s handler budget;
    the handler runs only after a git command that moves history. Assumption:
    the owner's 'no known defects' instruction; the owner can reverse this with
    one message. Test: `test_a_cold_docs_index_is_not_built_inside_the_hook`.

### Phase 3: A quoted destructive operand

- [x] ✅ **Task 3.0**: `destructive_git` does not recognise a QUOTED operand:
  `git checkout "--" f.txt` is allowed where the unquoted spelling is denied,
  and bash removes the quotes before git ever sees them. Graduated from
  [Plan 00407](../Completed/00407-niggles-ledger-twelve/PLAN.md) N8.

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

  - Fixed with a shared `utils.command_evasion.remove_word_quoting`, which
    removes only quoting that cannot move a word boundary. The sibling sweep
    found the gap in eleven spellings across `destructive_git`'s rules
    (`test_destructive_git_quoted_operands.py`) and two in `git_stash`
    (`TestGitStashQuotedWords`). `ancestry_preserving_merge` already matched
    its quoted spellings. The xfail is now a plain pass.

### Phase 3b: A stats check no fast gate can see

- [x] ✅ **Task 3.2**: Delivered by Plan 00466 N13, on branch
  `worktree-n466-n13n14`. That branch moves the check into
  `plan_qa/checks/stats_arithmetic.py` as the one shared implementation,
  called by `check_repo_hygiene.py` and run in the commit gate. A second
  build here was withdrawn before commit, because two implementations of one
  check is the shape this plan exists to remove. Port `plan-stats-arithmetic` from
  `scripts/qa/check_repo_hygiene.py` into the daemon's `plan-qa` checks, so the
  session sweep, the edit-time lint and the commit gate all see it. Graduated
  from [Plan 00407](../Completed/00407-niggles-ledger-twelve/PLAN.md) N11.

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

- [x] ✅ **Task 3.2b**: `docs-qa`'s `pointer-resolves` check does not reach
  plans under `Completed/`, so a link broken BY archival is invisible to it.

  Measured, not suspected: archiving Plans 00406 and 00407 turned four
  `../00408-…` links and two `../Completed/00405-…` links dead — an archived
  plan's own relative paths all shift by one level — and a full
  `docs-qa --sweep` immediately afterwards reported "0 findings — documentation
  corpus is clean". The dead links were found by checking each target by hand.

  This is the same shape as Task 3.2: the failure is silence, and the check
  that would speak is the one that does not run here. Archival is exactly when
  these links break, and archival is a step an agent performs unattended.

  Decide deliberately whether `archive-immutability` is the reason for the
  exclusion — if archived plans are not to be edited, a dead link in one is
  arguably permanent by design. If so, the check belongs at archival TIME
  (verify every link in the moved folder resolves after the `git mv`) rather
  than in the sweep. Either answer closes this; leaving it unexamined does not.

  - **Decided (unattended, 2026-09-24)**: yes, `archive-immutability` is the
    reason for the exclusion, so the check runs at archival time. The new
    plan-QA COMMIT check `archival-links-resolve` looks at each `.md` file the
    commit renames into an archive directory. It BLOCKS a link the move broke
    and names the repoint that restores it, and it advises on a link that was
    already dead. Journals are skipped because they are append-only. The
    sweep exemption stays. Assumption: the owner's 'no known defects'
    instruction; the owner can reverse this with one message. Tests:
    `tests/unit/plan_qa/checks/test_archival_links_resolve.py`.

### Phase 3c: An allowlist of commands that do not run their argument

- [ ] ⬜ **Task 3.3**: (Open: it was not assigned in the 2026-09-24
  unattended pass.) `echo 'git merge x'` and `echo 'cd .claude/hooks-daemon'`
  are matched as real commands by `merge_to_main_approval` and
  `daemon_location_guard`. Graduated from
  [Plan 00407](../Completed/00407-niggles-ledger-twelve/PLAN.md) N12.

  This is the accepted cost of closing that entry's hole, not an oversight.
  `echo 'X'` and `bash -c 'X'` are structurally identical — a command with a
  quoted argument — so nothing in the text separates them. Only knowing that
  `echo` does not EXECUTE its argument does, which means an allowlist of inert
  commands (`echo`, `printf`, `:`, `true`), applied per segment head.

  Build it as an ALLOWLIST, per N7's rule: the safe error is withholding an
  exemption, because a missing entry costs a false positive while a wrong entry
  costs a guard. It belongs in `utils.shell_segmentation` beside
  `strip_inert_spans`, so all three guards get it at once rather than one
  growing a private copy — that divergence is what produced N2, N3 and N12 in
  the first place.

- [x] ✅ **Task 3.4**: `plan_number_helper` uses literal-blanking as an
  existence filter, the same shape N12 corrected in its two siblings —
  `blank_shell_literal_spans(strip_quoted_heredoc_bodies(command))` decides
  whether a `mkdir` of a plan folder is present, so `bash -c "mkdir …"` is
  missed.

  Carried here rather than fixed in the release because the consequence is a
  plan-number collision rather than a safety breach, and because it pre-dates
  this cycle — it is the idiom N2's comment cited as precedent, which is
  precisely how the mistake propagated. Verify the behaviour before changing
  it; the fix is the same one-line removal if it reproduces.

  - Reproduced and fixed. This is NOT ledger 00422 N28, which is about a
    relative `mkdir` resolved against the workspace root and waits on Plan
    00464's command-directory resolver. The mkdir rule now reads
    `strip_inert_spans` plus in-word unquoting, so `bash -c "mkdir …"` and a
    quoted plan-folder path both match
    (`test_a_quoted_creation_is_still_a_creation`). The discovery rules keep
    their literal blanking, where a literal is the signal.

- [x] ✅ **Task 3.5**: `pushd` walks past `R-DAEMON-DIR-CD`. The pattern
  anchors on `\bcd`, and `pushd .claude/hooks-daemon` changes the working
  directory exactly as `cd` does.

  Found while verifying Plan 00407 N12's fix rather than by reading the code:
  a probe of sixteen spellings a shell would really execute denied fifteen —
  `bash -c`, `bash -lc`, `sh -c`, `env bash -c`, `eval`, a leading variable
  assignment, `$( )`, backticks, a subshell, a line continuation, a quoted or
  single-quoted path, a trailing slash and an expansion-built path — and
  allowed `pushd`.

  **Pre-existing, not this release's regression**: `git show v3.63.0:…/daemon_location_guard.py` carries the same `\bcd` anchor, so the
  shipped version never matched it either. That is why it is graduated rather
  than fixed inside a release being cut, which is the same call made for N8 —
  and treating two identical situations differently because one file was
  edited more recently would not be a principle.

  It deserves priority over N8 nonetheless: N8 needs a deliberately quoted
  operand, whereas `pushd` is a spelling an agent emits naturally. Pinned by a
  strict xfail so it fails loudly if fixed by accident. The fix is one token —
  `\b(?:cd|pushd)` — but check `popd` and the `-` form too, and check whether
  the deny message still reads correctly when the command was not `cd`.

  - Fixed, and the xfail is now a plain pass. The rule text now reads
    "`cd`/`pushd` into …". **Decided (unattended, 2026-09-24)**: `popd` and
    `cd -` stay unmatched, because they name no path and the directory they
    return to was entered by an earlier command this rule already judged.
    Assumption: the owner's 'no known defects' instruction; the owner can
    reverse this with one message.

### Phase 3d: Release-documentation leftovers from the v3.64.0 gates

- [x] ✅ **Task 3.6**: Four documentation NITs the v3.64.0 Step 7 review raised
  and the release did not take. Recorded here because the review report lives
  under `untracked/agent-reports/`, which is gitignored — a finding that exists
  only in an untracked file is a finding that is already lost.

  - `CLAUDE/UPGRADES/v3/v3.63.0-to-v3.64.0/release-notes/` has no `20-` and two
    files numbered `24-`. Nothing is missing (`20-` was consumed by the v3.63.0
    cycle) and the count of 48 is right, but the directory cannot be indexed by
    number. Renumber if that is ever wanted.
  - GitHub issue **#38** is uncredited while **#37** is credited, for two
    externally-reported defects in the same release. Pick one convention.
  - The v3.63.0→v3.64.0 upgrade guide contains no markdown links at all, where
    its predecessor linked CHANGELOG and RELEASES. If links are added, the
    prefix from three levels down is `../../../../` — the depth is the thing
    that goes wrong here.
  - Two small shipped changes are in no release document: the `hooks-daemon`
    skill description gaining `optimise`/`bug-report`, and the `regen-docs.md`
    correction at `397cdde3`.

  None is user-visible breakage, which is why none held the release. Fold them
  into the next release's documentation pass rather than amending a published
  one.

  - **Decided (unattended, 2026-09-24)**, following this task's own "do not
    amend a published release" rule:

    - Numbering and links: declined. Both live only in the published
      v3.63.0→v3.64.0 directory, nothing is missing, and renumbering would
      break any link to those files.
    - #37/#38 credit: the convention is to credit, as
      `(reported as issue #N)`. It is recorded in
      `CLAUDE/UPGRADES/UNRELEASED/release-notes/README.md`, where callouts
      are written.
    - The two unmentioned skill changes: folded into the next release as
      callout `44-`.

    Assumption: the owner's 'no known defects' instruction; the owner can
    reverse this with one message.

### Phase 3e: The `review-n12` findings, rehoused from Plan 00409

These arrived with the finding that became
[Plan 00409](../Completed/00409-interpreter-heredoc-defeats-the-guards/PLAN.md) and were
recorded there first, because the alternative was losing them: the report lives
in `untracked/agent-reports/`, which is gitignored. They belong here — 00409 is
one shipped regression, this plan is the review's leftovers. Every reproduction
below was re-verified against the report and, where cheap, re-run on current
code.

- [x] ✅ **Task 3.7**: `merge_to_main_approval` misses two real merges. Both
  re-confirmed on current code after 00409 landed, so neither is a side effect
  of that fix:

  - `echo feature/x | xargs git merge` — the regex finds `git merge` but the
    segment holds no positional, so `_first_positional` returns None and
    `merge_target` answers "not a merge". The reviewer's suggestion is to treat
    a positional-less `git merge` as a merge under a placeholder key, which the
    `_GH_CURRENT_PR` pattern already establishes as an idiom.
  - `git pull . feature/x` — `git pull` is simply not in the pattern set, and
    with two positionals it performs a real merge into the checked-out branch.
    A separate pattern and a separate judgement call.

  `git merge $(cat branch.txt)`, `B=x; git merge $B` and `xargs -I{}` all DENY
  with a garbled name — fail-closed and cosmetic, explicitly NOT holes.

  - Fixed (`TestTwoMergesThatWereMissed`). A positional-less `git merge` is
    gated under `unnamed-branch`. **Decided (unattended, 2026-09-24)**:
    `git pull <remote> <branch>` is gated as a merge of that branch, whatever
    the remote is. A pull naming no branch, or naming the default branch
    itself (`git pull origin main` on `main`), is an ordinary update and is
    not gated. Assumption: the owner's 'no known defects' instruction; the
    owner can reverse this with one message.

- [x] ✅ **Task 3.8**: `issue_filing_gate._cwd_repo_slug` reads only
  `remote.origin.url` (`issue_filing_gate.py:258`), so a clone whose only
  remote is named `upstream` answers None and the gate stands down — while `gh`
  resolves its base repo from the remote SET and files against the PUBLIC
  tracker anyway. Any remote pointing at `UPSTREAM_REPO_SLUG` should answer
  "ours".

  **Record the correction, not just the finding**: answering "not ours" is the
  FAIL-OPEN direction here. The gate DENIES filings against upstream, so "not
  ours" means it never fires; "assume upstream" would over-deny a client's own
  filing at a cost of one refusal naming `hooks-daemon issue-report`. The
  module docstring argues that trade-off consciously, so this is a settled call
  being revisited on new evidence — that the fail-open is reachable — not a
  defect the code failed to consider.

  - Fixed. The new `GitRepo.remote_urls()` reads every remote, and a remote
    anywhere in the set that points at us engages the gate. The docstring of
    `_cwd_repo_slugs` records the correction.
    Tests: `test_a_clone_whose_only_remote_is_named_upstream_is_gated` and
    `test_any_remote_pointing_at_us_is_enough`.

- [x] ✅ **Task 3.9**: Six further `cd` spellings past `R-DAEMON-DIR-CD`, all
  verified `matches=False` through the live handler, all of which really do
  change directory. `pushd` is the seventh and is already Task 3.5.

  - `cd -- <path>` and `cd -P <path>` — `cd[ \t]+[^\s;&|]*` cannot span the
    whitespace after an option. `--` is the most plausible innocent spelling of
    the set; it is what a careful script writes.
  - `cd .claude/'hooks-daemon'`, `cd .claude/"hooks-daemon"`,
    `cd .claude//hooks-daemon`, `cd .cl\aude/hooks-daemon` — the pattern needs
    the path as one contiguous literal.

  The option forms are a regex fix (`\b(?:cd|pushd)(?:[ \t]+-[A-Za-z-]+)*`,
  plus `)` and a backtick in the terminating lookahead). The intra-token
  quoting forms need a normalisation step — drop quotes and backslashes,
  collapse `//` — not a wider regex.

  Deliberately NOT holes: a bare `cd` inside backticks and `(cd <path>)` both
  fail the lookahead, but a `cd` in a subshell that ends immediately changes
  nothing. Add a command after either and both match.

  - Fixed as specified: an option run, plus `)` and a backtick in the
    lookahead. The matched text is normalised first: every quote and
    backslash is dropped, so a path nested inside `bash -c '…'` is covered
    too, and `//` and `/./` are collapsed. The tests are in
    `TestEverySpellingThatReallyChangesDirectory`. `(cd <dir>)` now matches.
    That is fail-closed, as the lookahead change implies.

- [x] ✅ **Task 3.10**: Two `daemon/cli.py` nits from the same review. Both
  fixed: an unreadable held lock now reports `"unknown"`, and the explicit
  `LOCK_UN` is gone because `os.close` releases the lock. Tests:
  `test_an_unreadable_lock_body_still_warns_with_an_unnamed_holder` and
  `test_a_failing_unlock_is_survived`.

  - `cli.py:1699-1708`: the comment says "an unnamed holder is better than no
    warning at all", and the adjacent `except OSError` sets `holder = None`,
    which drops the warning entirely — only an EMPTY file gets `"unknown"`.
    Behaviour is unchanged from before the restructure; what the restructure
    did was put the contradiction on adjacent lines. One word fixes it:
    `holder = "unknown"`.
  - `cli.py:1713`: the `LOCK_UN` call sits in an `else:`, so an `OSError` from
    it propagates out of `_warn_if_qa_run_in_progress` and ends
    `hooks-daemon restart` with a traceback — the Plan 00407 N10 failure this
    function was hardened against. Very unlikely, and the `finally`'s
    `os.close` releases the lock regardless, which makes the explicit unlock
    redundant. Drop it or wrap it.

### Phase 4: The sub-bar items, carried so they are not lost

- [x] ✅ **Task 3.1**: Four items the reviewer put below the filing bar, each
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
  - **Decided (unattended, 2026-09-24)**. Assumption: the owner's 'no known
    defects' instruction; the owner can reverse this with one message.
    - `env`: fixed. It is treated like `nohup`, so it is flagged only when
      handed a shell (`env sh -c`).
    - `create_time`: fixed. A server whose start time is unreadable is
      skipped (`test_scan_survives_an_inaccessible_start_time`).
    - `_append_unique`: declined. On a case-insensitive filesystem both
      entries name the same absent path, and acting on either creates the
      same file. Folding them needs a filesystem case probe on every deny,
      which the Linux CI cannot exercise.
    - Config path: declined. `ProjectContext.initialize` rejects any config
      not at `<root>/.claude/hooks-daemon.yaml`, so the joined literal
      cannot diverge from `config_path()`. The join also honours the
      injected `_workspace_root` that the tests rely on, which
      `config_path()` would bypass.

## Success Criteria

- [ ] ⬜ Every task above is terminal: fixed, or declined with the reason
  recorded in the code or the plan rather than only here.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from Plan 00407 N6. The split is the point: the release review
  produced eight findings, and separating "a user is denied something they
  should be allowed" from "this is inconsistent with itself" is what let the
  first four ship the same day.
