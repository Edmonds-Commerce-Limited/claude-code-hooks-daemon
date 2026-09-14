# Plan 00407: niggles ledger twelve

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger eleven
([Plan 00405](../Completed/00405-niggles-ledger-eleven/PLAN.md)) is complete, so
this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

- [x] ✅ **N1**: two documents each claim the FIRST action of `/release`, and
  obeying them in the documented order makes the documented stop unreachable.

  **Found**: a human `/release` on a tree whose slate gate was not clean.

  `RELEASING.md` ("The release state file") says `/release` MUST write
  `untracked/release-state.json` as its **first action**. The skill's own
  `invoke.sh` output says Stage 0, the slate-clean gate, is what you
  `Run this yourself, in the main thread, first` — **before any agent is
  spawned**. Both say "first"; only one can be.

  Taking `RELEASING.md` literally writes the state file, and then Stage 0
  returns exit 2 with an explicit instruction: stop, show the human the report,
  end the turn with `STOPPING BECAUSE: [awaiting-human] the release slate is not clean`, and do NOT proceed. That stop is then **denied by the `release_blocker`
  Stop handler**, because a state file exists and its `last_completed_step` is 0.

  The handler's own route out is to DELETE the state file, which it correctly
  describes as *the abort action, not a pause button*. So the slate gate's
  documented outcome — "a human decides, and re-invokes `/release auto accept-wip`" — cannot be reported as written. It has to be reported as an
  ABORT, and the recorded authorisation is destroyed on the way.

  **Why it is worth an entry.** The two outcomes are not the same thing. "Paused
  at a gate that defers to you" and "aborted" read differently to whoever finds
  the transcript, and only one of them is what happened. The fix is a precedence
  sentence rather than new machinery: Stage 0 runs BEFORE the state file is
  written, because a release that never cleared the slate gate was never in
  flight, and writing the authorisation first is what manufactures the deadlock.

  **Fixed** as a precedence sentence, not new machinery. `RELEASING.md` ("The
  release state file") now states that Step 1a runs BEFORE the state file is
  written and why, and the skill — a thin shim — points at it rather than
  restating the order it previously contradicted.

  A second remedy is deliberately NOT taken, and is left for an owner ruling:
  making `release_blocker` stand down at `last_completed_step: 0`. It would be
  belt-and-braces, since nothing has changed at step 0 and that is definitionally
  not the half-done release the guard protects. It is left alone because the
  guard is a safety control, weakening one to fix a document is the wrong
  direction, and the ordering fix removes the deadlock on its own.

- [x] ✅ **N2**: `merge_to_main_approval` read a merge NAMED in a commit
  message as a real merge.

  **Found** by the release code-review gate, and reproduced against the real
  function before being believed. `merge_target` blanked quoted LITERALS but
  not a heredoc BODY, so `_GIT_MERGE_RE` matched prose inside one — including
  `git commit -m "$(cat <<'EOF' … EOF)"`, this repository's own canonical
  commit idiom. With the approval key on, any commit message describing a merge
  was denied, naming a remediation about a command the author never ran.

  This is the Plan 00377 N7 class that `destructive_git._scan_target` fixed in
  the same release — applied to one handler and not to its sibling. The fix is
  ordered, and the order is forced by a length property: strip the heredoc
  bodies FIRST (that collapses the body, so offsets move), then blank literals
  (which preserves length), and re-slice from the heredoc-stripped copy. Slicing
  the raw command would use offsets the strip has already invalidated; slicing
  the blanked copy would hand `shlex` a real branch name as a run of spaces.

- [x] ✅ **N3**: `daemon_location_guard` read a `cd` named in PROSE as a
  directory change.

  **Found by the daemon denying a review agent** as it wrote up N2: the report's
  prose quoted a `cd` into the daemon clone inside a `<<'EOF'` body, and the
  handler matched text bash was never going to execute. The same command's
  `destructive_git` check ALLOWED the identical heredoc, because it blanks inert
  spans first — a clean side-by-side demonstration, in one command, of a fix
  present in one handler and missing in its neighbour.

  Both passes are needed and neither subsumes the other: `strip_inert_spans`
  reaches heredoc and message bodies, while a bare `echo 'cd …'` is an ordinary
  quoted literal that only `blank_shell_literal_spans` reaches. The second was
  found by a failing test, not predicted.

- [x] ✅ **N4**: `deployed_artefact_drift` hardcoded `CLAUDE/Plan`, so a project
  with a configured plan directory got SILENCE from a drift detector.

  The directory is configurable and the installer honours it, but the handler
  carried no `PLANNING` tag, so the registry never injected the value. Every
  plan artefact then missed `is_file()`, the loop continued, and nothing was
  reported — no error, just quiet. That is exactly the "repairable but
  invisible" failure the handler was written to end. Its named sibling
  `plan_workflow_asset_checker` already did this correctly, which is what made
  the omission legible.

- [x] ✅ **N5**: `issue_filing_gate` missed `gh`'s DEFAULT way of naming a
  repository, and the hole led to a PUBLIC tracker.

  The gate resolved the target from `--repo`/`-R` or a `GH_REPO` assignment.
  `gh` has a third route and it is the default: with neither present it reads
  the base repository from the working directory's remotes. Every client install
  carries a clone of this repository under `.claude/hooks-daemon/`, so a bare
  `gh issue create` typed with the shell inside that clone filed a hand-written,
  unverified body upstream while the gate stood by.

  This is the guarantee Plan 00403 shipped — "nothing unchecked is filed" —
  failing on the most natural route in, and the consequence is a client's
  private material on a public tracker, which cannot be retracted. Resolution
  failure deliberately answers "not ours" rather than "assume upstream": gating
  an unresolvable cwd would deny a client's ordinary filing on their OWN
  tracker, which the module docstring names as the false positive that gets this
  handler switched off. The residual is now stated there rather than unnoticed.

- [x] ✅ **N6**: two review findings graduated rather than fixed here —
  see [Plan 00408](../00408-handler-hygiene-from-the-release-review/PLAN.md).

  Neither is user-visible breakage, so neither belongs in a release being cut:
  raw hook-field literals where `HookInputField` is declared the single source
  of truth (plus two duplicate `_CWD_FIELD` constants), and `merge_qa_report`
  building the full docs corpus on the hook budget while a sibling handler
  argues against exactly that in the same release. The four sub-bar items the
  reviewer listed are carried there too, so they are not lost.

- [x] ✅ **N7**: inserting two characters disabled R-GIT-CHECKOUT-DISCARD — a
  REGRESSION in this release, and the most serious finding of the session.

  `strip_message_bodies` (new this release) scoped message blanking to the
  BINARY, not the subcommand, and its value pattern had a bare-word fallback.
  For `git checkout`, `-m` selects merge-conflict style and takes NO value — so
  the next token, the `--` that makes the checkout destructive, was blanked as
  though it were commit prose, and the guard stopped matching.

  Reproduced twice: at the function level here, and end to end by the reviewer
  through the live PreToolUse hook in a scratch repo, where the `-m` form ran,
  exited 0 and permanently discarded a working-tree modification while the
  plain form was denied. The previous release blanked nothing here and denied
  both. **Not an evasion** — `git checkout -m` is a command a model can emit,
  and the loss is silent and permanent.

  Fixed by scoping to `(binary, subcommand)` with an ALLOWLIST, because the
  safe error is withholding an exemption. `checkout` and `branch` (`-m`
  renames), `cherry-pick` and `revert` (`-m` is a parent NUMBER) and `rebase`
  (`-m` is valueless) are all deliberately absent, each for a stated reason.

- [x] ✅ **N8**: a QUOTED destructive operand is not recognised — graduated to
  [Plan 00408](../00408-handler-hygiene-from-the-release-review/PLAN.md).

  Found while testing N7 and worth separating from it precisely because the
  first reading was wrong: `git checkout -m "--" f.txt` survived the N7 fix,
  which looked like the fix being incomplete. It is not — the plain
  `git checkout "--" f.txt` fails identically with no `-m` present, so blanking
  was never the cause and this pre-dates the release. Pinned by a strict xfail
  naming 00408, so it fails loudly if it is ever fixed by accident.

- [x] ✅ **N9**: the "never raises" boundary still raised on the commonest
  unreadable config, and this entry corrects [Plan 00405](../Completed/00405-niggles-ledger-eleven/PLAN.md)'s
  own N9 fix.

  That fix widened the catch to `ValueError`, reasoning that pydantic's
  `ValidationError` is one. `yaml.YAMLError` is NOT — it derives straight from
  `Exception` — so a config with a syntax error still escaped a boundary the
  router reaches while dispatching. The half left open was the MORE likely
  half: a schema mismatch needs a version skew, a stray tab needs a typo.

  Fixed at the source rather than at the catch site: `Config.load` now raises
  `ValueError` for malformed YAML, matching `ConfigLoader.load`'s existing
  contract and the JSON path, where `JSONDecodeError` already IS a `ValueError`.
  Every caller that reasonably catches "the config could not be read" as
  `ValueError` is now right, instead of only the one that was patched.

- [x] ✅ **N10**: the QA-lock advisory could abort the restart it only meant to
  warn about.

  `_qa_run_lock_holder` opened the lock file outside any `OSError` handling and
  nothing wraps the CLI's dispatch, so an unhandled exception ended
  `hooks-daemon restart` with a traceback — a STRONGER refusal than the one its
  caller's docstring promises never to make, on the most-used recovery verb.
  The window is ordinary: `is_file()` then `os.open` is two calls, so a QA run
  finishing in between unlinks the file. Unknown now degrades to "no warning",
  the only answer an advisory can safely give when it cannot tell.

- [x] ✅ **N11**: the plan index's closing self-check went stale again — the
  SAME line, in the same file, that [Plan 00405](../Completed/00405-niggles-ledger-eleven/PLAN.md)
  N4 already fixed one release ago.

  **Found by CI**, not by a local gate, which is the entry's point. The
  reconciliation bullet was recounted to 398 folders over **395 distinct**
  numbers against a counter of **408**, and the line under it still read
  `393 + 13 = 406. ✅` — the previous release's figures, still carrying their
  tick.

  Recounted from disk rather than patched to match, per the checker's own
  remediation: 24 + 361 + 13 = 398 folders, 395 distinct numbers, the
  duplicate-number set exactly `00034/00039/00041`, and the 13 folderless
  numbers exactly the set `comm` produces against the counter. Only the
  arithmetic line was stale, so `395 + 13 = 408. ✅` is the whole fix.

  **Why it recurred, which is the part worth recording.** 00405 corrected the
  numbers; nothing changed about how they are maintained. The bullet is
  hand-derived data with a tick that asserts it was verified, and the tick is
  what makes a stale line worse than no line.

  **The gate that would have caught it does not run where the edit happens.**
  `plan-stats-arithmetic` lives only in `scripts/qa/check_repo_hygiene.py` and
  its integration test — it is NOT one of the daemon's `plan-qa` checks. So
  `plan-qa --sweep` reported 0 findings against a README that was already
  wrong, and so did the commit gate, and so did `tests/unit/`. The only thing
  that fails is a full `tests/` run. That is why a defect fixed one release ago
  reached CI again unchallenged: every fast gate an agent actually runs is
  blind to it.

  Porting the rule to `plan-qa` — where the session sweep, the edit lint and
  the commit gate would all see it — is the structural fix, and is graduated to
  [Plan 00408](../00408-handler-hygiene-from-the-release-review/PLAN.md) rather
  than absorbed into a release being cut.

## Success Criteria

- [x] ✅ Every entry above is in a terminal state: N1–N5, N7, N9 and N10 fixed;
  N11 fixed with its structural half graduated; N6 and N8 graduated to
  Plan 00408.

- [ ] 🔄 Full QA passes and CI is green for every entry closed.

- [x] ✅ Release-bound consequences are in `CLAUDE/UPGRADES/UNRELEASED/` before
  the status flips, and only the ones a user can actually have seen.
  `release-notes/48-…` covers N2–N5, including the `issue_filing_gate` hole as
  a security fix; `46-…` was amended for N9, because the "never raises"
  boundary predates v3.63.0 and the malformed-YAML half was left open by the
  first fix.

  **N7 and N10 deliberately get NO release note**, which was checked rather
  than assumed: `strip_message_bodies` and `_qa_run_lock_holder` are both
  absent from the v3.63.0 tree, so both defects were introduced and fixed
  inside this unreleased range. A note would describe a regression no user ever
  received. N1 is a process-document correction with nothing to do.

## Delivery & Milestones

- Opened by N1, which was found by USING the release pipeline rather than by
  reading it — the contradiction is invisible until both documents are obeyed
  in the same run, and each is correct read on its own.
