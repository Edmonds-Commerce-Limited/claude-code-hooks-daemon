# Routine 00003: dependency updates

**Status**: Active
**Created**: 2026-11-09
**Owner**: dev
**Trigger**: schedule
**Period**: 7 days
**Grace**: 2 days

## Purpose

Dependency updates are merged as a matter of course, not as a question for the owner (owner ruling, 2026-11-09).
`.github/dependabot.yml` opens one grouped pull request per ecosystem each week (`uv` and `github-actions`), and
Dependabot opens a separate pull request for each security update. Left alone they go stale against `main`, their CI
results stop meaning anything, and known vulnerabilities stay on the default branch: on 2026-11-09 every push reported
112 open alerts, 7 critical, while five update pull requests sat unmerged.

## Scope

Every open pull request authored by Dependabot, in both ecosystems, including security updates. Each run takes every
such pull request to merged, or to a recorded blocker with a plan that clears it.

## Procedure

1. List them: `gh pr list --author app/dependabot --json number,title,headRefName,headRefOid,statusCheckRollup,comments`.
2. For each pull request whose checks ran against an old `main`, comment `@dependabot rebase` so CI reruns on the
   current one. Results from a stale base are not evidence either way.
3. **Green on the current base:** merge it with `gh pr merge N --merge --match-head-commit <sha>` (never squash or
   rebase), then `git pull --ff-only` and restart the daemon if `uv.lock` changed.
4. **Red:** a failure is work to finish, not a reason to skip. Diagnose it in a worktree from the pull request's
   branch. Fix this repository's code for the new version when the update is sound; pin or exclude a package only
   with a recorded reason and a plan to remove the pin. A grouped pull request that one package breaks may be split
   by excluding that package from the group until its fix lands.
5. A major-version bump gets the same treatment, plus a read of its changelog for behaviour changes the tests may not
   cover.
6. Record the run.

## What a run records

Every run appends one row to `RUNS/<year>.md`, covering:

- the interval it covered, `from -> to` (the `main` commit at each end);
- each pull request: merged (with its merge commit), or blocked (with the blocker and the plan that clears it);
- the open Dependabot alert count before and after, from the push output or `gh api`.

## Non-Goals

- No change to `.github/dependabot.yml`'s cadence or grouping except as a recorded step 4 split.
- No release: merged updates ship with the next release like any other change.
