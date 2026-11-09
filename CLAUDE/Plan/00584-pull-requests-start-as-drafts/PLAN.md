# Plan 00584: pull requests start as drafts

**Status**: Not Started
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An open pull request says "ready for review" by default, and agents open them long before the work is ready. Owner
request: every pull request starts as a draft, and leaving draft is a deliberate, explicit step.

GitHub's draft status is a separate field (`isDraft`, shown as a "Draft" badge); it never changes the title, and it
is unavailable on private repositories under GitHub Free. Owner rulings (2026-11-09):

- **The `[DRAFT]` title prefix is used everywhere**, on every repository, so any review or automation system can hold
  on it. Where GitHub offers native drafts, `--draft` is required as well, so the badge and the prefix agree.
- **Leaving draft removes the prefix in the same step.** `gh pr ready N` while the title still carries `[DRAFT]` is
  denied, and so is a title edit that drops the prefix while the PR stays a native draft. The fix text gives the
  combined form (title edit plus `gh pr ready`).
- **Returning to draft re-adds it**: `gh pr ready --undo` requires the title to regain `[DRAFT]`.

Whether a repository has native drafts is read once from GitHub (visibility and the owner's plan) and cached, never
queried on every command. No CI workflow in this repository filters on draft status, so a draft PR still gets the full
release gate.

Related, not duplicates (dedupe scout, 2026-11-09): Plan 00568 (`gh pr merge --admin` and the merge REST/GraphQL
routes, the same `gh pr` surface), Plan 00502 (merge requires approval: `gh pr ready` is the natural later point for
an approval or QA gate, left to 00502), Plan 00264 (comment size). Prior art: Plan 00275 (`github_auto_close_keywords`,
the existing `gh`/git message parsing). The handler follows Plan 00582's rollout standard and the #192 message
standard: every deny says why and what to do next.

## Goals

- `gh pr create` (and `gh api` POSTs to `.../pulls`) is denied unless the title starts with `[DRAFT]` and, on a
  repository with native drafts, `--draft`/`-d` is given.
- `gh pr ready N` is denied unless the same command also removes the prefix; `gh pr edit --title` dropping the prefix
  is denied unless it also marks the PR ready; `gh pr ready --undo` requires the prefix back.
- `gh pr create --web` and other routes the handler cannot judge get an advisory, never a silent pass.
- This repository's own PR-creating flows comply: the `/release` skill, `/release hotfix` and `RELEASING.md`.

## Non-Goals

- No approval or QA gate on `gh pr ready` (Plan 00502).
- No change to bot-opened PRs (Dependabot); the handler judges agent commands only.

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Decide the client default (enabled here; opt-in or advise-first for clients per Plan 00582) and
  how the handler reads the current title for `gh pr ready N` (one bounded `gh pr view --json title,isDraft`, or
  require the combined command form); record the rulings in this plan
- [ ] ⬜ **Task 1.2**: Native-draft capability check, read from Plan 00585's repository facts service (owner ruling:
  a rich, automatically refreshed metadata object). Repository facts are DETECTED from GitHub and cached, never
  hand-maintained in tracked config: config would drift the day a repository goes public or its owner changes plan.
  The cache stores the capability a handler needs ("has native drafts"), not raw plan tiers. Prior art:
  `utils/github_issue_validity.py` already looks up repository permissions lazily with TTL caches. Decide whether to
  lift that into one shared repository-facts service rather than add a second cache. A config value is allowed only
  as an explicit override (`auto` default, or forced on/off for offline or GitHub Enterprise hosts). Verify which
  probe is readable by a non-admin token before relying on it. Fail-safe when it cannot be read: require the prefix
  only.

### Phase 2: Build

- [ ] ⬜ **Task 2.1**: RED tests, then the handler: create, ready, edit, undo and REST routes, with the shared `gh`
  command parsing
- [ ] ⬜ **Task 2.2**: Update the release skill, the hotfix path and `RELEASING.md` to create `[DRAFT]` drafts and to
  mark ready with the prefix removed; a test pins the release flow's commands against the handler

### Phase 3: Delivery

- [ ] ⬜ **Task 3.1**: targeted QA, live probe, merge, verify CI

## Success Criteria

- [ ] Every rule in Goals is tested in both directions (denied without the prefix, allowed with it)
- [ ] The release and hotfix flows pass the handler (tested)
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` naming the new
  handler, its default and the `[DRAFT]` convention

## Delivery & Milestones

- (pending)
