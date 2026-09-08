# Plan 00205: destructive git synonym respellings

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Build the porcelain-to-synonym map for every entry in
  `_DESTRUCTIVE_PATTERN_REASONS`
  - [x] ✅ For each blocked porcelain form, list synonym spellings achieving the
    same destruction
  - [x] ✅ Probe each — via direct handler instantiation, not the live daemon
    socket (this worktree is instructed not to restart the daemon; the
    handler dispatch path probed is identical code either way) — to record
    its actual decision, rather than reading the regex
  - [x] ✅ Classify every entry: must-block, or out-of-scope with a reason.
    Result: `git branch -D`/`git push --force` each have exactly one ordinary
    plumbing synonym (fixed in Phase 2); the other 7 rules (`reset --hard`,
    `clean -f`, `checkout .`/`checkout -- <file>`, `restore`, `stash drop`,
    `stash clear`, `commit --amend`) have none — every plumbing equivalent is
    a multi-step sequence, not a single ordinary spelling. Recorded in
    `tests/unit/handlers/pre_tool_use/test_command_synonym_evasion.py`.
- [x] ✅ **Task 1.2**: Repeat the sweep for the other hardened handlers
  (`git_stash`, `pip_break_system`, `sudo_pip`, `curl_pipe_shell`). Result: no
  ordinary synonym found for any of the four — each already covers every
  ordinary invocation shape (e.g. `pip`/`pip3`/`python -m pip` together), and
  no other command performs the same act. Reasons recorded in
  `_NO_ORDINARY_SYNONYM_KNOWN` in the same test file.

### Phase 2: TDD the two confirmed gaps

- [x] ✅ **Task 2.1**: `+refspec` force push
  - [x] ✅ Failing tests: `git push origin +main:main` and
    `git push origin +refs/heads/main:refs/heads/main`
  - [x] ✅ False-positive tests that must stay ALLOWED: a `+` inside a branch
    name, and `git push origin main:main` with no `+`
  - [x] ✅ Extend `_GIT_PUSH_FORCE_PATTERN` to cover a `+`-prefixed refspec
- [x] ✅ **Task 2.2**: `update-ref` branch deletion
  - [x] ✅ Failing test for `git update-ref -d refs/heads/<name>`
  - [x] ✅ False-positive test: `git update-ref` without `-d` stays ALLOWED
  - [x] ✅ Add the pattern with a reason naming the `git branch -d` alternative

### Phase 3: Close the class, not the instances

- [x] ✅ **Task 3.1**: Extend the completeness-gated evasion suite with a synonym
  axis, so each command-anchored handler must declare synonym coverage or be
  explicitly classified as having none. New file
  `tests/unit/handlers/pre_tool_use/test_command_synonym_evasion.py`,
  deliberately scoped to the 5 handlers Phase 1 actually swept (see its
  module docstring "Scope, deliberately bounded") rather than claiming
  completeness over every command-anchored handler in
  `test_blocking_handler_evasion.py`.
- [x] ✅ **Task 3.2**: Update `destructive_git.get_claude_md()` and
  `docs/guides/HANDLER_REFERENCE.md` with the newly blocked spellings
- [x] ✅ **Task 3.3**: Add `get_acceptance_tests()` entries for both new blocks

### Phase 4: Verify

- [x] ✅ **Task 4.1**: QA on touched files (black, ruff, mypy --strict, bandit,
  deptry — all clean) plus the full `pytest tests/unit` (16,545 passed) and
  `tests/integration` (3,111 passed) suites. Two failures observed are
  pre-existing and unrelated: an `error_hiding` self-scan finding and a
  magic-timeout finding, both in `install/transport_verify.py` and its test —
  a file this plan never touched — plus one flaky `CLAUDE.md`-rewrite
  assertion in `test_forwarder_socket_stdin.py` that passed cleanly on
  isolated re-run. The full `./scripts/qa/llm_qa.py all` (which ends in a
  live-daemon smoke test) was not run — out of scope for this worktree, which
  is instructed not to restart the daemon.
- [ ] ⬜ **Task 4.2**: Daemon restart, verify RUNNING, re-probe every spelling
  from Task 1.1 against the live socket — **explicitly out of scope for this
  worktree** (its operating instructions forbid restarting the daemon). Left
  for the merge/release step that does restart it.
- [ ] ⬜ **Task 4.3**: Client-mode verification via `scripts/dummy-client-repo.sh`
  — **deferred alongside Task 4.2** for the same reason; not attempted here.

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

- [x] `git push origin +main:main` is DENIED
- [x] `git update-ref -d refs/heads/<name>` is DENIED
- [x] Ordinary `git push origin main:main` and bare `git update-ref` stay ALLOWED
- [x] Every entry in the Task 1.1 map is blocked or carries a written
  out-of-scope reason
- [x] The evasion suite fails if a handler in its (deliberately bounded, see
  Task 3.1) swept universe declares no synonym classification
- [x] QA passes on all touched files and the full unit/integration suites
  (two unrelated pre-existing findings noted in Task 4.1); daemon restart and
  live-socket verification (Tasks 4.2/4.3) deferred — out of scope for a
  worktree instructed not to restart the daemon
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/08-destructive-git-synonym-respellings-closed.md`

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

- Both confirmed gaps closed (`+refspec` push, `git update-ref -d refs/heads/<name>`), the porcelain-to-synonym enumeration for
  `destructive_git` plus the four Task 1.2 siblings recorded, and the
  synonym-axis completeness gate added, scoped to the handlers actually
  swept. Delivered at `60cff2b3` on branch `agent-ad51d578783570fa0-e770e7cb`.
