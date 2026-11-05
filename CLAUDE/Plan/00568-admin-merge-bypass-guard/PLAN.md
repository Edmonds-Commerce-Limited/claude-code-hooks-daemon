# Plan 00568: admin merge bypass guard

**Status**: Not Started
**Created**: 2026-11-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #160

## Overview

A default branch can require an approving review while letting admins bypass
the rule. A session running with an admin's token can then merge a pull request
that is still blocked: `gh` refuses the blocked merge itself, and offers
`--admin` as the way past. No built-in handler notices. The nearest one,
`ancestry_preserving_merge` (Plan 00207), parses the same `gh pr merge` command
but only judges `--squash` and `--rebase`.

Issue #160 asks for a configurable PreToolUse Bash handler that denies the
admin-bypass merge routes and names the supported one: get the required
approval, then merge without the admin flag. Those routes are:

- `gh pr merge <n> --admin`, with the flag anywhere, including `--admin=true`;
- a non-GET call to the pull-request merge REST endpoint, through `gh api`,
  `curl` or `wget`;
- the `mergePullRequest` GraphQL mutation;
- each of these when wrapped.

These stay allowed:

- a plain `gh pr merge` with any merge method;
- a GET read of the merge endpoint;
- a mention in grep, echo, a commit message or a quoted heredoc body;
- `git push`.

This plan is filed at triage. It touches a safety control and adds a new
default behaviour, so under the issue runbook it waits on the owner's decisions
below before any code is written.

Dedupe: no live plan covers it (scout checked 61 of 61 live plans). Plan 00502
(merge requires approval) gates LOCAL worktree merges and does not touch
GitHub-side bypass. Plan 00207 is prior art for the `gh pr merge` flag parsing.

## Goals

- Deny the admin-bypass merge shapes listed above, unwrapped and in the common
  wrappers. The wrappers are `bash -c` (including nested), `xargs`, `env`,
  `sudo`, `timeout`, `nohup` and `command`, using the shared command-parsing
  utilities rather than new regexes.
- Allow every non-bypass form named in the Overview, each with a test.
- Make the deny message name the supported route.
- Provide an enabled switch and a repository allow-list where an admin merge is
  legitimate.

## Non-Goals

- Judging whether a merge would actually bypass protection. That needs a
  network call to GitHub at hook time, and the handler judges the command
  shape only.
- `git push` straight to a protected branch, which the issue explicitly leaves
  allowed.
- Plan 00502's local merge-approval gate.

## Open questions for the owner

1. **Ship it at all, and as which handler?** Recommended: a new handler,
   `admin_merge_bypass_guard`, separate from `ancestry_preserving_merge`,
   because it guards a different hazard. Alternative: a new pattern group inside
   `ancestry_preserving_merge`.
2. **Default on or opt-in?** Recommended: enabled by default. An agent rarely
   has a legitimate reason to override branch protection, and the allow-list
   covers the exceptions. A release note calls out the new deny. Alternative:
   shipped disabled, enabled by `optimise` where `gh` is in use.
3. **Allow-list shape.** Recommended: `allow_repositories: ["owner/name", ...]`,
   matched exactly against the repository named on the command (`-R`/`--repo`,
   or the REST path). A command with no repository named is judged against the
   current checkout's `origin`. Alternative: no allow-list, so a human runs the
   admin merge themselves.
4. **How deep to go into interpreter one-liners.** The issue asks for short
   Python and Node one-liners to be covered. Recommended: match the merge
   endpoint, or `mergePullRequest`, together with a write method in the
   one-liner's text. Do not attempt to parse the interpreter's code; the gap
   that leaves is stated in the docs.

## Tasks

### Phase 1: Tests first (after the owner's answers)

- [ ] ⬜ **Task 1.1**: Failing tests for every deny shape and wrapper listed in
  the Goals, and for every allowed form. The allowed forms are plain
  `gh pr merge` with each method, a GET read of the endpoint, mentions in
  grep, echo, printf, commit messages and quoted heredocs, and `git push`.
- [ ] ⬜ **Task 1.2**: Failing tests for the options (enabled, allow-list) and
  for the deny text naming the supported route.

### Phase 2: Implementation

- [ ] ⬜ **Task 2.1**: Implement the handler on the shared command-parsing
  utilities, reusing `ancestry_preserving_merge`'s `gh pr merge` parsing
  where it fits.
- [ ] ⬜ **Task 2.2**: Add a rule ID, `get_claude_md` guidance, acceptance
  tests, a `HANDLER_REFERENCE.md` section and the config example.

### Phase 3: Release-bound record

- [ ] ⬜ **Task 3.1**: Release-note callout in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (Audience: client projects).
  Add a config-changes manifest entry if the handler ships enabled.

## Success Criteria

- [ ] Every deny shape and every allowed form in the Overview has a passing
  test written first.
- [ ] The deny message names the supported route, and the allow-list exempts
  exactly the configured repositories.
- [ ] A release-note callout and any config-changes entry are present in the
  `CLAUDE/UPGRADES/UNRELEASED/` holding area.
- [ ] Targeted QA passes; the daemon restart is verified; a live check denies
  `gh pr merge 1 --admin` and allows `gh pr merge 1 --merge`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/YYYY-MM-DD/<entry>.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from issue #160 triage; parked on the owner questions above.
