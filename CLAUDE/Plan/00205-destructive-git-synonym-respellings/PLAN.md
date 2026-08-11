# Plan 00205: destructive git synonym respellings

**Status**: Not Started
**Created**: 2026-08-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

v3.52.0 closed ten command-evasion bypasses across five blocking handlers. Every
one of those ten was an **invocation** respelling: git global options before the
subcommand (`git -C /path`), sudo's own flags (`sudo -H`), a path-qualified
binary (`/usr/bin/pip`), or a shell line continuation. The fix was structural —
`utils/command_evasion.py` holds the invocation grammars and continuations are
normalised once, where a command enters the daemon.

That hardening does not cover a second, independent class: a **synonym**
respelling, where a *different git command* performs the same destructive act.
The invocation is entirely ordinary; the verb is different. Two instances are
confirmed against v3.52.0 source, both found during the v3.52.0 release gate.

This is the same DBF shape as the ten: the guard matches the spelling it
expects, and an agent typing an equally ordinary alternative sails through.
Neither instance is a regression introduced by v3.52.0 — both predate it — but
`truth-changes/v3.52.0.yaml` initially claimed respelling immunity was now true,
which over-claimed in exactly the way `security_antipattern` did. That claim was
softened in the same release; this plan closes the actual gap.

## Goals

- Block `git update-ref -d refs/heads/<name>`, which deletes a branch ref with
  no merge check — an exact `git branch -D` equivalent.
- Block the `+refspec` force-push form (`git push origin +main:main`), an exact
  `git push --force` equivalent.
- Enumerate the remaining plumbing equivalents of every currently-blocked
  porcelain command, and decide each explicitly: block, or document as
  out-of-scope with a written reason.
- Extend the completeness-gated evasion suite with a synonym axis, so this class
  cannot silently escape triage the way the invocation class now cannot.

## Non-Goals

- No change to the invocation-respelling machinery in `utils/command_evasion.py`
  — it is correct for its class, and this is a different axis.
- No attempt to block every conceivable route to data loss (`git prune`, direct
  writes under `.git/`). The bar is *ordinary spellings a well-intentioned agent
  would type*, which is the bar the original ten were held to.

## Context & Background

Confirmed against v3.52.0 source:

| Blocked porcelain  | Unguarded synonym                | Evidence                                                                                           |
| ------------------ | -------------------------------- | -------------------------------------------------------------------------------------------------- |
| `git branch -D X`  | `git update-ref -d refs/heads/X` | `update-ref` appears nowhere under `src/claude_code_hooks_daemon/`                                 |
| `git push --force` | `git push origin +main:main`     | `destructive_git.py:45` `_GIT_PUSH_FORCE_PATTERN` matches only `--force`/`--force-with-lease`/`-f` |

The `+refspec` case is the more urgent: it is a published-history hazard
identical to `--force`, and `+` refspecs appear in ordinary CI and deploy
scripts, so an agent copying an existing script hits it by accident.

The `update-ref` case is lower frequency but was found in the sharpest possible
circumstance — a human was asked to run `git branch -D` manually while the agent
was blocked on it. The plumbing form was available and deliberately not used. An
agent under pressure to unblock itself is exactly the actor this guard exists to
stop, so the gap matters more than its frequency suggests.

## Tasks

### Phase 1: Enumerate the class

- [ ] ⬜ **Task 1.1**: Build the porcelain-to-synonym map for every entry in
  `_DESTRUCTIVE_PATTERN_REASONS`
  - [ ] ⬜ For each blocked porcelain form, list synonym spellings achieving the
    same destruction
  - [ ] ⬜ Probe each against the live daemon socket to record its actual
    decision, rather than reading the regex
  - [ ] ⬜ Classify every entry: must-block, or out-of-scope with a reason
- [ ] ⬜ **Task 1.2**: Repeat the sweep for the other hardened handlers
  (`git_stash`, `pip_break_system`, `sudo_pip`, `curl_pipe_shell`)

### Phase 2: TDD the two confirmed gaps

- [ ] ⬜ **Task 2.1**: `+refspec` force push
  - [ ] ⬜ Failing tests: `git push origin +main:main` and
    `git push origin +refs/heads/main:refs/heads/main`
  - [ ] ⬜ False-positive tests that must stay ALLOWED: a `+` inside a branch
    name, and `git push origin main:main` with no `+`
  - [ ] ⬜ Extend `_GIT_PUSH_FORCE_PATTERN` to cover a `+`-prefixed refspec
- [ ] ⬜ **Task 2.2**: `update-ref` branch deletion
  - [ ] ⬜ Failing test for `git update-ref -d refs/heads/<name>`
  - [ ] ⬜ False-positive test: `git update-ref` without `-d` stays ALLOWED
  - [ ] ⬜ Add the pattern with a reason naming the `git branch -d` alternative

### Phase 3: Close the class, not the instances

- [ ] ⬜ **Task 3.1**: Extend the completeness-gated evasion suite with a synonym
  axis, so each command-anchored handler must declare synonym coverage or be
  explicitly classified as having none
- [ ] ⬜ **Task 3.2**: Update `destructive_git.get_claude_md()` and
  `docs/guides/HANDLER_REFERENCE.md` with the newly blocked spellings
- [ ] ⬜ **Task 3.3**: Add `get_acceptance_tests()` entries for both new blocks

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ **Task 4.2**: Daemon restart, verify RUNNING, re-probe every spelling
  from Task 1.1 against the live socket
- [ ] ⬜ **Task 4.3**: Client-mode verification via `scripts/dummy-client-repo.sh`

## Dependencies

- Related: Plan 00202 (invocation-respelling hardening) — same DBF theme,
  orthogonal axis
- Related: Plan 00204 (security_antipattern over-claim) — same "guard claimed
  more than it did" failure mode

## Technical Decisions

### Decision 1: Deferred out of v3.52.0 rather than fixed in it

**Context**: Both gaps were confirmed during the v3.52.0 release gate, after QA
and acceptance had already passed.

**Options Considered**:

1. Fix in v3.52.0 — correct-by-release, but a code change at that point forces a
   full FAIL-FAST restart of the QA and acceptance gates, on a release that is
   already the vehicle for a history rewrite and so carries elevated risk.
2. Defer to this plan, and correct only the over-claiming documentation in
   v3.52.0 — doc-only, no gate re-run, and it removes the false statement that
   would otherwise ship.

**Decision**: Option 2. Neither gap is a regression introduced by v3.52.0, so
shipping them unchanged leaves users no worse off than v3.51.0. Shipping a claim
of immunity that is not true *would* leave them worse off, because a believed
protection lowers vigilance — the precise lesson of the `security_antipattern`
finding in the same release. The claim was corrected; the gap is tracked here.

**Date**: 2026-08-11

## Success Criteria

- [ ] `git push origin +main:main` is DENIED
- [ ] `git update-ref -d refs/heads/<name>` is DENIED
- [ ] Ordinary `git push origin main:main` and bare `git update-ref` stay ALLOWED
- [ ] Every entry in the Task 1.1 map is blocked or carries a written
  out-of-scope reason
- [ ] The evasion suite fails if a new command-anchored handler declares no
  synonym classification
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                                                | Impact | Probability | Mitigation                                                                                          |
| ------------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------- |
| A `+refspec` pattern false-positives on branch names containing `+` | High   | Medium      | False-positive tests written BEFORE the pattern, per the lesson of the widened `sudo_pip` near-miss |
| Blocking `update-ref` breaks legitimate script or daemon internals  | Medium | Low         | Scope the pattern to `-d` with a `refs/heads/` target; leave every other `update-ref` use untouched |
| The synonym axis is unbounded and the plan never converges          | Medium | Medium      | Non-Goals fixes the bar at "ordinary spellings"; Task 1.1 produces a closed, decided list           |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00205-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not started.
