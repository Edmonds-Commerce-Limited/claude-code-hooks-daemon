# Plan 00558 design: branch WIP limit and hygiene

Phase 1 decisions (Tasks 1.1 and 1.2) for [PLAN.md](PLAN.md). Code citations come from [subagent-reports/261103-issue-152-code-facts.md](subagent-reports/261103-issue-152-code-facts.md) unless stated. Paths are relative to `src/claude_code_hooks_daemon/` unless they start with a top-level directory.

## 1. Config surface (Goal 1)

### Decision: one top-level `branches:` block

A new `BranchesConfig` model in `config/models.py`, added to `Config` beside `worktree:` and `reference_repos:`. It follows the `reference_repos:` precedent: one top-level block feeds the SessionStart sweep, the PreToolUse guards and the CLI, so they cannot disagree (`.claude/hooks-daemon.yaml`, the comment under `reference_repo_sweep`). `extra="forbid"` like `WorktreeConfig`.

```yaml
branches:
  default: auto              # auto = origin/HEAD, then local main, then master; or a name
  remote: origin             # the remote whose refs count and whose deletes are judged
  integration_lines: []      # globs, e.g. ["release/*", "epic/*"]: merge targets, never counted, never deleted remotely by an agent
  exempt: []                 # globs: never counted, never judged, never deleted by an agent (e.g. "users/*", "gh-pages")
  protected_names: [main, master, develop, trunk]   # was branch_safety.DEFAULT_PROTECTED_NAMES
  wip:
    cap: 10                  # owner, Q2: repository-wide
    mode: block              # block | warn | off
    count_remote: true       # remote-only branches count; identical tips count once
  duplicates:
    mode: warn               # warn | off (never blocks: a stem match is a heuristic)
  dormancy:
    preset: standard         # standard (7/14/30, owner Q3) | strict (3/3/7, owner); see section 4
    advisory_days: null      # null = the preset's value; a number overrides it
    noisy_days: null
    block_days: null
    mode: block              # block | warn | off ("warn" caps the third stage at noisy)
  stop_guard:
    mode: block              # block | warn | off
    unpushed_subagent: block # block | advise | off; this repository sets advise until Q5 (section 6)
    include_default: false   # judge the default branch and integration lines at stop too
  force_removal:
    mode: block              # block | off: lossless `worktree remove --force` and `branch -D` (section 11)
  evacuation:
    mode: block              # block | warn | off: the evacuate-then-destroy shape (section 13)
  cleanup_after_merge:
    mode: advise             # act | advise | off; this repository sets act
  sweep:
    budget_ms: 3000          # SessionStart wall-clock budget for the whole inventory
    behind_threshold: 50     # was branch_count_advisor.behind_main_threshold
```

Every key has a model default, so a project with no `branches:` block gets the whole feature at the defaults above.

### Migration of the existing decisions

| Today                                                                  | After                                                                                                                                                                               |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `utils/git_sync.py` `default_branch()` (origin/HEAD, main, master)     | Kept as the `auto` resolver. A new `resolve_default_branch(config, repo)` returns `branches.default` when it names a branch, else calls it. Every caller moves to the new function. |
| `delete-branch --protected-ref` default `main` (`daemon/cli.py:12807`) | argparse default becomes `None`; `None` resolves through `resolve_default_branch`. An explicit flag still wins.                                                                     |
| `worktree-reap --base-branch` default `main` (`daemon/cli.py:12426`)   | Same as above.                                                                                                                                                                      |
| `branch_safety.DEFAULT_PROTECTED_NAMES`                                | Becomes the model default of `branches.protected_names`; the default branch, every integration-line match and every exempt match are added at runtime.                              |
| `branch_count_advisor.options.max_open_branches`                       | `branches.wip.cap`. Read as a fallback for one release when `branches.wip.cap` is unset, with a deprecation line in the SessionStart summary.                                       |
| `branch_count_advisor.options.behind_main_threshold`                   | `branches.sweep.behind_threshold`, same fallback.                                                                                                                                   |
| `branch_count_advisor` handler                                         | Replaced by the branch sweep SessionStart handler (Task 2.3); the handler ID is kept as an alias so an existing `enabled: false` still silences the new line.                       |

Note the fallback is read in code, not by a config rewrite: handler options are a free `dict` applied by `setattr` (`handlers/registry.py:386-427`), so a stale option is silently ignored unless something reads it.

### What a migration needs in this project

Config changes are tracked per release in a manifest (schema: `CLAUDE/UPGRADES/config-changes/SCHEMA.md`; staging: `CLAUDE/UPGRADES/UNRELEASED/config-changes/`, today holding `v3.72.0.yaml`). The build adds to the staged manifest for the release it ships in:

- `added`: every `branches.*` key above, with `recommended: true` on `branches.integration_lines` and `branches.exempt` (a project with release branches or human-owned branches must declare them before the guards fire).
- `renamed`: `handlers.session_start.branch_count_advisor.options.max_open_branches` to `branches.wip.cap`, and `...behind_main_threshold` to `branches.sweep.behind_threshold`. `check-config-migrations` warns a client still holding the old key.
- `changed`: `branch_count_advisor` (replaced) with a `migration_note`.
- `breaking: false`, but a post-upgrade task in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` telling the upgrading agent to run `hooks-daemon branch-sweep` and declare integration lines and exempt patterns first (see section 10, adoption).

Also: the `daemon/init_config.py` template gains the block, and this repository's `.claude/hooks-daemon.yaml` sets `cleanup_after_merge.mode: act` and drops the two old options. `CLAUDE/Worktree.md:56` says "at most 3 open work branches"; that conflicts with the owner's cap of 10 and must be reconciled in Task 5.1 (unsettled: see the end).

### Rejected alternatives

- **Handler options on each handler.** That is the current state and the cause of the three-way drift. CLI verbs do not read handler options at all, and `shares_options_with` shares one handler's options, not a model across events and the CLI.
- **Extending `worktree:`.** Branches exist without worktrees (remote-only, `git switch -c` in the main checkout), and `worktree:` already means merge-approval policy.
- **Keys under `daemon:`.** `daemon:` configures the process and transport, not repository policy.
- **No default-branch key (always auto-detect).** Fails on clones without `origin/HEAD` and on repositories whose default is neither `main` nor `master`; that is half of why the CLI verbs default to `main`.

## 2. Inventory and classification

One module, `core/branch_inventory.py`, used by the sweep, the guards and the CLI. It returns one record per branch name: local tip, remote tip, worktree path, upstream, ahead, behind, lines, last-commit age, park marker, linked plan or issue, creator (section 6) and a state.

### States (first match wins)

1. **exempt**: matches `branches.exempt`. Shown only with `--all`.
2. **default / integration line**: the default branch, or matches `integration_lines`. Not work, not counted.
3. **merged into default**: tip is an ancestor of `refs/remotes/<remote>/<default>` or `refs/heads/<default>`.
4. **merged into an integration line**: tip is an ancestor of `refs/remotes/<remote>/<line>` for some line.
5. **patch-equivalent**: `git cherry <target> <tip>` prints no `+` line against the default or a line.
6. **same tip as another**: its tip equals another non-exempt branch's tip (grouping, not a separate state; shown on the record and used by the cap).
7. **parked**: tip carries the park trailer (section 5).
8. **dormant**: unmerged and last commit at or beyond the effective `advisory_days`; the stage (advisory, noisy, block) and the containment (section 4) are on the record.
9. **live work**: everything else.

States 3-5 are "done, not deleted". Only 7-9 are work.

### Git commands, and the cost at 1,000+ branches

Every command runs once per pass, not once per branch, except the bounded step 5.

1. `git for-each-ref --format='%(refname)%00%(objectname)%00%(committerdate:unix)%00%(upstream)%00%(ahead-behind:<default-ref>)%00%(trailers:key=Parked-Reason,valueonly,separator=%x1f)' refs/heads refs/remotes/<remote>`. One process; names, tips, ages, ahead/behind against the default and park markers for all refs. `%(ahead-behind:)` needs git 2.41 (this host has 2.47.3); on older git the inventory falls back to `rev-list --left-right --count` per branch inside the budget below.
2. `git worktree list --porcelain`: worktree path per branch, and dirty detection is deferred to the guards that need it.
3. `git for-each-ref --merged=<ref> --format='%(refname)' refs/heads refs/remotes/<remote>`: once for the default ref and once per existing integration-line ref. This is the bulk replacement for per-branch `merge-base --is-ancestor`.
4. Same-tip grouping is computed in Python from step 1.
5. `git cherry` and `git diff --shortstat <default>...<tip>` (lines) for unmerged branches only, each through `daemon/branch_safety.py`.

Cost: steps 1-4 are four to six git processes whatever the branch count; on 1,400 refs they read packed-refs and the commit-graph. Step 5 is per branch, so it is bounded twice: a cache in `untracked/branch-inventory/cache.json` keyed by `(tip sha, target sha)` (a result never changes for the same pair, so only branches whose tip or target moved are recomputed), and the `sweep.budget_ms` wall clock. Branches not reached inside the budget are reported as "not yet classified" rather than guessed, and the next pass continues from the cache. SessionStart runs the full pass; the guards read the cache plus steps 1 and 3 (section 3).

### Reuse of `daemon/branch_safety.py`

- The merged, patch-equivalent and content-preserved tiers (`classify_branch`, `:508`) are the proof for every delete: the cleanup (section 7), WorktreeRemove (section 8) and a new `branch-sweep --clean` all call `classify_branch` and `delete_branches` (`:655`), which already writes the recovery bundle and re-checks the tip before deleting.
- `_unique_commit_count` (`:418`) is the patch-equivalence step 5 uses.
- The inventory does NOT run the content-preserved tier: it walks every blob and is for the delete moment only.
- `classify_branch` gains a `targets` parameter (default ref plus integration-line refs) in place of the single `protected_ref`, so merged-into-a-line is a proof tier too.

Plan and issue links: a number token in the branch name, then `Addresses #N`/`Plan NNNNN` in the tip commit subject, resolved with the existing `find-plan` lookup.

## 3. Creation guard (Goals 3, 4)

One PreToolUse handler for the Bash and Agent routes and a check inside `worktree_create` for WorktreeCreate. All routes share one decision function: `creation_verdict(new_name | None) -> allow | warn | deny`.

### Routes and detection

| Route                                                                                                                       | Detected by                                                                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git switch -c/-C/--create <n>`, `git checkout -b/-B <n>`                                                                   | The git-argv parser `sensitive_content` already uses to extract branch names (`handlers/pre_tool_use/sensitive_content.py:1496`, `:1834`); moved to a shared utility so both use one parser.                                                                                                                               |
| `git branch <n> [start]`                                                                                                    | Same parser; only the create form (no `-d/-D/-m/-M/-c/-C/--list/-a/-r/--contains/...`, exactly one or two positionals).                                                                                                                                                                                                    |
| `git worktree add -b/-B <n> <path>`, and `git worktree add <path>` with no `-b`, no `--detach`, no existing branch argument | Same parser. The bare form creates a branch named after the path's basename (git's DWIM), so it is a creation unless that branch already exists or `--detach` is given.                                                                                                                                                    |
| Agent (`Task`) tool with `isolation: "worktree"`                                                                            | PreToolUse on the Agent tool, reading `tool_input.isolation`.                                                                                                                                                                                                                                                              |
| WorktreeCreate event                                                                                                        | Inside `worktree_create`'s `handle()`, before `_git_worktree_add`, only when the path does not exist (the idempotent re-fire for the same agent is never counted or denied). A refusal exits non-zero, which aborts the creation. It is the backstop for `claude --worktree` and any dispatch the Agent check did not see. |

A command the parser cannot read in full is allowed (this is a workflow guard, not a safety guard); the next sweep counts whatever it made. `git push <remote> HEAD:refs/heads/<new>`, `git fetch <remote> a:b` and `gh pr checkout` are not creation routes in v1: they are counted by the next inventory and listed as a follow-up.

### What is counted at decision time

Count = distinct tips among branches that are not the default, not an integration line and not exempt, over `refs/heads` and (when `count_remote`) `refs/remotes/<remote>`, excluding `<remote>/HEAD`. A local branch and its remote copy at the same tip count once; at different tips they count once too (same name). Merged-but-undeleted branches DO count: the cap is what makes deleting them worthwhile, and the denial names them first because they are the cheapest to clear. Parked branches count (parking is not a way round the cap).

Cost: one `for-each-ref` over the refs (step 1 of the inventory without `ahead-behind`), pattern matching in Python, no ancestry. That is one git process. The merged/dormant labels in the denial text come from the SessionStart cache; if the cache is missing the denial lists names only.

The request is denied when `count >= cap` (creating one more would exceed it). The denial lists the open branches: merged ones first with the `delete-branch` command, then dormant, then live, each with age and worktree path, capped at 20 lines plus a count.

### Duplicate-stem rule (Goal 4)

`stem(name)`: lower-case; strip a leading `worktree-`, `agent-`, or `<remote>/`; then strip trailing suffixes repeatedly while one matches `[-_](\d{1,2}|r\d+|v\d+|orig|old|new|retry\d*|again|redo|copy|bak|backup|[0-9a-f]{8})$`. The `[0-9a-f]{8}` arm removes `worktree_create`'s hash suffix. Numbers: every 2-5 digit token, plus `issue-N`/`gh-N`.

A new name warns when its stem equals an open branch's stem, or when it shares a number token with an open branch. The warning names the existing branch, its age and worktree, and says "continue there instead". It never denies, so a false match (two phases of one plan) costs one line.

## 4. Dormancy and containment (Goal 5)

Age = days since the tip's committer date (local tip, else remote tip). Only unmerged, unparked, non-exempt branches have a stage. The day counts below are the `standard` preset's; `strict` is defined after them.

### Containment of an idle branch

Every dormant branch is reported with where its commits live, because "idle" means two very different things:

| Containment            | Test                                                                                                                                                   | Reported as                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| in the default branch  | tip is an ancestor of `refs/remotes/<remote>/<default>`, or `git cherry` against it has no `+` line                                                    | idle and contained: cleanup candidate, with the `delete-branch` command |
| in another remote ref  | `git for-each-ref --contains <tip> refs/remotes/<remote>` names a ref other than the branch's own remote copy (an integration line, or another branch) | idle and contained in `<ref>`: cleanup candidate                        |
| on its own remote only | the only containing remote ref is `<remote>/<name>` itself                                                                                             | idle, pushed, unmerged: work to finish or park                          |
| nowhere                | no remote-tracking ref contains the tip                                                                                                                | LOST WORK RISK: loud, see below                                         |

The default-branch test is already in the inventory (steps 3 and 5 of section 2). The `--contains` test is one process per dormant branch, cached by `(tip sha, packed remote refs hash)` and inside the sweep budget; dormant branches are far fewer than branches.

"Contained nowhere" is loud from the first stage, whatever the preset: it is listed first, in capitals, in EVERY SessionStart (not only new sessions), in every creation-route decision and in the cap and dormancy denials, with the one command that secures it (`git push -u <remote> <name>`). It is still advisory: the work is not gone yet, and blocking would not bring it back.

### Stages

- **7 days, advisory:** one line per branch in the SessionStart summary on new sessions.
- **14 days, noisy advisory:** the same line in EVERY SessionStart (new, resume, compact), plus a context line appended to every allowed creation-route decision (section 3), plus a non-blocking context line at each main-thread Stop, at most once per hour per session (state in the session's spend-ledger state document). Every one of these is `additionalContext`; none denies.
- **30 days, block:** the creation routes of section 3 are denied while any branch is at this stage, with the same branch list and three ways out: finish and merge it, `hooks-daemon branch-park <name> --reason ...`, or delete it (`delete-branch`, which proves or asks a human). Nothing else is denied: commits, merges, pushes, deletes and every other tool stay open, so the way out is never blocked. `dormancy.mode: warn` stops at the noisy stage.

### Presets: `standard` and the stricter `strict` (owner ruling)

| Preset               | `advisory_days` | `noisy_days` | `block_days` |
| -------------------- | --------------- | ------------ | ------------ |
| `standard` (default) | 7               | 14           | 30           |
| `strict` (suggested) | 3               | 3            | 7            |

**Expression:** a `dormancy.preset` name plus per-stage keys that default to `null`. Effective value = the explicit key if set, else the preset's value. The model validates the effective values, not the raw keys: `advisory_days <= noisy_days < block_days`, all at least 1, so an override that inverts the stages under either preset is a config error at load, not a silent misbehaviour.

**`strict` has no separate quiet stage.** The owner named two stages, a warning at 3 days and a block at 7. With only four days between them, a once-per-new-session line is too easy to miss before the block lands, so the warning is the noisy form from day 3 (`noisy_days = advisory_days`).

**`strict` changes nothing else.** It does not tighten the WIP cap: the cap limits how MANY branches are open, dormancy limits how LONG one sits, and the owner set the cap (10, Q2) separately from this ruling. Tightening both under one name would make a project that wants faster turnover also accept fewer concurrent branches, which it did not ask for. The duplicate, Stop-guard and cleanup modes are not age rules and are untouched too. A project that wants a lower cap sets `wip.cap`.

**Rejected:**

- **Explicit values only, no name.** Nothing to suggest or check against: the optimiser could only say "consider 3 and 7", the docs would repeat the numbers, and a project copying them would drift from any later change to the preset.
- **A branch-wide `profile` that sets every `branches.*` key.** Couples the cap to the age rule (above), and a single profile name cannot express "strict dormancy, default cap".
- **A preset that forbids overrides.** A project that wants strict with a 10-day block would have to drop the preset and copy all three numbers.

**How it is suggested (never applied silently):**

1. The configuration optimiser (`bin/hooks-daemon optimise-checklist`, which already checks the top-level `plan_workflow` section beside the handlers) checks the `branches:` section too. On `preset: standard` with no stage overrides it prints an OPTIONAL line, "stricter dormancy available: `branches.dormancy.preset: strict` (warn at 3 days, block new work at 7)". It is not a WARN or FAIL, so a project on the defaults still scores full marks.
2. The configuration guide's `branches:` section (`docs/guides/CONFIGURATION.md`, the canonical home for config format; skills point there) documents both presets with the table above.
3. The config-changes manifest for the shipping release lists `branches.dormancy.preset` under `added` with a description naming `strict`, but NOT `recommended: true`: the default stays `standard`, so the upgrade advisory mentions it and does not promote it.

Not a surface: the SessionStart sweep line. It reports branches, not configuration, and a nag to change config on every session would be the noise the stages are meant to ration.

## 5. Parked marker (Q4)

### Decision: a trailer on an empty commit at the branch tip

`hooks-daemon branch-park <name> --reason "<text>"` writes an empty commit on the branch (same tree as the tip) with trailers `Parked-Reason: <text>` and `Parked-By: <git user>`, using `git commit-tree` plus `git update-ref <ref> <new> <old>` so no checkout is needed and a moved tip fails the update. It then pushes the branch with a plain fast-forward `git push <remote> <name>`.

- **Survives a fresh clone:** the marker is in the branch's own history, so wherever the branch is, the marker is. A branch that is not pushed would not survive a fresh clone anyway.
- **Read cheaply:** `%(trailers:key=Parked-Reason)` in the inventory's single `for-each-ref`; no extra process.
- **Cleared:** by the next commit on the branch (the tip no longer carries the trailer), which is exactly "work resumed". `branch-park --clear <name>` writes an empty commit with an `Unparked:` trailer for a human who wants to resume the clock without a code change.
- **Exempts:** the dormancy stages, including the 30-day block. It does NOT exempt the WIP cap (still work in progress) or the Stop guard's dirty check.
- **Park date:** the commit date of the park commit, shown as "waiting since".

Inventory rule: commits whose tree equals their parent's tree and that carry a `Parked-*`/`Unparked` trailer are not counted in "ahead" or "lines", and patch-equivalence ignores them (an empty commit has no patch, so `git cherry` against a target could otherwise report it as unique). A test pins both.

### Rejected alternatives

- **A tracked file on the default branch** (e.g. `CLAUDE/parked-branches.yaml`): parking needs a commit to the default branch, concurrent agents conflict on one file, and the entry outlives a deleted branch.
- **A git note on the tip:** `refs/notes/*` is neither pushed nor fetched by default, so it fails "survives a fresh clone" unless every clone is configured; and a note on a tip silently detaches when the tip moves.
- **The plan the branch belongs to:** not every branch has a plan, the plan link is a heuristic (section 2), and the plan lives on the default branch, with the same commit problem as a tracked file.
- **Local git config (`branch.<name>.parked`):** does not survive a clone.

## 6. Stop and SubagentStop guard (Goal 6)

### Recording the creator and every toucher

The guard covers EVERY branch the session or sub-agent touched, not only the one it made or the current one.

Decision: git config on the branch. Creation writes `branch.<name>.hooksDaemonCreator` (`<session_id>:<agent_id>`, agent empty for the main thread), `hooksDaemonCreated` (unix time) and `hooksDaemonRoute`. Every touch adds one value to the multi-valued `branch.<name>.hooksDaemonTouchedBy` (`git config --add`, same `<session>:<agent>` form) unless that value is already there.

- **Creation** is recorded by a PostToolUse handler after a successful creation route (section 3), confirming the ref exists first, from the payload's `session_id` and `agent_id` (PreToolUse and PostToolUse payloads carry `agent_id` inside a sub-agent; see `handlers/pre_tool_use/subagent_context_budget.py:308`).
- **A touch** is any of: a successful Bash `git commit`, `merge`, `rebase`, `cherry-pick`, `am`, `revert`, `reset`, `switch`/`checkout <branch>`, `pull` whose checkout (`cwd`) is on that branch afterwards; and the first `Write`/`Edit`/`NotebookEdit` per session per branch into a worktree on that branch. The branch is read with one `git -C <cwd> symbolic-ref -q HEAD`. The session's spend-ledger state remembers which branches it has already recorded, so a touch costs a git config write once per branch per session, not per tool call.
- WorktreeCreate writes the creator with an empty agent; the first tool call carrying an `agent_id` with `cwd` inside that worktree binds the agent (and counts as its first touch).
- Git keeps this right for free: `git branch -d/-D` removes the `branch.<name>` section, `git branch -m` renames it, and linked worktrees share the common config, so every worktree sees the same record. A branch nobody recorded (a human's, or one older than this feature) is never judged by the guard.

### What the guard checks

SubagentStop judges every branch whose `hooksDaemonTouchedBy` holds the stopping `<session>:<agent>`. Main-thread Stop judges every branch touched by the main thread of this session, plus, for the merged-but-not-deleted and unpushed checks, every branch its sub-agents touched (the coordinator owns what its sub-agents leave behind). The default branch and integration lines are excluded unless `stop_guard.include_default: true`: their push is governed by the release flow (R-RELEASE-MERGE-FREEZE), not by a session stop.

"Contained in a remote" = some `refs/remotes/<remote>/*` ref contains the tip (`for-each-ref --contains`, the existing R-GIT-BRANCH-FORCE-DELETE proof), after a `git fetch`-free read of the local tracking refs. A branch whose tip is contained in the LOCAL default branch is treated as handed over (the default branch is excluded above, so its own unpushed state is the release flow's), which is what lets a coordinator that merged a sub-agent's branch locally stop.

| Check                   | How                                                                                                                | Main thread | Sub-agent                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------- | ------------------------------------------------------------------------------ |
| Dirty worktree          | `git -C <worktree> status --porcelain` for the branch's worktree, untracked files included, ignored files excluded | block       | block                                                                          |
| Commits no remote holds | tip not contained in a remote (above) nor in the local default branch                                              | block       | `unpushed_subagent` (model default `block`; this repository `advise` until Q5) |
| Merged but not deleted  | merged state (section 2) and still present locally, on the remote, or as a worktree                                | block       | block (only if the sub-agent merged it)                                        |

The message names each branch, which check failed, and the exact commands to finish (`git add`/`commit`, `git push -u`, `git worktree remove`, `git branch -d`, the remote delete).

The model default refuses a sub-agent's stop while any branch it touched holds commits no remote contains, as #152's follow-up asks. This repository's sub-agents are told to commit in their worktree and NOT push; the coordinator merges locally. Under the model default every such sub-agent would be refused at stop. So this repository sets `unpushed_subagent: advise` until the owner rules (Q5): either sub-agents push their work branch (which removes the conflict and the advisory), or the setting stays. The coordinator's own Stop still refuses while any of its sub-agents' branches holds commits that are neither on a remote nor merged into the local default branch, so a sub-agent's work cannot be left behind by both of them.

### Interaction with the existing stop handlers

- Priority: after `usage_pause_stop_gate` (6), `cron_stop_enforcer` (7), the release-in-progress gate and `subagent_handoff_gate` (11), and before `auto_continue_stop` (15, 10 here). A usage-paused session must stop whatever its branches look like, so the guard returns allow when the usage-pause marker is live, and when `release-state.json` records a release (that gate owns the stop).
- Non-terminal, like `subagent_handoff_gate`, so the reason-prefix checks still run.
- Never strands an agent: after 3 blocked stops (the `subagent_handoff_gate` `MAX_STOP_BLOCKS` pattern) it allows and records the branch as "abandoned at stop" in the inventory cache, which the next SessionStart reports.

### The handoff path

When `subagent_context_budget` has recorded the hard band for this agent (`STATE_HARD_ENGAGED`), the guard keeps the dirty check and the unpushed check at its configured mode (committed and pushed work is exactly what a successor needs) and waives only merged-not-deleted, because the work continues in a fresh agent. The handoff message gets the branch name and tip sha appended so the successor knows where to continue.

A sub-agent that dies on a rate limit or an API error never fires SubagentStop (that is StopFailure, recorded by `stop_failure_recorder`). The guard cannot catch it; the SessionStart sweep reports the branch, the creator record names the session, and dormancy escalates it.

### Rejected alternatives

- **A session state file under `untracked/`** (the spend-ledger pattern): per checkout, so a branch made in a linked worktree is recorded under a different `untracked/` than the coordinator reads; and it goes stale when a branch is deleted or renamed outside the daemon.
- **The branch reflog** (`branch: Created from ...`): carries no session or agent identity, and is per clone and expirable.
- **Encoding the creator in the branch name:** names are chosen by agents and humans on the Bash routes; only WorktreeCreate controls its name.
- **Judging every branch at Stop:** would block a session on another session's or a human's branch, which is the false positive the plan must avoid.
- **Judging only the creator's branches, or only the current branch:** a session that commits on a branch another session made, then switches away, would leave it behind unjudged. "Touched" closes that.

## 7. Cleanup after merge (Goal 7) and integration lines in the delete guards (Goal 8)

### Cleanup after a merge

A PostToolUse handler on a successful Bash `git merge <branch>` run in a checkout whose current branch is the default or an integration line.

1. Prove: `classify_branch` against the checkout's HEAD; anything not merged or patch-equivalent is left alone.
2. `git worktree remove <path>` (never `--force`) when the branch is checked out in a clean linked worktree.
3. Local delete through `delete_branches` (recovery bundle, tip re-check; `-d` for merged).
4. The remote delete is NOT run inside the hook: it is a network call within the dispatch budget, and at this point the merge target is usually not pushed, so the proof would fail. The handler prints the exact `git push <remote> --delete <branch>` to run after the target is pushed; R-GIT-PUSH-DELETE-REMOTE then proves it, and the Stop guard's merged-but-not-deleted check makes sure it happens.

`mode: advise` prints steps 2-4 as commands instead of running them; `act` runs 2 and 3. Never a force, never the default branch, an integration line, an exempt branch, or a branch the proof did not cover. `gh pr merge` merges on the server; the cleanup there runs on the next `git fetch`/`git pull` that brings the merge in, through the same proof.

### Integration lines in R-GIT-PUSH-DELETE-REMOTE

In `_remote_delete_note` (`handlers/pre_tool_use/destructive_git.py:638-673`):

- Refuse outright any name that is the default, matches `integration_lines`, matches `exempt` or is in `protected_names`, whatever the proof.
- A branch is proven when its tracking tip is an ancestor of `refs/remotes/<remote>/<default>` OR of any `refs/remotes/<remote>/<line>`. Done with one `for-each-ref --merged` per target over the named refs, not one `merge-base` per branch.
- Live check (#153): one `git ls-remote <remote> refs/heads/a refs/heads/b ...` for all named branches, compared against the tracking tips in one pass. A 40-branch delete is then one network call.
- The handler gains its config from `branches:` (today its `__init__` takes no options, `:784`).

## 8. WorktreeRemove cleanup (Goal 9)

`handlers/worktree_remove/worktree_remove_handler.py` today runs `worktree remove --force` and `prune` and never deletes the branch (`:65-68`).

1. Before removing, read `git worktree list --porcelain` to map the payload path to its branch.
2. Remove the worktree, with `--force` only when the force-removal proof of section 11 passes (clean, and HEAD contained in another ref); otherwise without `--force`, so git itself refuses a dirty worktree and the handler reports it.
3. If the branch's creator record has route `worktree_create`, run `classify_branch` against the default ref and every integration-line ref; merged or patch-equivalent is deleted through `delete_branches`. Unproven is left in place and stays visible to the sweep and the WIP cap.

Counting `worktree_create` names needs no special case: the cap and the sweep count every non-default, non-exempt branch, so the `<slug>-<8hex>` names are counted like any other. The `worktree-reap` orphan pruning, limited to `agent-*` today (`core/worktree_reaping.py:558-560`), widens to branches with a `worktree_create` creator record.

## 9. Modes and rollout

| Part                                             | Default                                                                   | Turned off by                               |
| ------------------------------------------------ | ------------------------------------------------------------------------- | ------------------------------------------- |
| Sweep report (CLI, SessionStart line)            | on, advisory                                                              | the SessionStart handler's `enabled: false` |
| WIP cap                                          | block                                                                     | `branches.wip.mode: warn` or `off`          |
| Duplicate stem                                   | warn                                                                      | `branches.duplicates.mode: off`             |
| Dormancy advisory / noisy (7 / 14; strict 3 / 3) | advisory / noisy; "contained nowhere" loud at every stage                 | `branches.dormancy.mode: off`               |
| Dormancy block (30; strict 7)                    | block                                                                     | `branches.dormancy.mode: warn`              |
| Stop and SubagentStop guard                      | block (this repository: sub-agent unpushed advise until Q5)               | `branches.stop_guard.mode: warn` or `off`   |
| Lossless force removal                           | block                                                                     | `branches.force_removal.mode: off`          |
| Evacuate then destroy                            | block                                                                     | `branches.evacuation.mode: warn` or `off`   |
| Integration lines in the delete guard            | always (it only widens what is provable and refuses the lines themselves) | n/a                                         |
| Cleanup after merge                              | advise upstream, act here                                                 | `branches.cleanup_after_merge.mode: off`    |
| WorktreeRemove branch delete                     | on (proof required)                                                       | the same `cleanup_after_merge.mode: off`    |

### Build order

Value first. The #152 commenter triaged 154 leftover branches: 104 merged or contained in an integration branch and never deleted, 15 superseded, 14 finished but never merged, 11 sub-agents stopped midway, 3 waiting on a human, 7 other. Cleanup after merge alone would have removed about three quarters. So cleanup and the containment report come straight after the inventory, before any guard that denies; the guards then act on a repository that is already mostly clean, which also defuses the "blocked on upgrade" risk.

1. **Phase 2, inventory and report:** 2.0 `branches:` config, `resolve_default_branch`, the CLI-default and protected-name migrations; 2.1 inventory, including containment (section 4); 2.2 `branch-sweep` CLI; 2.3 SessionStart line.
2. **Phase 3, cleanup:** 3.1 cleanup after merge, integration lines in R-GIT-PUSH-DELETE-REMOTE with the batched `ls-remote` (#153, a dependency of the remote-delete step) and `branch-sweep --clean`; 3.2 WorktreeRemove branch delete (with the section 11 proof for its `--force`).
3. **Phase 4, enforcement:** 4.1 lossless force removal (section 11); 4.2 creation guard, creator and touch record, deny text (sections 3, 6, 12); 4.3 dormancy, presets and `branch-park`; 4.4 Stop and SubagentStop guard; 4.5 evacuate-then-destroy (section 13).
4. **Phase 5, ship** as before.

`delete-branch` and `branch-sweep --clean` use `delete_branches` (bundle, tip re-check) throughout.

## 10. Risks and how each is prevented

- **A release branch or other long-lived line is counted, flagged dormant or deleted.** It is declared in `integration_lines`: never counted, never dormant, never deleted remotely by an agent. The upgrade post-task asks for this before anything else; the sweep's first report lists long-lived branches that look like lines (names matching `release*`, `epic*`, `develop*`, `hotfix*`) as "declare these?".
- **A human's branch blocks agents (team repositories).** `exempt` globs; the guard judges creator-recorded branches only, so a human branch never blocks a Stop. It does count toward the cap if not exempt; the denial says how to exempt.
- **A project upgrades with hundreds of branches and is blocked at once.** The denial lists merged branches first, and `branch-sweep --clean` removes every provably merged one in one lossless command. The post-upgrade task tells the agent to run the sweep first. The cap and the 30-day block also have `warn` modes for a staged adoption.
- **A legitimately long task is blocked at 30 days.** `branch-park` exempts it with a recorded reason; a commit resets the clock.
- **The Stop guard traps an agent that must stop** (usage pause, release in progress, context budget). It yields to the usage-pause and release gates, waives merged-not-deleted on the handoff path, and gives way after 3 blocks.
- **The Stop guard forbids this repository's "do not push" sub-agent rule.** This repository sets `unpushed_subagent: advise` until Q5 (section 6); the coordinator's Stop still covers those branches.
- **A coordinator is refused because its merge into the default branch is not pushed yet.** Containment in the local default branch counts as handed over (section 6).
- **The force-removal guard blocks a cleanup a human wants.** It denies only when something would be lost; the message says to commit or push first, or to ask a human, who can run the command outside the agent.
- **The evacuation guard fires on a legitimate patch export** (a patch for review or an email). It needs BOTH halves on the same worktree or branch; an export alone never fires.
- **Slow git on a huge repository makes every creation command slow.** The guard runs one `for-each-ref` and reads the cache; a missing or stale cache never triggers a full inventory inside a PreToolUse dispatch. If the call times out, the guard allows with a "could not judge" advisory.
- **Concurrent `git config` writes collide** (several agents creating branches at once). Git locks `config`; the recorder retries a small number of times and, on failure, logs and allows: a missing creator record only means the Stop guard does not judge that branch.
- **A false duplicate match.** Warn only, never deny.
- **An empty park commit confuses the merged/ahead logic.** Section 5's inventory rule, pinned by a test.
- **`git worktree add <path>` DWIM misread.** Treated as a creation only when no existing branch matches the path basename and no `--detach`; tests cover each form.

## 11. Lossless force removal: `worktree remove --force` and `branch -D` (Goal 10)

A new rule in `destructive_git`, R-GIT-WORKTREE-REMOVE-FORCE, and a widened R-GIT-BRANCH-FORCE-DELETE, both on one proof, `contained_elsewhere(repo, tip, excluded_refs)`: some ref outside `excluded_refs` contains `tip` (`git for-each-ref --contains <tip> refs/heads refs/remotes refs/tags`). `excluded_refs` is the ref being deleted plus every other ref the same command deletes, so a command that deletes a branch and its only holder together is judged as a whole.

- **`git worktree remove --force|-f [-f] <path>`** is denied when either holds: (a) `git -C <path> status --porcelain` lists anything (modified, staged or untracked; ignored files excluded, matching what git's own non-force remove refuses on), or (b) the worktree's HEAD is not contained in any ref other than the worktree's HEAD itself (for a worktree on a branch, the branch survives removal and contains its commits, so (b) bites on a detached HEAD or when the same command also deletes the branch). Without `--force`, git refuses a dirty worktree on its own, so only the forced form is judged.
- **`git branch -D` / `-d --force` / `update-ref -d refs/heads/<n>`**: allowed when `contained_elsewhere` passes. Today only a remote-tracking ref counts (`destructive_git.py:442-467`); any other local branch or tag now counts too, because each later deletion of that holder is judged the same way, so no step loses a commit.
- One `for-each-ref --contains` and one `status --porcelain` per named target; a command naming many targets batches the `--contains` over all tips.
- The deny states what would be lost (paths, commit count) and the principle text of section 12.

## 12. What every deny says (Goal 11)

One constant, `BRANCH_LIMIT_PRINCIPLE`, appended to the WIP-cap, dormancy, Stop-guard, force-removal and evacuation denials, and to the handler guidance in Task 5.1, so the wording cannot drift:

> The limit exists so work FINISHES, never so it disappears. Finish a branch (merge it), park it with a reason, or delete it only when the guard proves nothing is lost. Work that serves another lane goes on that lane's branch, not a new one. A patch or copy saved under an ignored or untracked directory is lost work, not compliance. If the limit seems to force a choice between losing work and exceeding it, stop and ask a human.

Each deny then lists its specific way out (the branches to finish, the commands). A unit test asserts the constant appears in every deny these handlers produce.

## 13. Evacuate then destroy (Goal 12)

The shape: save the work as a patch somewhere git does not track, then destroy the worktree or branch that held it. Section 11 already denies the destroy step whenever something would be lost; this rule names the shape so the deny teaches the right move instead of inviting a cleverer workaround.

- **Evacuation:** `git diff`, `git diff --cached`, `git format-patch` (to stdout or `-o <dir>`), `git stash show -p` or `git show <commit>` whose output lands, by redirect, `tee` or `-o`, in a path that is ignored (`git check-ignore -q`) or untracked (`git ls-files --error-unmatch` fails), or outside the repository.
- **Destruction:** `git worktree remove` (forced or not), `git branch -d/-D`, `update-ref -d`, `rm -r` of a worktree directory (discarding checkouts are already denied by R-GIT-CHECKOUT-DISCARD); aimed at the same worktree (by path or `-C`/`cwd`) or branch the evacuation read.
- **Same command: decided, built.** Both halves in one Bash command (`&&`, `;`, `|`, subshells) are found by the existing parser that already splits compound commands for the pipe and destructive-git rules. Deny.
- **Same turn: decided feasible, built second.** A PostToolUse handler records each evacuation (worktree, branch, target path) in the session's spend-ledger state, keyed by turn: the main thread's turn counter advances at UserPromptSubmit, and a sub-agent's "turn" is its lifetime (`agent_id`). A destruction in the same turn that matches a record is denied the same way. A record expires with its turn, so a patch exported for review yesterday never blocks today's cleanup.
- The deny names the right move: commit the work on the branch of the lane it serves (or push it), or ask a human; plus section 12's text.
- `evacuation.mode: warn` turns it into an advisory.

## Unsettled (for the owner)

- `CLAUDE/Worktree.md:56` says at most 3 open work branches; the owner's cap is 10 repository-wide. Is 3 a separate, stricter local working rule, or should Worktree.md change to 10?
- Q5 also: the model default refuses a sub-agent stop with commits no remote holds; this repository's sub-agents are told not to push. Should they push their work branch (then the default applies here), or does this repository keep `unpushed_subagent: advise` (section 6)?
- Q1 (the #152 "preserve" branches) is still open; nothing here depends on it.
