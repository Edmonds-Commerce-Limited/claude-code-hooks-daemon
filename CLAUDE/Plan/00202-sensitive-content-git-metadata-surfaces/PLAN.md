# Plan 00202: sensitive content git metadata surfaces

**Status**: In Progress
**Created**: 2026-08-09
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The `sensitive_content` handler (Plan 00201) and its whole-tree QA backstop
guard file **contents**, and — since `fb91d81f` — file **paths**. That is two
of the seven surfaces that can carry a term into a git repository. The other
five are git *metadata*, and nothing in the daemon looks at any of them.

This is not a theoretical gap. It is measured. Cleaning this repo's own history
needed four distinct `git-filter-repo` mechanisms, because `--replace-text`
rewrites blob contents and nothing else:

| #   | Surface          | Rewrite mechanism   | Enters the repo via    | Guarded          |
| --- | ---------------- | ------------------- | ---------------------- | ---------------- |
| 1   | File contents    | `--replace-text`    | Write / Edit           | ✅ 00201         |
| 2   | File paths       | `--path-rename`     | Write / Edit           | ✅ `fb91d81f`    |
| 3   | Commit messages  | `--replace-message` | Bash `git commit`      | ❌ **this plan** |
| 4   | Author/committer | `--mailmap`         | Bash `git config`      | ❌ **this plan** |
| 5   | Tag names        | manual re-tag       | Bash `git tag`         | ❌ **this plan** |
| 6   | Tag messages     | manual re-tag       | Bash `git tag -m`      | ❌ **this plan** |
| 7   | Branch names     | manual rename       | Bash `git checkout -b` | ❌ **this plan** |

Every unguarded surface enters through **one tool** — `Bash` — which
`matches()` currently rejects outright: it fires only for `Write` and `Edit`.
So a single `git commit -m "<term>"` re-contaminates a repository that was
force-pushed clean, and both guards report all-clear afterwards, because the
scanner reads `git ls-files` blob contents and the handler never saw the call.

This plan closes the write-time gap for those five surfaces and — per the DBF
corollary that *every write-time rule needs a batch equivalent* — adds the
history sweep that covers metadata already committed.

## Goals

- `sensitive_content` inspects `Bash` commands that write git metadata, and
  denies with the same non-disclosure contract already in force (index only,
  never the term, path redacted).
- The QA backstop sweeps committed **history** metadata — commit messages,
  tag names, tag messages, author/committer identities, branch names — not
  just the working tree.
- Surface coverage is asserted by a test that enumerates all seven surfaces,
  so a future surface cannot be added silently without a guard.

## Non-Goals

- Rewriting history. That is `untracked/rewrite/refresh.sh`, already built and
  verified; this plan stops history needing to be rewritten *again*.
- Blocking git metadata commands wholesale. Only a term match denies.
- A new handler. This is the existing handler learning a second tool — a new
  handler would fork the secret-list loading and the non-disclosure contract,
  which is precisely the duplication that made the QA scanner drift in 00201.

## Context & Background

Two prior findings drive the design and must not be re-learned:

1. **Never reimplement the match test.** The 00201 scanner hand-rolled
   lowercase substring containment and could not see a path term's venv-slug
   spelling, so it reported a clean tree over a contaminated one. All matching
   goes through `utils/secret_redaction.term_matches`.
2. **The deny reason is an output surface.** The path-blindness fix had to
   redact `file_path` because the reason echoed it verbatim. A Bash deny
   reason must never echo the command string raw, for the identical reason.

## Tasks

### Phase 1: Write-time guard for git metadata

- [x] ✅ **Task 1.1**: Enumerate the git metadata write commands as named
  constants — no magic strings, one tuple per surface
- [x] ✅ **Task 1.2**: RED — tests per surface: term in commit message, tag
  name, tag message, branch name, `git config user.*`
- [x] ✅ **Task 1.3**: RED — negative controls: a clean `git commit`, a
  `git log`/`git show` **read** naming a term-free ref, and the escape a
  reviewer will ask about — a term appearing in a command that writes nothing
- [x] ✅ **Task 1.4**: GREEN — extend `matches()`/`handle()` to `ToolName.BASH`
- [x] ✅ **Task 1.5**: Deny reason redacts the command through `redact_text`;
  assert the term is absent from the ENTIRE response, not one field

### Phase 2: Batch equivalent — history sweep

- [x] ✅ **Task 2.1**: RED — fixture repo whose history carries a term in a
  commit message, a tag name, a tag message and an author id
- [x] ✅ **Task 2.2**: GREEN — sweep those surfaces via plumbing, reporting
  `rev`/`ref` + index, never the term
- [x] ✅ **Task 2.3**: Wire into `llm_qa.py` / `run_all.sh` as a check
- [x] ✅ **Task 2.4**: Confirm it reports 0 against the REWRITTEN mirror and
  non-0 against the pre-rewrite backup — the sweep's own negative control
- [x] ✅ **Task 2.5**: Grandfather the known-contaminated history so the gate is
  green (and therefore trusted) before the force-push, WITHOUT becoming an
  amnesty: commit baseline self-invalidates on rewrite, ref allowlist reports
  its own staleness

### Phase 3: Anti-regression

- [ ] ⬜ **Task 3.1**: A test that enumerates all seven surfaces and asserts
  each has a guard, so adding a surface without one fails
- [x] ✅ **Task 3.2**: `get_claude_md()` states the Bash coverage
- [x] ✅ **Task 3.3**: `get_acceptance_tests()` covers one metadata deny
- [ ] ⬜ **Task 3.4**: QA green, daemon restarts RUNNING, live probe via the
  daemon socket

## Technical Decisions

### Decision 1: Extend the existing handler rather than add a new one

**Context**: The metadata surfaces could be a separate `sensitive_git_metadata`
handler.

**Options Considered**:

1. New handler — clean separation, but forks secret-list loading, the
   redaction contract and the exclude-path logic across two files.
2. Extend `sensitive_content` to a second tool — one config key, one secret
   list read, one non-disclosure contract.

**Decision**: Option 2. 00201's own post-mortem was that a second
implementation of the same rule drifts from the first and reports clean while
the tree is dirty. The rule here is identical ("does this text carry a listed
term"); only the haystack differs, and the handler already takes a list of
haystacks after `fb91d81f`.

**Date**: 2026-08-09

## Success Criteria

- [ ] All five unguarded surfaces deny at write time on a term match
- [ ] The history sweep reports 0 on the rewritten mirror, non-0 on the backup
- [ ] No response on any surface contains a secret term — asserted against the
  whole serialised response, not a single field
- [ ] QA green; daemon restarts RUNNING; live socket probe confirms behaviour

## Delivery & Milestones

- Path surface closed ahead of this plan at `fb91d81f`
