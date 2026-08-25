# Plan 00267 — Design

Durable design detail for Plan 00267. `PLAN.md` links here rather than
carrying this inline; see `CLAUDE/PlanWorkflow.md` for why a supporting doc is
the right home for it.

## 1. Where this came from

An earlier attempt exists on the unmerged remote branch
`plan/00190-worktree-create-seed-env-files` (which renumbered itself Plan
00191). It was never merged, conflicts with current `main` on
`worktree_create_handler.py`, and its config shape does not express the
per-entry symlink/copy choice this plan requires. It is **superseded**, not
resumed. Its lasting value is a hostile Opus review, distilled below.

Because it never shipped, no released config key is being changed and there is
no migration burden.

## 2. Findings inherited from the superseded branch's review

| Severity | Finding                                                                                                                                                                                      | Disposition here                                                                                                                                                                            |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HIGH     | An **absolute** symlink target dangles when the same tree is viewed at two prefixes (host `/home/...` vs container `/workspace`). Reproduced; a relative link resolved correctly under both. | Binding constraint: links are **always relative**, computed against `dest.parent`. Worse than the problem being solved — the agent gets a *broken* link rather than an absent file.         |
| MEDIUM   | Symlink write-through: a worktree agent truncating `.env.test.local` silently clobbers the main checkout's real file. Review suggested copy may be the safer default.                        | Resolved by design: mode is **per-entry and project-chosen**. Ceases to be a defect, becomes a documented tradeoff. Both modes' hazards stated in `get_claude_md()` and the example config. |
| MEDIUM   | `exists()` let a directory through, contradicting a stated Non-Goal.                                                                                                                         | Directories are now a **Goal**. Each mode's directory semantics are explicit and tested (§4).                                                                                               |
| MEDIUM   | A bare-string config value was iterated per-character into a silent no-op.                                                                                                                   | Shape validation is mandatory (§5). Verified still applicable: `registry.py:375-376` applies every option by blind `setattr` with no type check.                                            |
| MEDIUM   | `_repo_toplevel` duplicated `ProjectContext._get_git_toplevel`.                                                                                                                              | Retired: use the existing `GitRepo.resolve_for` (`utils/git_repo.py:152-164`). No third resolver.                                                                                           |
| LOW      | The safety guard bounds where the link is *written*, not where it *points*.                                                                                                                  | Matters more with directories in scope; add a `resolve()`-under-root containment check.                                                                                                     |
| LOW      | Nested entry `mkdir(parents=True)` untested.                                                                                                                                                 | Explicit test for a nested entry.                                                                                                                                                           |
| LOW      | `--show-toplevel` from a worktree cwd is not the main checkout.                                                                                                                              | Subsumed by Phase 1 (§3).                                                                                                                                                                   |

## 3. Phase 1 is a real bug, not scaffolding

`worktree_create_handler.py:56` takes `hook_input["cwd"]` verbatim and anchors
the worktree to it. It never asks git where the repo root is. So a session
whose cwd is a subdirectory already creates worktrees at
`<subdir>/.claude/worktrees/` today — before this plan adds anything.

Seeding cannot be built on that: it must resolve the **main checkout root** to
locate the git-ignored sources. `GitRepo.resolve_for(path)` already does this
(`utils/git_repo.py:152-164`) and returns `None` outside a repo.

Idempotency is a bare `path.exists()` (`:64`), blind to git's own worktree
registry — a stale directory that is not a registered worktree is accepted and
echoed back as valid. Seeding keys off the same fresh-creation signal, so this
is recorded as a known limitation rather than silently inherited.

## 4. Config shape

Project-owned, in `.claude/hooks-daemon.yaml`. The common case stays a flat
list; precision is available per entry.

```yaml
handlers:
  worktree_create:
    worktree_create:
      enabled: true
      priority: 50
      options:
        seed:
          default_mode: symlink        # symlink | copy
          entries:
            - .env.local               # uses default_mode
            - path: .secrets/
              mode: copy               # explicit override
```

Two parallel `symlink:`/`copy:` lists would read slightly cleaner but cannot
carry per-entry attributes later without a breaking reshape. `command_hints`
is the closest existing template — it already pairs a list of dicts with a
merge `mode` — so this follows an established idiom rather than inventing one.

### Directory semantics are explicit per mode

- `copy` on a directory — recursive copy. Isolated; may drift from the main
  checkout; costs disk.
- `symlink` on a directory — **one** link exposing the entire subtree, and
  every write inside it writes through to the main checkout.

Neither is safe-by-accident, so both are stated in the shipped guidance.

## 5. Validation: shape warns, content fails

The house contract is that option-shape validation is the handler's own job,
done defensively — `tdd_enforcement._parse_test_path_map` warns and skips and
never raises. Seeding needs a sharper split, because silently seeding nothing
is precisely the failure this feature exists to prevent:

| Error class                                               | Example                                                                                    | Behaviour                                                                         |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| **Shape** — malformed config                              | `seed: ".env.local"`, unknown `mode:`, unknown dict key                                    | `logger.warning` + skip that entry, per house idiom                               |
| **Content** — a well-formed entry that cannot be honoured | configured path absent at the repo root, unsafe (absolute / `..`), wrong type for its mode | **Fail fast**: raise before the worktree is created, so there is no partial state |

The distinction: a shape error means the project mis-typed its config and the
daemon cannot know what was intended; a content error means the project stated
a clear intention the daemon cannot fulfil, and proceeding would hand back a
worktree quietly missing the files the agent needs.

Options arrive **after** `__init__` via `setattr(instance, f"_{key}", value)`,
so the parsed form is built lazily into a memo field — never in the
constructor. `configure()` is not the mechanism: the two `configure()` methods
in the tree are vestigial and the registry never calls them.

## 6. Suggestions: one implementation, two entry points

**Do not rebuild config preservation.** `hooks-daemon.yaml` already receives a
three-way merge (old-default vs new-default vs user) on upgrade via
`preserve_config_for_upgrade` (`scripts/install/config_preserve.sh:344`),
wired at `scripts/upgrade_version.sh:774`, backed by the `config-merge` CLI
command (`daemon/cli.py:2530`). The seed config lives in that file and
inherits the merge for free.

What does **not** exist is a suggestion generator. `config-merge` reconciles a
daemon default against a user value, but the daemon's default here is
necessarily empty: no shipped default can know which git-ignored files a given
project happens to have. Suggestions must be derived by scanning *this* repo.

Nor does a version-independent "is my config good **now**" diff exist —
`check-config-migrations` is `--from`/`--to` gated and reads only the release
manifests; `/optimise` is an LLM skill with no code behind it.

So: **one** implementation, invoked from two places. Install/upgrade calls the
same command an operator can run ad hoc. Building separate install-time and
ad-hoc paths would duplicate the scan and let the two drift.

### Suggestion heuristics (draft)

Propose a path when it is git-ignored **and** matches a local-config shape
(`.env*`, `*.local`, `*.local.*`), at the repo root or one level down.
Exclude anything tracked, and build/vendor/cache directories.

### Reuse rather than reinvent

`_key_present_in_config` and `_get_value_at_key` (`install/config_migrations.py:448`,
`:470`) for dotted-path walking, the `UNSET` sentinel (`:68`) so a
present-but-`false` key stays distinguishable from an absent one,
`AdvisorySuggestion` (`:270`) and `format_advisory_for_llm` (`:610`) for
rendering.

### CLI contract

Templates: `check-config-migrations` for `--format {text,json}` and delegating
all logic to a `run_*` function in `install/config_cli.py`;
`reconcile-settings --check` for a dry-run that exits 1 on drift; `plan-qa`
for the tri-state exit code.

Exit codes: **0** clean, **1** drift found (CI-gateable), **2** operational
error. Reports by default; writes only on explicit request, because the
project owns its config.

## 7. Dogfooding note

This repo's own `.claude/hooks-daemon.yaml` has **no `worktree_create` block
at all**, while `.claude/hooks-daemon.yaml.example` ships one. That is a live
instance of exactly the drift the Phase 5 command is meant to surface, and it
makes a natural first real-world test of the reporter.

## 8. Two Phase 4 decisions that departed from the filed task list

Both are recorded here because the plan's tasks named something else, and a
silently-ticked task that did not do what it said is worse than an amended one.

### A mode mismatch is NOT drift

Task 4.3 listed "mode mismatch" as a third drift category. It was deliberately
not built, and a test pins that it is not reported.

The mode is *precisely* the choice this whole feature exists to give the
project. Flagging a configured `copy` against a suggested `symlink` would be
nagging about a decision already made deliberately — and the suggested mode is
only a default the scanner has no information to vary. A report that nags about
correct configuration is one people stop reading, which would then also cost
them the two findings that DO matter:

- **unconfigured** — a candidate present in the repo that the config does not
  mention. Informational; the project may have decided against it.
- **missing** — a configured entry whose source is gone. Urgent, because the
  Phase 3 executor fails fast on exactly this, so it will abort the *next*
  worktree creation.

### The dotted-path config helpers were not reused

The plan said to reuse `_key_present_in_config` / `_get_value_at_key` from
`install/config_migrations.py`. On reading them they answer a different
question: "is this dotted key set in the config mapping?" — a walk over config
structure. Phase 4 compares a LIST of seed entries against a SCAN of the
filesystem. There is no dotted path involved and no config mapping to walk.

Reusing them would have meant reshaping the data to fit a helper that was not
about this, which is a wrong abstraction rather than DRY. They stay the right
tool for Phase 5, where a config key genuinely does need looking up.

What Phase 4 does reuse is `run_git`, so **git** decides what is ignored.
Reimplementing `.gitignore` semantics would drift from the tool that actually
governs the answer.
