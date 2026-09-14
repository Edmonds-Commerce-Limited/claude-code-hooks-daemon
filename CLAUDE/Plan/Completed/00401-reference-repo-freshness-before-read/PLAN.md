# Plan 00401: reference repo freshness before read

**Status**: Complete
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Reference repositories are cloned under `untracked/repos/` as a cross-project
convention. Agents read them without pulling first, so they reason from a
checkout that may be weeks behind the remote — and **stale reasoning is
indistinguishable from correct reasoning** at the point it is produced. Nothing
currently notices.

This plan makes a governed reference repo fresh before it is read, and gives the
project one DRY checker that reports every reference repo that is stale or off
its default branch — exposed as a SessionStart sweep and a CLI command.

Prior art is close and directly reusable: Plans 00178 and 00179 solved this for
the project's OWN repo. `utils/git_sync.py` is already repo-agnostic (every
function takes `cwd: Path`), so no new git plumbing is needed — only discovery,
caching, enforcement and reporting.

## Evidence gathered before designing

Measured against the one repo currently under `untracked/repos/` here:

```text
current_branch : php8.4        default_branch : php8.4
upstream_status: behind=0, ahead=1
working_tree_clean: False
origin: https://invalid.invalid/canary.git  -> Could not resolve host
```

Three facts that each constrain the design, and would each have produced a
harmful implementation if assumed away:

1. **The default branch is NOT `main`.** `git_sync.default_branch` resolves
   `origin/HEAD` correctly (`php8.4`). Anything that hardcodes `main` reports a
   false "not on default branch" for this repo.
2. **A reference repo can be un-fetchable BY DESIGN.** The canary's `origin` is
   deliberately replaced with an invalid URL (Plan 00291's rule: "with no
   remote, a push cannot happen even by accident"). A system that blocks reads
   of repos that are "not up to date" would lock this repo out permanently,
   because it can never be brought up to date.
3. **A reference repo can be dirty and ahead.** This one is `ahead 1` with
   uncommitted changes. A blind `git pull` would conflict or destroy work.

Measured cost, which decides the architecture below: `fetch_all` against the
unreachable origin returns `False` in **0.02s** — fail-silent, no hang. But
`Timeout.GIT_FETCH_SESSION` and `GIT_PULL_SESSION` are both **30s**, against a
**30s hook socket budget**.

## Owner rulings

| Question    | Ruling                                                                             |
| ----------- | ---------------------------------------------------------------------------------- |
| Enforcement | **Block once per repo, per session** as the DEFAULT — and the mode is configurable |
| Auto-pull   | **The daemon pulls when provably safe**; reports and never touches otherwise       |
| Scope       | **Configurable roots, auto-discover** every git checkout beneath them              |

## Architecture: PreToolUse performs NO network I/O

Forced by the measurement above, not by preference. A fetch+pull inside
PreToolUse can consume the entire 30s socket budget for ONE repo, and there can
be several — reproducing the `socket_timeout` failure mode the daemon already
has dedicated error text for.

So the network work happens at **SessionStart**, which already owns that budget
and already fetches for the project's own repo. By the time any read happens,
governed repos have been fetched and safely pulled. The PreToolUse handler reads
**cached state only** and is the backstop for a repo that goes stale mid-session
or failed the safe-pull.

A cache entry that is missing or past its TTL is treated as NOT VERIFIED, which
still enforces — it must never silently read as fresh.

## Safety invariants

Each is a rule the implementation must not be able to violate:

- **Un-checkable ⇒ never blocks.** No origin, unreachable, or no upstream is
  reported once and then stays out of the way. This is what keeps the canary
  usable.
- **Dirty, ahead, or diverged ⇒ never pulled.** Report only. Reuses the refusal
  logic already proven in `git_upstream_checker._auto_pull`.
- **The remediation command is exempt.** A handler that blocks
  `git -C untracked/repos/foo pull` makes its own instruction unreachable. The
  git commands that inspect or update a governed repo must pass through.
- **The daemon's own pull must not re-enter** the interception path.

## Goals

- A governed reference repo is fresh before an agent reads it, or the agent is
  told it is not.
- One checker, three surfaces (PreToolUse, SessionStart, CLI) that cannot drift.
- The convention works unchanged in any project that adopts it, with zero config
  for the default root.

## Non-Goals

- Managing what is cloned, or cloning anything. This plan governs freshness of
  repos that already exist.
- Pulling a repo that is dirty, ahead or diverged — reported, never resolved.
- Governing the project's own repository; Plans 00178/00179 already do that.

## Tasks

### Phase 1: The DRY checker (`reference_repos/` package)

- [x] ✅ **Task 1.1**: `discovery.py` — enumerate git checkouts under configured
  roots, apply exclude globs. Reuse `utils/path_exclusion.py`. A checkout is a
  `.git` of EITHER kind (a worktree's is a file), is never descended into, and
  the walk is depth-bounded so a root of `/` cannot become a filesystem sweep;
  a non-positive bound finds nothing rather than everything. 23 tests, 100%
  coverage of the module.

- [x] ✅ **Task 1.2**: `model.py` + `inspection.py` — a `RepoState` built from
  `git_sync` with NO network: branch, default branch, upstream, ahead/behind,
  dirty, and a `checkable` classification carrying the reason it is not.
  Named `inspection.py`, NOT `inspect.py` as drafted: that filename shadows a
  standard-library module much of the ecosystem imports. `RepoState` carries no
  enforcement policy — three surfaces consume it and only one blocks, so a
  `should_block` here would bake one consumer's configurable mode into the value
  the other two share. `git_sync._remotes` promoted to public `remotes()` so a
  caller can tell "no remote" from "no upstream": both are uncomparable, but
  their remedies differ (`git remote add` vs `git branch -u`). 69 tests, 100%
  coverage; the load-bearing one asserts inspection performs no network I/O.

- [x] ✅ **Task 1.3**: `refresh.py` — fetch, then `pull_ff_only` ONLY when clean
  and not ahead. The task said MIRROR `git_upstream_checker._auto_pull`, but it
  is a method welded to SessionStart's message formatting: it returns display
  lines, not a decision, so it cannot be reused. The decision is instead owned
  by `RepoState.safe_to_pull` and consumed here, so it exists once. What this
  module adds is the granularity a REPORT needs — dirty / ahead / diverged are
  one boolean to the decision but three different remedies to a reader, and
  telling someone with diverged history to commit their changes is useless
  advice. An un-checkable repo is not even fetched; a failed fetch or pull
  degrades to a report, because an exception at SessionStart would cost the
  session's whole startup context for something as ordinary as being offline.
  11 tests; package coverage 100%.

  **Known shallow duplication, recorded rather than left silent**: the two
  boolean conditions (dirty, ahead) now appear both here via `safe_to_pull` and
  inline in `_auto_pull`. Not unified because `_auto_pull` needs per-branch
  message text that a single boolean cannot carry, so a shared predicate would
  serve one caller and not the other. Worth revisiting only if a third caller
  appears.

- [x] ✅ **Task 1.4**: `cache.py` — JSON TTL cache under `daemon_untracked_dir()`.
  Missing/expired reads as NOT VERIFIED, never as fresh — and so does every other
  unusable shape: malformed JSON, a truncated write, an unknown `Checkability`, a
  non-numeric count, a schema-version mismatch, or a timestamp in the FUTURE
  (clock skew would otherwise make an entry immortal, since a naive `age > ttl`
  never fires on a negative age). One bad entry condemns the whole file, because
  returning the readable remainder would silently drop a repo, and a dropped repo
  is indistinguishable from one that was never governed. `None` (nothing known)
  and `{}` (swept, governs nothing) are deliberately different answers. 24 tests;
  package coverage 100%.

- [x] ✅ **Task 1.5**: `report.py` — one renderer used by every surface, so the
  three consumers cannot drift in what they say. Only repos NEEDING ATTENTION
  are listed: an all-clear is one line and a project governing nothing says
  nothing, which is what keeps the uncheckable canary off the top of every
  report. `NOT VERIFIED` is a distinct headline from `stale` — "nobody checked"
  and "this is out of date" demand different responses, and collapsing them
  would either cry wolf or give false comfort. `remediation_command` returns ONE
  command (a reader given three runs none), `--ff-only` never a plain pull, with
  wrong-branch outranking behind, and NOTHING at all for a dirty repo because
  every mechanical remedy there moves a tree holding uncommitted work.
  17 tests; package coverage 100%.

### Phase 2: Config

- [x] ✅ **Task 2.1**: Typed top-level `reference_repos` block following
  `PlanWorkflowQaJournalConfig`: `enabled`, `roots` (default
  `["untracked/repos"]`), `exclude`, `mode` (`block_once` default, `block`,
  `advise`, `off`), `auto_pull`, `cache_ttl_minutes`. `extra=forbid`, `Literal`
  for mode, `ge=1` on the TTL (a zero TTL expires instantly, so every read would
  be NOT VERIFIED).

  `enabled` ships **TRUE**, which is safe because discovery finds nothing when
  the root is absent — a project that never adopted the convention gets silence
  with zero config. Shipping it off would make every adopting project hunt for a
  switch before the protection did anything, which is the reported failure.

  `roots` reuse `normalise_repo_relative_path` (absolute and `..` rejected) plus
  one rule of their own: a root resolving to `.` is REJECTED, because it would
  sweep the whole project and govern the project's own repository — which
  Plans 00178/00179 already handle and this plan's Non-Goals exclude. 23 tests;
  validated against this project's live config.

### Phase 3: SessionStart sweep (does the network work)

- [x] ✅ **Task 3.1**: `session_start/reference_repo_sweep.py` — refresh every
  governed repo, auto-pull where safe, write the cache, report what it could not
  make fresh. Silent when everything is clean and current.
- [x] ✅ **Task 3.2**: Bound the report so a project with many repos cannot flood
  SessionStart (`_MAX_LISTED = 10`); the CLI stays unbounded, because a report
  you ASKED for should show everything.

### Phase 4: PreToolUse enforcement (cache only)

- [x] ✅ **Task 4.1**: `pre_tool_use/reference_repo_freshness.py` matching
  `Read`/`Grep`/`Glob` path fields and `Bash` command strings, the latter split
  per segment via `utils/shell_segmentation.py`.
- [x] ✅ **Task 4.2**: The four modes, `block_once` keyed per repo per session
  (the `lsp_enforcement` precedent, including Plan 00277's session scoping so
  one session cannot consume another's single warning). The session map is
  capped, because the daemon outlives any one session.
- [x] ✅ **Task 4.3**: The exemption set — every `git` segment passes through.
  The test builds the command from `remediation_command()` rather than a
  hand-written lookalike, so the exemption and the printed remedy cannot drift.

### Phase 5: CLI

- [x] ✅ **Task 5.1**: `bin/hooks-daemon reference-repos [--json] [--all]`
  calling the SAME checker. Exits non-zero when any governed repo is stale or
  off its default branch; an un-checkable repo alone never fails the command,
  so the canary cannot make CI permanently red. It WRITES the cache, because
  both other surfaces name it as the cure for `NOT VERIFIED` and a cure that
  records nothing cures nothing.

### Phase 6: Documentation

- [x] ✅ **Task 6.1**: `CLAUDE/ReferenceRepos.md` documents the convention, the
  three surfaces and the un-fetchable carve-out, with a reciprocal section in
  `CLIENT-MODE-TESTING.md`. Both state the rule the carve-out exists for: do
  NOT restore the canary's origin to clear a freshness report — that trades the
  safety property for a tidier report. `docs/guides/HANDLER_REFERENCE.md` gained
  the `reference_repo_freshness` section and summary row.

## Success Criteria

- [x] ✅ A stale governed repo cannot be read without the agent being told, in
  the configured mode.
- [x] ✅ The canary (`untracked/repos/php-qa-ci`, unreachable origin, dirty) is
  reported and NEVER blocked and NEVER pulled. Running the CLI against the REAL
  canary is what exposed the one defect worth having: its local refs say "not
  behind", so the report counted it as fresh and printed `all 1 up to date` for
  a repo whose fetch had failed with exit 128. `RepoState.verified` now
  separates "confirmed against its remote" from "checkable".
- [x] ✅ No PreToolUse code path performs network I/O — asserted by
  `test_the_handler_never_performs_network_io`, which monkeypatches
  `subprocess.run`/`Popen`/`check_output` to raise.
- [x] ✅ `default_branch` is resolved from `origin/HEAD`, so a repo whose default
  is not `main` is not falsely reported.
- [x] ✅ The remediation command printed by a deny message is itself allowed —
  the test builds it from `remediation_command()`, so the exemption and the
  printed remedy cannot drift apart.
- [x] ✅ One checker backs all three surfaces. Proven twice in the build: the
  false all-clear was fixed in `report.py` alone and corrected every surface,
  and `display_path` was promoted rather than copied into the handler.
- [x] ✅ Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/41-a-reference-clone-is-fresh-before-you-read-it.md`
  for the callout, and three `recommended: true` entries in
  `UNRELEASED/config-changes/v3.64.0.yaml` — the `reference_repos` block and
  both new handlers — so the upgrade advisory promotes them to existing installs
  rather than letting a whole subsystem ship dormant. No truth-change: this adds
  behaviour rather than falsifying a documented one.
- [x] ✅ Full QA passes and CI is green — 30/30 checks locally (23,076 tests,
  95.1% coverage) and CI green on Python 3.11, 3.12 and 3.13.

## Delivery & Milestones

- Filed from an owner report that agents reason from stale reference repos
  across projects. Dedupe scout checked 22 live plans: no overlap; 00178/00179
  are the portable prior art.
- Delivered across `9e399219`…`7a43abf6`: the checker package and config
  (Phases 1–2), the SessionStart sweep (`10520648`), the PreToolUse backstop
  (`97764ef9`), the CLI (`84524579`) and the docs (`7e7df501`).
- **Four defects, none of which a passing test suite would have surfaced.**
  Each was found by using the finished thing rather than by adding more tests
  of the kind already written, and each now has a regression test:
  - `984e2c92` — a failed fetch read as an all-clear. Pointed the CLI at this
    repo's real canary (unreachable origin, `git fetch` exits 128) and it
    printed `all 1 up to date`. `refresh_repo` already knew; all three
    consumers were dropping the outcome and keeping only `.state`.
  - `7e7df501` — the handler DENIED the commit shipping its own documentation.
    `_CHAIN_SEPARATORS` includes `\n`, so every line of a heredoc commit
    message parsed as a command reading a governed repo.
  - `f80e0657` — `git -C <repo> pull` was exempt but `cd <repo> && git pull`
    was not, blocking the obvious form of the remedy the deny message prints.
    Also the seventh registration gate, which CI caught and local runs did not:
    the default config template lives in `init_config.py` and is tested from
    `tests/daemon/`, not the `tests/unit/daemon/` subset being run.
  - `7a43abf6` — the Bash parser was blind to `cat 'path'`, `cat "path"` and
    `--file=path`. `split()` leaves quotes attached to the word, so the
    plainest quoted read matched no governed root at all.
- The last of those is the one worth remembering: a false POSITIVE is loud and
  gets fixed, while a false NEGATIVE is silent — and silence from a freshness
  gate reads as "that repo is fine", which is exactly the confident, wrong
  conclusion this plan exists to prevent.
