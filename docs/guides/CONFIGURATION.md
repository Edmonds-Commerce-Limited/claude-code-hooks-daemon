# Configuration Guide

This guide covers everything you need to know about configuring the Claude Code Hooks Daemon.

---

## Config File Location

The daemon looks for its configuration file at:

```
<project-root>/.claude/hooks-daemon.yaml
```

It also accepts `.yml` as an extension. The daemon finds the config by searching upward from the current directory for a `.claude/` folder containing `hooks-daemon.yaml`.

You can also use JSON format (`hooks-daemon.json`), but YAML is recommended for readability.

### Generating a Config File

If you do not have a config file yet, use the `init-config` command:

```bash
# Generate a full config with all handlers listed
.claude/hooks-daemon/bin/hooks-daemon init-config --mode full > .claude/hooks-daemon.yaml

# Generate a minimal config with just the structure
.claude/hooks-daemon/bin/hooks-daemon init-config --mode minimal > .claude/hooks-daemon.yaml
```

---

## Config Structure Overview

A complete config file has three top-level sections:

```yaml
version: "2.0"          # Config format version

daemon:                  # Daemon process settings
  # ...

handlers:                # Handler configuration by event type
  pre_tool_use:          # Handlers that run before tool execution
    # ...
  post_tool_use:         # Handlers that run after tool execution
    # ...
  session_start:         # Handlers that run at session start
    # ...
  # ... more event types

plugins:                 # Daemon plugins: custom handler modules (not Claude Code plugins)
  # ...

projects:                # Monorepo sub-tree declarations (optional)
  # ...
```

---

## Daemon Settings

The `daemon` section controls the background process itself.

```yaml
daemon:
  idle_timeout_seconds: 600    # Shut down after N seconds of inactivity (default: 600)
  log_level: INFO              # Logging verbosity: DEBUG, INFO, WARNING, ERROR
  strict_mode: false           # Fail-fast on all errors (useful for development)

  # Input validation (recommended)
  input_validation:
    enabled: true              # Validate incoming hook event data
    strict_mode: false         # true = fail-closed (deny on bad data), false = fail-open (allow)
    log_validation_errors: true
```

### Setting Details

| Setting                        | Default | Description                                                                                                                                                                                                                 |
| ------------------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `idle_timeout_seconds`         | `600`   | Daemon shuts down after this many seconds without a hook call. It restarts automatically on the next call (lazy startup).                                                                                                   |
| `log_level`                    | `INFO`  | Controls how much detail appears in daemon logs. Use `DEBUG` when troubleshooting handler behaviour.                                                                                                                        |
| `strict_mode`                  | `false` | When `true`, a handler that raises denies the call instead of being skipped. A `SAFETY`+`BLOCKING` handler denies on its own raise either way — see [Strict Mode](#strict-mode) below. Recommended for development/testing. |
| `self_install_mode`            | `false` | Used when the daemon runs from the project root instead of `.claude/hooks-daemon/`. Only needed for daemon development.                                                                                                     |
| `input_validation.enabled`     | `true`  | Validates hook event data before processing. Catches malformed events early.                                                                                                                                                |
| `input_validation.strict_mode` | `false` | When `true`, invalid events are denied. When `false`, invalid events are allowed through with a warning logged.                                                                                                             |
| `chain.deadline_seconds`       | `20`    | Per-event chain deadline in seconds, well under the client's own 30s socket timeout — see [Chain Deadline](#chain-deadline) below.                                                                                          |
| `chain.max_inflight`           | `16`    | How many handler chains run at once, across every session the daemon serves — see [Dispatch Capacity](#dispatch-capacity) below.                                                                                            |
| `chain.slot_wait_seconds`      | `2`     | Seconds a chain waits for a free slot before it is refused, spent from its own deadline — see [Dispatch Capacity](#dispatch-capacity) below.                                                                                |

---

## ccy Container Workflow

The `ccy` section configures the ccy (claude-yolo) container workflow. It
currently holds a single flag that governs auto-deploy **and arming** of the
standalone PTY supervisor (`claude-supervise.py`) — the process that watches the
daemon-written context sidecar and, when context goes RED while the session is
idle, injects a real `/compact` and auto-resumes with `continue`.

```yaml
ccy:
  deploy_supervisor: true   # true | false | (absent)
```

| Value      | Behaviour                                                                                                                                                                                       |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `true`     | On install/upgrade, deploy/refresh `claude-supervise.py` into the project's `.claude/ccy/` **and arm it** — but only when a `.claude/ccy/` directory already exists (i.e. it is a ccy project). |
| `false`    | Never deploy or arm (explicit opt-out).                                                                                                                                                         |
| _(absent)_ | Deploy **and arm** anyway when a `.claude/ccy/` directory exists, and recommend setting the flag `true`. Distinguished from an explicit `false`.                                                |

Projects that do not use the ccy container workflow (no `.claude/ccy/`
directory) are unaffected — the deploy is a no-op.

**Arming** means writing an armed `CCY_CLAUDE_WRAPPER` export into
`.claude/ccy/ccy.env`. The ccy launcher sources that file and prepends
`$CCY_CLAUDE_WRAPPER` to `claude`, so without it the deployed script is inert (it
never wraps the session). The generated line is self-locating — it resolves the
supervisor path from `ccy.env`'s own directory at source time, so one line works
for both the podman `/workspace` mount and an arbitrary LXC project dir. Arming
is idempotent and respects the user: an existing `CCY_CLAUDE_WRAPPER` in
`ccy.env` (set OR commented out to disable) is left untouched.

---

## Worktree Workflow

The top-level `worktree:` block holds policy for the git-worktree parent/child
workflow (Plan 00367).

```yaml
worktree:
  merge_to_main_requires_human_approval: false   # default false
```

| Value   | Behaviour                                                                                                                         |
| ------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `false` | (default) The parent-to-main merge happens once verification passes; no daemon gate.                                              |
| `true`  | A `git merge`/`gh pr merge` run in the MAIN checkout on its default branch is denied until a human runs `approve-merge <branch>`. |

A merge run inside a linked worktree (child into parent) is never gated
either way. Handler details, the deny reason and the human's approval route
are in [`merge_to_main_approval`](HANDLER_REFERENCE.md#merge_to_main_approval).

---

## Hosts (per-host settings)

The top-level `hosts:` block holds settings that differ by machine or session
role (Plan 00479). Each key is a label. An entry applies to a session when its
`pattern` (a case-sensitive `fnmatch` glob: `*`, `?`, `[...]`) matches the
session's effective hostname; with no `pattern`, the label itself is the exact
hostname. The effective hostname is the first non-empty of
`HOOKS_DAEMON_HOSTNAME`, `CCY_HOST_HOSTNAME`, then the system hostname.

```yaml
hosts:
  sdlc-runner:                  # a label
    pattern: "cchd-sdlc-*"      # optional glob; omitted = the label is the hostname
    usage_ceiling:
      max_used_percent: 80      # 0 < x <= 100, applies to both windows
      five_hour: 85             # optional override for the 5-hour window
      seven_day: 70             # optional override for the 7-day window
  dev-laptop:
    usage_ceiling:
      max_used_percent: 95
```

| Key                                   | Meaning                                                                           |
| ------------------------------------- | --------------------------------------------------------------------------------- |
| `pattern`                             | Optional glob against the effective hostname. A blank value is an error.          |
| `usage_ceiling.max_used_percent`      | Used-percent limit for both windows, greater than 0 and at most 100.              |
| `usage_ceiling.five_hour`/`seven_day` | Per-window limit that overrides `max_used_percent`. At least one limit is needed. |

When several entries match, the lowest limit wins per window. No matching
entry, or no ceiling on the matches, means no ceiling. Unknown keys are
rejected at config load. The resolver is
`utils.host_usage_ceiling.resolve_host_usage_ceiling`.

### What a ceiling does: the usage pause

A session whose host has a ceiling PAUSES when a live usage window reaches it;
it does not end. Three handlers (`usage_pause_gate`, `usage_pause_tool_gate`,
`usage_pause_stop_gate`) run it, inert unless a ceiling is set:

- The prompt that trips the ceiling carries a directive to delete every cron
  and create ONE recurring resume cron on the schedule `*/10 * * * *`, then
  stop. The schedule names no clock time, so no host time zone can misplace it;
  a tick before the resume time (the window's reset plus two minutes) costs the
  model no turn: it reads the daemon's usage snapshot, lifts the pause when a
  fresh reading (seen within 15 minutes) is under the ceiling (for example after
  the session moved to another account), re-bases the recorded resume time when
  a fresh reading is still over on a different window, and is otherwise dropped.
  This trusts the same host-wide snapshot a held prompt already does. The directive also winds up subagents: start no new ones, let
  running ones finish.
- While paused, other prompts are dropped before the model, every main-thread
  tool but `CronList`/`CronDelete`/`CronCreate`/`ToolSearch`/`SendMessage`/
  `TaskStop` is denied (a new subagent included, and the turn is halted), and a
  stop is accepted only once exactly the resume cron remains. A session that
  never submits a prompt is paused by its next tool call (refused without a
  halt, carrying the directive) or its next Stop. A subagent over the ceiling
  starts the pause, but a subagent's own calls are never denied: running ones
  finish.
- The owner is never locked out: each held prompt re-checks the ceiling, so a
  pause that no longer applies lifts. `bin/hooks-daemon usage-pause clear`, run
  in a terminal (whether a `!`-prefixed command passes through the hooks is
  unverified), removes the pause and records an override until the latest reset
  among the windows over the ceiling (at most 8 days): no pause is started for
  that session meanwhile, even with usage still over. While it is in force and
  a window is over its ceiling, every prompt carries a line naming the window,
  its percentage, the ceiling and the override's end time (UTC), so the session
  knows the ceiling is suppressed. An override marker that cannot be read still
  counts, with an unknown end, and is reported on every prompt.
  `usage-pause status` shows the state. A pause record is honoured for at most
  8 days.
- The resume cron's prompt starts `[tick:usage-resume]`. When it fires, usage is
  re-read: under the ceiling the pause lifts and the declared crons are
  re-created; still over it, the next resume cron is scheduled.
- The status line's usage segment (`usage_indicator`) shows the ceiling a host
  runs under as `⛔ 80%` (`⛔ 5h 80% 7d 95%` when the windows differ), and
  `⏸ usage HH:MM` (local resume time) while paused, and `override until HH:MM`
  (local time) while the owner's override is in force: red when a window is over
  its ceiling, yellow otherwise. An override marker that cannot be read shows
  `override (end unknown)` in red.

No ceiling, an unknown hostname or missing, stale or API-key-only usage data
never pauses a session; a debug log line says which.
The pause record is `<session>.usage-paused` in the context sidecar directory,
which the ccy supervisor also reads
([CcySupervisor.md](../../CLAUDE/development/CcySupervisor.md)).

---

## Projects (monorepo boundaries)

The top-level `projects:` block declares a monorepo's sub-trees so
workspace-aware handlers (e.g. `npm_command`, `lint_on_edit`,
`tdd_enforcement`) resolve config, linters and test dirs against the right
project instead of the repo root. Full design and rationale:
[../../CLAUDE/Code/WorkspaceResolution.md](../../CLAUDE/Code/WorkspaceResolution.md)
— this section covers only the config shape.

**Omitted entirely (the default)**: one project at the repo root,
byte-identical to today's behaviour.

```yaml
projects:
  - name: web
    root: "{REPO_ROOT}/web"
  - name: service
    root: service
  - name: infra
    root: infra
    kind: ansible          # no manifest at this root — declaration is the only way
    bin_dirs: [.venv/bin]
  - name: legacy-app
    root: apps/legacy
    layout:                # this project's OWN directory-layout truths (Plan 00300)
      source_dirs: ["backend/src"]
      test_dirs: ["backend/tests"]
```

Each project's `layout:` (same shape as the top-level `layout:` block)
is its OWN — a project without one uses built-in defaults for its own root,
never the root project's declared lists. The top-level `layout:` is the ROOT
project's layout only, not a global fallback. `ProjectRegistry.layout_for(path)`
resolves the owning project's layout for a file; a handler needing the union
across every project uses `ProjectRegistry.iter_layouts()`/`all_source_dirs()`
— never a hand-rolled loop.

| Field      | Required | Description                                                                                                                                                          |
| ---------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`     | yes      | Unique identifier within the block; used in advisory/diagnostic output.                                                                                              |
| `root`     | yes      | Repository-relative project directory. `.` declares the repo root itself.                                                                                            |
| `kind`     | no       | Ecosystem name. Unset infers from the manifest found at `root`.                                                                                                      |
| `bin_dirs` | no       | Root-relative tool bin dirs. Unset infers from `kind`; `[]` explicitly declares none.                                                                                |
| `layout`   | no       | This project's own `layout:` block (source/test/config/vendor dirs). Unset uses built-in defaults for this project's root — never the root project's declared lists. |

**Path notation: `{REPO_ROOT}`.** Documented paths use the literal token
`{REPO_ROOT}` for "the repository root" (e.g. `{REPO_ROOT}/web`) — optional
sugar accepted anywhere a repository-relative path is, and on a handful of
exempt fields (a daemon plugin path, `project_handlers.path`) the portable
alternative to a genuine absolute path. Full semantics:
[../../CLAUDE/Code/WorkspaceResolution.md](../../CLAUDE/Code/WorkspaceResolution.md).

**Every path is repository-root-relative — zero absolute paths.** `root` and
each `bin_dirs` entry reject absolute paths, `~`, and `..` escapes. `name`
values must be unique within the block; duplicates are rejected at load. A
declared project need not contain a manifest — `infra/` above is exactly the
case declaration exists for.

The `monorepo_detector` session-start handler is advisory only: when it sees
an unconfigured monorepo shape, it prints a paste-ready `projects:` block, but
never changes enforcement itself.

`markdown_organization`'s `monorepo_subproject_patterns` option was **removed**
(Plan 00300 hard cutover) — `projects:` is the only sub-project mechanism.
Loading a config that still sets it is a hard startup error whose message
prints the equivalent `projects:` block; there is no fallback, and staying on
an older daemon version is the backward-compat path.

**The zero-absolute-paths rule extends beyond `projects:` (Plan 00303).**
`plan_workflow.directory`/`workflow_docs` and `documentation.trees.agent`/
`human` follow the same repository-relative-or-reject rule as `root` above.
A handful of advisory/best-effort options (`sensitive_content`'s
`secret_word_list_path`, `daemon.payload_capture.dir`,
`model_fallback_detector`'s `snapshot_dir`) degrade instead of rejecting: an
absolute value is logged and the built-in default is used. Daemon plugin paths,
`project_handlers.path`, `daemon.socket_path`/`pid_file_path`, and
`transport.relay_binary` are documented exemptions — see
`CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.58.0.yaml` for the full list and
rationale. On the two exemptions that resolve against the project (daemon
plugin paths, `project_handlers.path`), a leading `{REPO_ROOT}` token is the
portable alternative to a genuine absolute path — see the path notation
paragraph above.

---

## Branches (`branches:`)

The top-level `branches:` block holds the branch hygiene settings: the three branch pools (open work under `wip.cap`, default 10; parked; merged), duplicate warnings, cleanup after merge and dormancy. Dormancy ages an unmerged, unparked branch from its tip's commit date and applies three stages:

- advisory: one line per branch in the SessionStart summary of a new session.
- noisy: the same line in every SessionStart, plus a context line on every allowed branch creation.
- block: creating a branch is denied (rule `R-BRANCH-DORMANT`) until each blocking branch is merged, parked or deleted. Nothing else is denied.

`branches.dormancy.preset` picks the stage days; `advisory_days`, `noisy_days` and `block_days` override one stage each (the effective values must satisfy `advisory <= noisy < block`). `mode: warn` stops at the noisy stage and `off` disables the stages.

| Preset               | `advisory_days` | `noisy_days` | `block_days` |
| -------------------- | --------------- | ------------ | ------------ |
| `standard` (default) | 7               | 14           | 30           |
| `strict`             | 3               | 3            | 7            |

`strict` changes only the dormancy days; it does not tighten `wip.cap`. `bin/hooks-daemon optimise-checklist` prints a non-scoring OPTIONAL line suggesting `strict` to a project on `standard` with no overrides.

```yaml
branches:
  dormancy:
    preset: strict
    block_days: 10 # optional per-stage override
```

### Parking a branch

`bin/hooks-daemon branch-park <name> --reason "<text>"` writes an empty commit with `Parked-Reason` and `Parked-By` trailers at the branch tip (no checkout), then pushes the branch with a plain fast-forward `git push`. A parked branch is exempt from the dormancy stages and moves from the open-work count to the parked pool (below). A failed push is reported with the command to retry; the local park stands. A later commit on the branch ends the park, and `bin/hooks-daemon branch-park --clear <name>` writes an `Unparked` commit to restart the clock without a code change. Re-parking an already-parked branch needs a new reason: the same reason exits 2.

### Branch pools: open, parked, merged

Every work branch is in exactly one pool, and each pool has a cap, a maximum age and a mode:

| Pool      | Members                                             | Cap                             | Stale when                                                                           | Deny rule              |
| --------- | --------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------------------ | ---------------------- |
| open work | unmerged, unparked branches                         | `wip.cap` (10)                  | the dormancy block stage                                                             | `R-BRANCH-WIP-CAP`     |
| parked    | branches whose tip carries `Parked-Reason`          | `parked.cap` (null = `wip.cap`) | the park is older than `parked.max_age_days` (null = `block_days`)                   | `R-BRANCH-PARKED-POOL` |
| merged    | merged or patch-equivalent branches not yet deleted | `merged.cap` (null = `wip.cap`) | unkept: at once (unless a worktree holds it); kept: older than `merged.max_age_days` | `R-BRANCH-MERGED-POOL` |

In `block` mode, creating a branch is denied while a pool is at its cap or holds a stale member, and the deny names that pool's own way out: merge, re-park with a new reason, or delete a parked branch; `branch-sweep --clean` (plus `--remote` when a remote copy exists) for merged ones. `warn` turns the deny into a context line and `off` stops counting the pool. `preset: strict` shortens every default age together, and leaves the caps alone.

`bin/hooks-daemon branch-keep <name> --reason "<text>"` keeps a merged branch (a release you still need, say) for `merged.max_age_days`. The keep is a git note on the branch tip under `refs/notes/hooks-daemon/keep`, pushed to `branches.remote`, so every clone sees it; a new commit on the branch moves its tip and ends the keep. A kept branch is skipped by `branch-sweep --clean` and reported; a lapsed keep is cleaned like an unkept branch. A same-reason re-keep exits 2, and a branch that is not merged exits 1 (park it instead).

`branches.bot_owned` (default `["dependabot/*"]`) names branches a bot manages. They are in no pool: never counted, never judged by the creation guard and never deleted by `branch-sweep --clean`. `branch-sweep` lists them in their own `bot-owned` section.

`branches.home` (default empty) names the branches a main checkout lives on. The daemon writes and auto-commits the CLAUDE.md block only while HEAD is attached to a home branch; empty means the repository's default branch, and a configured list replaces that default (set it when a checkout sits on an environment, release or production branch). On any other branch, or a detached HEAD, it writes nothing and logs why. `regenerate-docs` still writes the block on request but commits only on a home branch. `branches.home_commit` (default `true`) set to `false` keeps the block written on a home branch but never commits it. Use it when the home branch only accepts changes by pull request: the block rides your next pull request.

```yaml
branches:
  parked:
    cap: 5
    max_age_days: 60
  merged:
    mode: warn
  bot_owned: ["dependabot/*", "renovate/*"]
```

### Other branch settings

| Key                            | Values (default first)        | Effect                                                                                                                                                     |
| ------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `wip.cap` / `wip.mode`         | `10` / `block`, `warn`, `off` | Open work branches allowed before a creation is denied (`R-BRANCH-WIP-CAP`); `count_remote` also counts remote ones                                        |
| `duplicates.mode`              | `warn`, `off`                 | Warn when a new branch name is close to an existing one; never denies                                                                                      |
| `stop_guard.mode`              | `block`, `warn`, `off`        | Stop and SubagentStop refuse while a touched branch is dirty, holds commits no remote has, or is merged but undeleted                                      |
| `stop_guard.unpushed_subagent` | `block`, `advise`, `off`      | How the unpushed-commits finding is treated at a SubagentStop (this repository sets `advise`)                                                              |
| `force_removal.mode`           | `block`, `off`                | `git worktree remove --force` and `git branch -D` are denied when they would lose work                                                                     |
| `evacuation.mode`              | `block`, `warn`, `off`        | Copying work to an untracked file and destroying its worktree or branch is denied, in one command or one turn                                              |
| `cleanup_after_merge.mode`     | `advise`, `act`, `off`        | After a merge lands: advise the delete command, or delete the branch when it is proven merged; `regenerable` lists the ignored globs that may be discarded |
| `sweep.budget_ms`              | `3000` / integer milliseconds | Wall-clock budget for the per-branch inventory steps; `behind_threshold` (default 50) is the commits-behind-default count that earns a warning             |

Every deny from these guards ends with the same principle text: the limit exists so work finishes, never so it disappears. `bin/hooks-daemon branch-sweep` reports every branch by state; `branch-sweep --clean` deletes the provably merged ones and writes a recovery bundle first. The same two commands are the `branch-sweep` (report) and `branch-sweep-clean` (held) steps of `/hooks-daemon housekeeping`.

**What "contained" means.** The session-start summary and the branch creation guard read only the remote-tracking refs the clone has fetched, so their CONTAINED NOWHERE text says exactly that: no fetched remote-tracking ref of the remote holds the commits. A remote may still hold the branch outside `refs/heads` (an archive namespace the default refspec never fetches). `bin/hooks-daemon branch-sweep` and `bin/hooks-daemon delete-branch` make one bounded `git ls-remote` (only when a branch would otherwise be unproven) and accept a remote ref at, or descending from, the branch tip as proof, naming the ref they relied on. A failed listing falls back to the fetched-ref answer and reports that the remote could not be checked.

Recovery bundles accumulate: `delete-branch` writes a new file per call under `untracked/deleted-branches/` and `branch-sweep --clean` one per run under `untracked/branch-cleanup/`, each named by UTC time plus a random suffix, so a later deletion never overwrites an earlier one. Both print one `git fetch <bundle> refs/heads/<name>:refs/heads/<name>` restore line per deleted branch. `delete-branch --bundle PATH` refuses a PATH that already exists. When git refuses every delete, the run says nothing was deleted and keeps no bundle, because nothing needs recovering.

`branch-sweep --clean --remote` also deletes merged branches on `branches.remote`, so one command clears local and remote alike. It deletes only what the remote-delete guard would let an agent delete: the branch's tip is an ancestor of the default branch (or, for an ordinary branch, of an integration line), and `git ls-remote` confirms the remote's live tip is that same commit. A patch-equivalent remote branch is listed as skipped, not deleted. It first fetches the keep notes from the remote, so a keep made in another clone protects the branch; if that fetch fails, the remote half is refused and only local branches are cleaned. Each delete carries a lease on its proven tip, and the remote tips go into the same recovery bundle with a restore line that fetches the ref back and pushes it. `--dry-run` works with `--remote`. The flag contacts the remote; plain `--clean` never does.

`branch-sweep --clean` leaves a live agent's worktree and branch alone, locally and on the remote, and prints `Skipped <name>: ...` with the reason. Three signals mark one: a `running` work-queue record naming the branch or worktree, a worktree under `.claude/worktrees/` (Claude Code creates and cleans those itself), and a worktree git reports `locked`. `worktree-reap` honours the work-queue and lock signals too.

## Handler Configuration

Handlers are grouped by the event type they respond to. Each handler has at minimum an `enabled` flag and a `priority` number.

### Basic Handler Syntax

```yaml
handlers:
  pre_tool_use:
    # Compact syntax (most common)
    destructive_git: {enabled: true, priority: 10}

    # Expanded syntax (when you need options)
    british_english:
      enabled: true
      priority: 60
      mode: warn              # Handler-specific option
      excluded_dirs:          # Handler-specific option
        - node_modules/
        - dist/
```

### Handler Properties

| Property   | Required | Description                                         |
| ---------- | -------- | --------------------------------------------------- |
| `enabled`  | Yes      | `true` to activate the handler, `false` to skip it  |
| `priority` | Yes      | Execution order -- lower numbers run first          |
| `options`  | No       | Handler-specific configuration (varies per handler) |

### Enabling and Disabling Handlers

To enable a handler, set `enabled: true`. To disable it, set `enabled: false`. Changes take effect after a daemon restart:

```bash
.claude/hooks-daemon/bin/hooks-daemon restart
```

---

## Event Types

The daemon supports these hook event types:

| Event Type        | Config Key           | When It Fires                                           |
| ----------------- | -------------------- | ------------------------------------------------------- |
| PreToolUse        | `pre_tool_use`       | Before Claude executes a tool (Bash, Write, Read, etc.) |
| PostToolUse       | `post_tool_use`      | After a tool finishes executing                         |
| SessionStart      | `session_start`      | When a new Claude Code session begins                   |
| SessionEnd        | `session_end`        | When a session ends                                     |
| PreCompact        | `pre_compact`        | Before conversation history is compacted                |
| SubagentStop      | `subagent_stop`      | When a subagent completes its task                      |
| UserPromptSubmit  | `user_prompt_submit` | When the user submits a prompt                          |
| PermissionRequest | `permission_request` | When a tool requests permission                         |
| Notification      | `notification`       | When a notification event occurs                        |
| Stop              | `stop`               | When Claude is about to stop responding                 |
| StatusLine        | `status_line`        | When generating the status bar display                  |

---

## Priority System

Priorities determine the order handlers execute within an event type. **Lower numbers run first.**

### Priority Ranges

The canonical statement of the bands is the agent-tree
[Priority Guide](../../CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide); the band
boundaries derive from `PriorityRange` in
`src/claude_code_hooks_daemon/constants/priority.py`. Quoted here for
convenience:

<!-- ssot-quote: CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide -->

| Priority Range | Type         | Examples                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0-9            | Test         | Test fixtures (`Priority.TEST_HANDLER`), plus the Stop-family handlers that MUST run before a terminal Stop catch-all: `branch_stop_guard`, `idle_workable_issue_stop_gate`, `goal_loop_detector`, `cron_stop_enforcer`, `cron_subagent_stop_enforcer`, `teammate_reap_advisor`, `background_task_recorder`, `subagent_report_path_verifier`, `subagent_cache_aggregator`, and the usage pause gates `usage_pause_gate`, `usage_pause_tool_gate`, `usage_pause_stop_gate` |
| 10-20          | Safety       | `destructive_git`, `sed_blocker`, `secret_file_guard`                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 25-35          | Code Quality | `qa_suppression`, `lint_on_edit`, `comment_changelog`                                                                                                                                                                                                                                                                                                                                                                                                                     |
| 36-55          | Workflow     | `lsp_enforcement`, `plan_qa_edit`, `npm_command`                                                                                                                                                                                                                                                                                                                                                                                                                          |
| 56-73          | Advisory     | `british_english`, `flaggable_work_advisor`, `model_fallback_detector`                                                                                                                                                                                                                                                                                                                                                                                                    |
| 100+           | Logging      | Reserved for logging/metrics/cleanup; no built-in handlers ship here                                                                                                                                                                                                                                                                                                                                                                                                      |

<!-- /ssot-quote -->

Per-handler numbers are deliberately not listed: your project's config can
override any handler's priority, and the shipped defaults live in
`constants/priority.py`.

### Why Priority Matters

When multiple handlers match the same event, they run in priority order. A safety handler at priority 10 runs before a workflow handler at priority 45.

**Terminal handlers** stop the chain when they match. If a terminal handler at priority 10 denies a command, handlers at priority 20 and above never see the event.

**Non-terminal handlers** add context but allow the chain to continue. Multiple non-terminal handlers can each contribute context to the same event.

### Customizing Priorities

You can override the default priority of any handler:

```yaml
handlers:
  pre_tool_use:
    # Move sed_blocker to run before destructive_git
    sed_blocker: {enabled: true, priority: 8}
    destructive_git: {enabled: true, priority: 10}
```

---

## Handler Options

Some handlers accept additional configuration through the `options` field or handler-specific keys.

### Handler-Specific Settings

```yaml
handlers:
  pre_tool_use:
    # British English handler with custom settings
    british_english:
      enabled: true
      priority: 60
      mode: warn             # "warn" (advisory) or "block" (deny)
      excluded_dirs:
        - node_modules/
        - dist/
        - vendor/

    # Absolute path handler with blocked prefixes
    absolute_path:
      enabled: true
      priority: 12
      blocked_prefixes:
        - /container-mount/
        - /tmp/claude-code/

    # Upstream check with an explicit pull policy
    git_upstream_checker:
      enabled: true
      priority: 56
      options:
        mode: warn                     # warn | agent-pull | auto-pull
```

For the complete per-handler options reference (all handlers, all options, defaults, and examples), see **[Handler Reference](HANDLER_REFERENCE.md)**.

### Listing every exception

`hooks-daemon exceptions [--json]` lists what exempts something from a guard, with the reason each
carries: `exclude_paths` and `extra_whitelist` entries, handlers set to `enabled: false` or
`mode: warn`, in-file `MUST_EXCEED_*_BECAUSE` hatches, and the QA exception files. An exception
written as `{pattern, reason}` shows its reason; a plain string shows `(no reason)`.

### Parent-Child Handler Relationships

Some handlers share configuration through a parent-child relationship. The child handler inherits `options` from the parent, avoiding duplication:

```yaml
handlers:
  pre_tool_use:
    # Parent handler defines shared options
    markdown_organization:
      enabled: true
      priority: 42
      options:
        track_plans_in_project: "CLAUDE/Plan"
        plan_workflow_docs: "CLAUDE/PlanWorkflow.md"

    # Child handler inherits options from markdown_organization
    plan_number_helper:
      enabled: true
      priority: 30
      # No need to repeat track_plans_in_project here
```

---

## Tag-Based Handler Selection

Instead of enabling handlers one by one, you can use tags to enable or disable groups of handlers.

### Using enable_tags

Only run handlers that have at least one of the specified tags:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, safety, tdd]
    # Only handlers tagged with python, safety, or tdd will run
```

### Using disable_tags

Exclude handlers with specific tags:

```yaml
handlers:
  pre_tool_use:
    disable_tags: [ec-specific, project-specific]
    # Handlers with these tags will not run
```

### Combining Tags with Individual Settings

Individual `enabled: false` settings override tag filtering:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python]

    # This handler matches the python tag but is explicitly disabled
    qa_suppression:
      enabled: false
```

### Available Tags

**Language tags:** `python`, `php`, `typescript`, `javascript`, `go`

**Function tags:** `safety`, `tdd`, `qa-enforcement`, `qa-suppression-prevention`, `workflow`, `advisory`, `validation`, `logging`, `cleanup`

**Tool tags:** `git`, `npm`, `bash`

**Specificity tags:** `ec-specific`, `project-specific`

---

## Daemon Plugins (handler modules)

Daemon plugins let you add custom handlers specific to your project. A daemon
plugin is a Python handler module the daemon loads itself. It is **not** a
Claude Code plugin, which Claude Code installs from a marketplace and runs
without the daemon: see [Claude Code plugins](CLAUDE_CODE_PLUGINS.md).

### Daemon Plugin Configuration

```yaml
plugins:
  paths: []      # Additional Python module search paths (optional)
  plugins:
    # Load a specific handler from a file
    - path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
      event_type: pre_tool_use  # REQUIRED: which event this plugin handles
      handlers: ["MyHandler"]   # Specific class names to load
      enabled: true

    # Load all handlers from a directory
    - path: ".claude/hooks/handlers/post_tool_use/"
      event_type: post_tool_use
      handlers: null            # null = load all Handler subclasses found
      enabled: true
```

`event_type` is **required** and has no default — a plugin entry without it is
rejected at config load. It must name an event the daemon actually dispatches;
a catalogued-but-unwired event is refused, and the error lists the ones you can
use.

### Writing a Custom Handler

Create a Python file in `.claude/hooks/handlers/<event_type>/`:

```python
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(PreToolUseHandlerBase):
    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,
            terminal=True   # True = stop chain on match, False = continue
        )

    def matches(self, hook_input: dict) -> bool:
        # REQUIRED: Filter by event type
        if hook_input.get("hook_event_name") != "PreToolUse":
            return False
        # Your matching logic
        command = hook_input.get("tool_input", {}).get("command", "")
        return "dangerous_pattern" in command

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult(
            decision=Decision.DENY,
            reason="This operation is not allowed."
        )
```

**Important:** The directory path (e.g., `pre_tool_use/`) is a convention only. Your handler's `matches()` method must check `hook_event_name` to filter by event type.

**Pick the base class that matches your event.** Every event has one in `claude_code_hooks_daemon.core.handler_bases`, named after it — `PreToolUseHandlerBase`, `SessionStartHandlerBase`, `PostToolUseHandlerBase`, and so on. Each narrows `handle()` to the decisions its event can actually deliver: `GatingResult` (allow/deny/ask) for `PreToolUse` and `PermissionRequest`, `BlockingResult` (allow/deny) for `PostToolUse`, `Stop` and `SubagentStop`, and `AdvisoryResult` (allow only) for every other event.

This matters because an event that cannot express a refusal drops one silently — a `DENY` returned from a `SessionStart` handler produces a valid response with the refusal removed, so the handler believes it blocked and nothing blocked. Subclassing `Handler` directly still works and is not deprecated, but the event base lets a type-checker catch that mistake before it ships.

### Daemon Plugin Search Paths

Use `paths` to add directories to the Python module search path, allowing your handlers to import shared utilities:

```yaml
plugins:
  paths:
    - ".claude/hooks/lib"   # Add this to sys.path
  plugins:
    - path: ".claude/hooks/handlers/"
      event_type: pre_tool_use
      handlers: null
      enabled: true
```

---

## Environment Variables

These environment variables affect daemon behaviour. They are typically set in `.claude/hooks-daemon.env`, which is sourced before the daemon starts.

| Variable                   | Description                                                                                                                             |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `HOOKS_DAEMON_ROOT_DIR`    | Root directory of the daemon installation. Default: `$PROJECT_PATH/.claude/hooks-daemon`. Set to `$PROJECT_PATH` for self-install mode. |
| `CLAUDE_HOOKS_SOCKET_PATH` | Override the Unix socket path. Takes precedence over hostname-based paths.                                                              |
| `CLAUDE_HOOKS_PID_PATH`    | Override the PID file path.                                                                                                             |
| `CLAUDE_HOOKS_LOG_PATH`    | Override the log file path.                                                                                                             |
| `HOSTNAME`                 | Used for multi-environment isolation. Each unique hostname gets its own socket, PID, and log files (e.g., `daemon-laptop.sock`).        |
| `DAEMON_BRANCH`            | Git branch or tag to install (used by the installer only). Default: `main`.                                                             |
| `FORCE`                    | Set to `true` to force reinstall over an existing installation.                                                                         |

### Hostname-Based Isolation

When running in multiple environments (containers, CI, different machines), each unique `HOSTNAME` gets isolated runtime files:

```
# With HOSTNAME=laptop
.claude/hooks-daemon/untracked/daemon-laptop.sock
.claude/hooks-daemon/untracked/daemon-laptop.pid
.claude/hooks-daemon/untracked/daemon-laptop.log

# With HOSTNAME=ci-runner-01
.claude/hooks-daemon/untracked/daemon-ci-runner-01.sock
```

This prevents conflicts when multiple daemon instances run for the same project across different machines.

---

## Minimal vs Full Config

### Minimal Config

Use a minimal config when you want a clean starting point and plan to enable handlers selectively:

```yaml
version: "1.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use: {}
  post_tool_use: {}
  session_start: {}

plugins:
  paths: []
  plugins: []
```

Generate one with:

```bash
.claude/hooks-daemon/bin/hooks-daemon init-config --mode minimal
```

### Full Config

Use a full config to see every available handler with descriptions and recommended settings. This is the default output of the installer and lists all event types and handlers:

```bash
.claude/hooks-daemon/bin/hooks-daemon init-config --mode full
```

### Recommended Starting Config

For most projects, the example config (`.claude/hooks-daemon.yaml.example` in the daemon repository) provides a good starting point. It enables all safety handlers and disables optional workflow/quality handlers with clear comments explaining each one.

---

## Config Validation

### Validating Your Config

The daemon validates its config on startup. If there are issues, you will see error messages in the logs:

```bash
# Check logs for config errors
.claude/hooks-daemon/bin/hooks-daemon logs | grep -i "config\|error\|warning"
```

### Common Config Errors

**Unknown handler name:**

```yaml
handlers:
  pre_tool_use:
    destrutive_git: {enabled: true}  # Typo -- should be "destructive_git"
```

The daemon will log a warning about an unrecognized handler. Check spelling against the example config.

**Wrong event type:**

```yaml
handlers:
  pre_tool_use:
    lint_on_edit: {enabled: true}  # Wrong -- this is a post_tool_use handler
```

Handlers only work under their correct event type. See the example config for the right placement.

**Invalid YAML syntax:**

```yaml
handlers:
  pre_tool_use:
    destructive_git: {enabled true}  # Missing colon after "enabled"
```

The daemon will fail to start with a YAML parse error. Use a YAML linter to check syntax.

**Missing version field:**

```yaml
# version: "2.0"  -- missing!
daemon:
  log_level: INFO
```

Always include the `version` field at the top of your config.

### Strict Mode

With `daemon.strict_mode: true`, a handler that raises an exception denies the call instead of being skipped. This is useful during development to catch handler bugs immediately. In production, leave it `false` so the daemon continues running even if a single handler has a problem — except a handler tagged both `SAFETY` and `BLOCKING`, which always denies on its own raise, whatever this setting says: a safety guard that crashed has not judged the call. See [CLAUDE/Security/FailOpenBoundaries.md](../../CLAUDE/Security/FailOpenBoundaries.md) for the full inventory of what still fails open.

### Chain Deadline

The hook client gives the daemon a socket timeout (30s) and treats an expired one as an ALLOW for the whole PreToolUse chain — so a single slow handler used to bypass every guard behind it, not just itself. `daemon.chain.deadline_seconds` (default `20`, comfortably under that 30s budget) bounds how long the daemon itself spends on one event: once it is exceeded, a handler tagged both `SAFETY` and `BLOCKING` that has not run yet is denied ("not judged in time"), and any other not-yet-run handler is skipped with a note. Setting it to `null` disables enforcement — not recommended, since that reopens the original bypass.

The two worktree events are the exception: `WorktreeCreate` and `WorktreeRemove` run git rather than judge a call, and their git budget (30s per call) is longer than this deadline, so they get their own: a 55s chain deadline for create and 65s for remove, and a client wait of 60s and 70s. `deadline_seconds` can raise those but never lower them below that floor, and `null` still disables enforcement. Every other event uses `deadline_seconds` unchanged.

### Dispatch Capacity

One daemon serves every session in the project, and it runs at most `daemon.chain.max_inflight` handler chains at once (default `16`). A chain that finds every slot taken waits up to `daemon.chain.slot_wait_seconds` (default `2`, `0` refuses at once) for one, and that wait is spent from its own deadline. If no slot frees, the chain is refused as "dispatch pool saturated", which is handled like "not judged in time": a call whose chain holds a `SAFETY`+`BLOCKING` handler is denied, Stop and SubagentStop included.

The daemon's exact recovery command (`hooks-daemon restart`, `status`, `logs`, `stop`, `start` or `repair` by this install's launcher, nothing else on the line) needs no slot of that pool, so a full pool can always be restarted from inside a session. Those commands share a separate pool of 2 instead, so repeated `status` calls cannot pile up behind a stuck handler; when it is full too, the hook client still lets the exact recovery command through. Saturation lasting 10 seconds or more is logged as a WARNING with its duration and the number of calls refused, at most every 30 seconds. It counts as over only after 5 seconds with no refusal. Seeing it regularly means the host runs more concurrent sessions than `max_inflight` allows.

```yaml
daemon:
  chain:
    max_inflight: 32
    slot_wait_seconds: 2.0
```

---

## Applying Config Changes

**Handler changes** (enabling, disabling, priority adjustments) require a daemon restart:

```bash
.claude/hooks-daemon/bin/hooks-daemon restart
```

**Claude Code settings** (`.claude/settings.json`) require a full Claude Code session restart. This file is managed by the installer and rarely needs manual changes.

---

## Example Configurations

### Python Project

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    # Safety
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    curl_pipe_shell: {enabled: true, priority: 15}
    pip_break_system: {enabled: true, priority: 20}
    sudo_pip: {enabled: true, priority: 20}

    # Code quality (qa_suppression covers every supported language)
    qa_suppression: {enabled: true, priority: 30}
    tdd_enforcement: {enabled: true, priority: 15}

    # Workflow
    web_search_year: {enabled: true, priority: 55}

  post_tool_use:
    lint_on_edit: {enabled: true, priority: 25}

  session_start:
    git_upstream_checker: {enabled: true, priority: 56}

plugins:
  paths: []
  plugins: []
```

### JavaScript/TypeScript Project

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    # Safety
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    lock_file_edit_blocker: {enabled: true, priority: 20}

    # Code quality (qa_suppression covers eslint-disable / @ts-ignore too)
    qa_suppression: {enabled: true, priority: 30}

    # Workflow
    global_npm_advisor: {enabled: true, priority: 40}
    npm_command: {enabled: true, priority: 50}
    web_search_year: {enabled: true, priority: 55}

  post_tool_use:
    lint_on_edit: {enabled: true, priority: 25}
    validate_eslint_on_write: {enabled: true, priority: 20}

  session_start:
    git_upstream_checker: {enabled: true, priority: 56}

plugins:
  paths: []
  plugins: []
```

### Safety-Only (Minimal Intervention)

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 10}
    absolute_path: {enabled: true, priority: 12}
    curl_pipe_shell: {enabled: true, priority: 15}
    dangerous_permissions: {enabled: true, priority: 18}
    lock_file_edit_blocker: {enabled: true, priority: 20}
    pip_break_system: {enabled: true, priority: 20}
    sudo_pip: {enabled: true, priority: 20}

  post_tool_use: {}
  session_start: {}

plugins:
  paths: []
  plugins: []
```
