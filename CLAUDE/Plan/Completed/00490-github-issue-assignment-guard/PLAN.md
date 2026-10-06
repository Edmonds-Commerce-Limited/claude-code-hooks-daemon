# Plan 00490: github issue assignment guard

**Status**: Complete
**Created**: 2026-10-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked for a new handler. When a session works on a GitHub issue, that issue must be assigned to the GitHub
account the session is signed in as:

- an issue assigned to nobody may be claimed (assigned to self), and work proceeds;
- an issue already assigned to self may be worked on;
- an issue assigned to someone else, and not to self, must not be worked on.

Sessions do not always work on GitHub issues, so nothing may force every session to have one. The rule applies only
when the work is tied to an issue. The main case is a plan that names its issue in the existing PLAN.md header
convention, `**GitHub Issue**: #N` (see CLAUDE/Plan/CLAUDE.md, "Plan sources").

The owner left the mechanism open ("exactly how you go about that I don't mind"), then steered it twice: the assignee
work is to be **deterministic code, with no agent turns spent on basic GitHub lookups**, wrapped in a **GitHub issue
validity** module with the assignee as one check among several; and an **author whitelist** is a major validity flag,
so agents only pick up issues created by approved identities, and that list is configurable. Items marked
**[coordinator call]** are defaults the owner may overturn. The plan follows the guard-effort pragmatism review
(Plan 00483 open question 4): it must not break ordinary sessions, and it stays off the hot path for anything not tied
to an issue.

## Goals

- A session cannot start or continue issue-tied work on an issue assigned only to someone else, or opened by an author
  nobody approved.
- A session working on an unassigned issue is told to claim it with one deterministic command before work continues.
- Work on a valid issue is never interrupted.
- Work not tied to an issue is never judged, slowed or denied by this handler.
- Looking up and claiming an issue costs no agent reasoning: code does it.

## Non-Goals

- Forcing every session to work on an issue.
- Multi-account `gh` setups. The owner's assumption is one sign-in. With more than one account, or none, the handler
  only advises.
- Judging issues in repositories other than the one the work is in.
- Changing who may be assigned. Org permissions are GitHub's business.
- The other validity checks listed below. The structure admits them; none is built now.

## Design

### The validity module (the owner's steer)

`src/claude_code_hooks_daemon/utils/github_issue_validity.py` is a deterministic checker with pluggable checks.

- **`ValidityCheck`** is a protocol: a `name`, a `needs_identity` flag, and `evaluate(facts, identity) -> CheckResult`.
  A result has a status (`ok`, `fixable`, `blocking`, `unknown`, or `n/a`), a message, and an optional deterministic
  **`FixAction`** (a `gh` argument list).
- **`IssueFacts`** come from ONE `gh issue view N --json assignees,state,author,labels` call per issue, cached with a
  TTL, with a timeout and an injectable runner, so no test touches the network. The signed-in login comes from
  `gh api user --jq .login`, resolved once per process. It is fetched only when a check needs it.
- **`check_issue(number, checks) -> ValidityReport`** returns the per-check results and an overall verdict. Precedence:
  blocked, fixable, unknown, valid.
- Only a settled state stays cached. A fixable or blocked report drops its cached facts, so the retry after a claim
  sees the new assignee at once. A failure is remembered for a minute, so an offline machine does not pay a timeout on
  every edit.
- Every login read from GitHub is validated against GitHub's login grammar. An unreadable login is replaced by a
  placeholder, never dropped: dropping an assignee could turn "someone else's" into "unassigned", which is claimable.

**Checks that ship:**

| Check                  | ok                          | fixable                      | blocking                                 | unknown               | n/a                          |
| ---------------------- | --------------------------- | ---------------------------- | ---------------------------------------- | --------------------- | ---------------------------- |
| `AssigneeCheck`        | self among the assignees    | nobody assigned; fix = claim | assigned to others only                  | no identity, no facts |                              |
| `AuthorWhitelistCheck` | author on the approved list |                              | author not on the list, or none recorded | no facts              | no list configured, or empty |

Author matching is case-insensitive (GitHub logins are). An empty list is treated like an absent one, never as a
lockout.

**Candidate checks, one new class each, NOT built now:** issue open or closed (a closed issue is not work to start);
a label rule (for example the issue-sdlc `agent-needs-human` label); a repository check (the issue belongs to this
repository, not a cross-reference); a "not already worked by another live plan" check.

### Strictness belongs to the caller

The module reports `unknown` and decides nothing about it.

- **The PreToolUse handler is lenient:** `unknown` only advises, once per failure window, and never denies.
- **The CLI is strict:** `unknown` is not eligible and exits non-zero, because the issue-sdlc author gate must never
  fail open. With no list configured, `--list-eligible` refuses to list at all.

### The author list: one home

The list is the handler option `approved_issue_authors` under
`handlers.pre_tool_use.github_issue_assignment_guard.options` in `.claude/hooks-daemon.yaml`. The config schema has no
shared `github` section, so the handler's own options are the home. The CLI reads the same key whether or not the handler
is enabled, so the handler, the CLI and the issue-sdlc runbook share one source. This repository's config is seeded with
the four logins the runbook used to carry in a table.

### The CLI: `bin/hooks-daemon issue-validity`

- `issue-validity N [--claim] [--json]` prints the report. With `--claim` code performs the claim
  (`gh issue edit N --add-assignee @me`) when, and only when, the verdict is fixable, so nothing is ever written to a
  blocked or unreadable issue. Exit codes: 0 valid, 1 blocked, 2 fixable and not fixed, 3 unknown, 4 usage or config.
- `issue-validity --list-eligible [--json]` prints the open issues that pass the author check, and how many it skipped.

### The handler: a thin consumer

`github_issue_assignment_guard` (PreToolUse) is judge-only. **Work is tied to an issue** when it is:

1. a Write/Edit of a tracked document inside a plan folder whose PLAN.md header carries `**GitHub Issue**: #N` (archived
   plans and the JOURNAL are never tied; a header with several issues ties to each);
2. a `git commit` that cites `#N` and names a plan (`Plan 00490`) whose header carries that same `#N`. A commit citing
   some other `#N`, such as a PR number, is not issue work.

Everything else exits in `matches()` after a string test or a path regex: no subprocess, no network, no file read.
A tied candidate reads one plan header, cached per plan file against its mtime.

| Report verdict | Handler                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------- |
| valid          | allow, silently                                                                                           |
| fixable        | deny, naming the ONE command: `bin/hooks-daemon issue-validity N --claim`, then retry                     |
| blocked        | deny: assigned to someone else, or author not approved. Do not work on it, do not claim it, write nothing |
| unknown        | allow with an advisory naming what could not be checked                                                   |

**[coordinator call]** The handler never writes to GitHub unless the option **`auto_claim`** is on (default off). With
it on, an otherwise valid unassigned issue is claimed inside the hook and the work goes ahead; a blocked issue is never
claimed.

**[coordinator call]** Defaults: enabled in this repository's own config, off by default in the shipped template for
client projects, until it has run here for a while.

## Tasks

### Phase 1: Confirm the ground

- [x] ✅ **Task 1.1**: Inventory where the `**GitHub Issue**: #N` header appears today, and how issue-sdlc starts issue
  work. Found 39 plan files carrying the header, in the forms `#N`, `#N, #M`, `#N (note)` and `(to be opened ...)`. The
  last form names no issue and is untied. The detection points above stand, with two adjustments: a header can name
  several issues, and the issue-sdlc runbook's "start work" step is the claim step (Task 3.1) rather than a hook
  detection point, because it happens before any plan exists.
- [x] ✅ **Task 1.2**: Probe `gh` read-only. `gh api user --jq .login` returns the login. `gh issue view N --json assignees,state,author,labels` returns the fields in one call, with `assignees: []` for an unassigned issue.
  Failure shapes: a missing issue exits 1 with "Could not resolve to an issue"; no auth exits 4 ("gh auth login"); a bad
  token exits 1 ("Bad credentials (HTTP 401)"); no network exits 1 with the dial error. Nothing was written to GitHub.

### Phase 2: The validity module, the CLI and the handler (TDD)

- [x] ✅ **Task 2.1**: Failing tests first for the module (every check, every verdict, caching, the author list absent,
  empty and present, case-insensitive matching), the CLI (exit codes, `--claim`, `--list-eligible` with the injected
  runner) and the handler (each verdict row, the tied and untied detection, the no-`gh` corpus).
- [x] ✅ **Task 2.2**: Implement `utils/github_issue_validity.py` with `AssigneeCheck` and `AuthorWhitelistCheck`.
- [x] ✅ **Task 2.3**: Implement the `issue-validity` CLI, with the claim performed by code, never for a blocked issue.
- [x] ✅ **Task 2.4**: Implement the handler as a consumer of `check_issue`, with the `auto_claim` option and its
  `get_acceptance_tests()`, CLAUDE.md guidance, rule IDs and config entries (enabled here, off in the client template).
- [x] ✅ **Task 2.5**: A regression corpus of ordinary non-issue commands and edits stays allowed and makes no `gh` call.

### Phase 3: Workflow and docs

- [x] ✅ **Task 3.1**: The issue-sdlc runbook selects issues with `issue-validity --list-eligible`, claims with
  `issue-validity N --claim` and acts on the exit code. Its author table and `jq` filter are replaced by a pointer to the
  config key; its safety reasoning (client-side filtering, untrusted comments, nothing written to an ineligible issue)
  stays.
- [x] ✅ **Task 3.2**: A release note, the config-changes entry and the handler reference entry.

### Phase 4: Verify

- [x] ✅ **Task 4.2**: Confirm, or make, `issue-validity --list-eligible` refuse to run when no
  `approved_issue_authors` list is configured, so the issue-sdlc selection never fails open (open question 4).
- [x] ✅ **Task 4.1**: Do a live dogfood check in this repository after a daemon restart:
  - an untied edit is silent;
  - an edit in a plan tied to an issue assigned to self is allowed;
  - an unassigned issue is denied with the claim command;
  - `bin/hooks-daemon issue-validity --list-eligible` lists only approved authors' issues.
- [x] ✅ **Task 4.3**: The coordinator merges the Task 4.2 branch and the full QA run on the merged tree passes; then
  close and archive this plan. Merged as `bb9bf1a98`; the full post-merge run over it (with the Plan 00483 Phase 2
  merge) found two Plan 00490 registry gaps, fixed in `24c68e67c` and `dd1afbc24`; its remaining findings were
  Plan 00483's (fixed in `a3b0df28a`, and N355); acceptance and semgrep green.

## Open questions for the owner

**Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** questions 1 to 3 are
decided as the defaults below. Resolved; not owner rulings.

1. **Resolved (coordinator call)**: tell the agent, do not auto-claim. Assignment publishes to GitHub.
2. **Resolved (coordinator call)**: off for client projects (the client template), on here.
3. **Resolved (coordinator call)**: advise, not deny, when `gh` cannot answer (offline, not signed in, several
   accounts), per the pragmatism review. The CLI is strict regardless.

Question 1 also settles whether auto-claim belongs in the hook: the `auto_claim` option exists and defaults to off.

4. **Resolved (Task 4.2)**: the handler keeps "no author check"; the `issue-validity` CLI refuses (exit 4) with no
   list. Original question: should an empty or absent `approved_issue_authors` mean "no author check" or "nobody is approved"? The
   build's default is "no author check", which avoids a lockout from a mis-edited config. Coordinator's
   recommendation: keep that for the handler. But the issue-sdlc selection (`issue-validity --list-eligible`) should
   refuse to run with no list configured, because the runbook requires that gate never to fail open. It is not yet
   confirmed whether the build already does that.

## Success Criteria

- [x] All verdict rows are pinned by tests, and the untied path makes no `gh` call.
- [x] The issue-sdlc runbook claims before working, stops on someone else's issue, and reads its author list from config.
- [x] The live dogfood check (Task 4.1) passes after a daemon restart.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/027-issue-validity-command-and-assignment-guard.md`,
  `UNRELEASED/release-notes/029-issue-validity-refuses-without-an-author-list.md`.

## Delivery & Milestones

- Delivered: merge `8846f9d77` (module, CLI, handler), merge `bb9bf1a98` (Task 4.2 CLI refusal), registry fixes
  `24c68e67c` and `dd1afbc24`.
