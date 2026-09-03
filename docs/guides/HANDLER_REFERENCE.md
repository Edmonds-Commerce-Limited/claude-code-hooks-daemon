# Handler Reference

Per-handler options, values and defaults for the Claude Code Hooks Daemon. Each handler intercepts specific Claude Code events and either blocks dangerous operations or provides advisory context.

**Scope**: this page documents every **PreToolUse blocking** handler plus the handlers that carry configurable options — not every handler that ships. For the full inventory of handlers active in *your* project, generate it from live config:

```bash
.claude/hooks-daemon/bin/hooks-daemon generate-docs   # writes .claude/HOOKS-DAEMON.md
```

**About the Priority column**: the number shown for each handler is its **shipped default**, taken from `src/claude_code_hooks_daemon/constants/priority.py` — the single source of truth for handler priorities. A project's `.claude/hooks-daemon.yaml` may set a different `priority:` for any handler; that override is local to the project and is never a reason to edit this page. `scripts/qa/check_handler_reference.py` fails the QA suite if any number here drifts from the code, or if a section names a handler that does not exist.

## How Handlers Work

Handlers run in **priority order** (lower number runs first). Each handler has two key methods:

- **matches()** -- Decides whether this handler should activate for the current event
- **handle()** -- Executes the handler logic and returns a decision (allow, deny, or context)

Handlers are either **blocking** (terminal) or **advisory** (non-terminal):

- **Blocking handlers** stop the dispatch chain and return immediately (deny or allow)
- **Advisory handlers** add context or guidance but allow the chain to continue

---

## Path Exclusion (`exclude_paths`)

Every path-based blocking handler accepts gitignore-style glob patterns that exempt matching files. This is the supported way for a project (e.g. a QA/linting library) to keep intentionally-"bad" fixture code out of the blockers instead of disabling a whole handler.

The handlers that honour it are deliberately not enumerated here — this list said "three" while six consumed the option, and it has since grown again. To see the current set, grep the source for `handler_excludes_path`, the single shared decision they all call.

Globs support `*` (within a segment), `?` (single char), and `**` (zero-or-more path segments). Examples: `**/fixtures/**`, `samples/**/*.py`, `tests/assets/**`.

**Two levels, combined as a union:**

- **Project-wide** -- `daemon.exclude_paths` (a top-level `daemon:` key). Inherited by every handler that supports exclusion.
- **Per-handler** -- `handlers.<event>.<handler>.options.exclude_paths`. Applies to that handler only.

A file is exempt if it matches the union of the project-wide list, the handler's own list, and the handler's built-in defaults. The three sources are additive; none overrides another.

**Two of them are not content scanners**, and for those an exclusion means something different — worth understanding before reaching for it:

- `tdd_enforcement` (PreToolUse, blocking) -- excluding a path turns the TDD gate OFF for it. Where the tests merely live somewhere the resolver cannot infer, prefer that handler's `test_path_map` option, which keeps the gate ON and declares the directory instead.
- `lint_on_edit` (PostToolUse, blocking) -- excluding a path stops it being linted at all. Narrower alternatives exist: `languages` restricts which languages are checked, and `command_overrides` can reduce a language to its cheap syntax check only (`extended: null`).

**Built-in defaults** (always skipped, no config needed):

- `error_hiding_blocker`: the canonical vendored/build-directory core (`node_modules`, `vendor`, `third_party`, `dist`, `build`, `.build`, `target`, `.next`, `.venv`, `venv`, `coverage`) plus `tests/fixtures/`, `tests/assets/`, `__fixtures__/` (added in v3.35.0 for parity with its siblings; core swap in Plan 00288).
- `security_antipattern`: `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, docs, and rule-definition dirs (via `should_skip()`).
- `qa_suppression`: per-language vendor / build / `node_modules` directories.

```yaml
daemon:
  exclude_paths:
    - "**/fixtures/**"
    - "samples/**"

handlers:
  pre_tool_use:
    error_hiding_blocker:
      options:
        exclude_paths:
          - "generated/**"
```

---

## Directory Layout (`layout:`)

A cross-cutting top-level block (Plan 00288) for project directory-role
truths that had no config home before it: which directories are source,
which are test, which hold config, and which extras extend the built-in
vendored/build set. Consumed via `ProjectLayout`, a runtime facade
(`core/project_layout.py`) that composes this block WITH the truths that
already had a home — `documentation.trees.agent`/`.human` (see
`british_english` above) and `plan_workflow.directory` (see the plan-QA
handlers) — into one API, so no handler re-declares a directory-name
truth independently.

Handlers currently reading the facade: `markdown_organization`,
`goal_injection`, `recovery_cron_advisor`, `plan_workflow`,
`plan_number_helper`, `worktree_file_copy`, `same_commit_plan_doc`,
`path_existence`, `tdd_enforcement`, `british_english`, and the shipped
`.claude/rules/` directory-role pointer files (deployed by
`install/directory_role_rules.py`; see `CLAUDE/DirectoryRoles.md` for
what belongs in each role).

Every list defaults to empty — **byte-identical behaviour to a project
with no `layout:` block at all**. `source_dirs`/`test_dirs`/`config_dirs`
extend (or, under `mode: replace`, stand alone in place of) the built-in
per-language/cross-language conventions; `vendor_dirs` extends the
canonical vendored/build-directory core (11 names: `node_modules`,
`vendor`, `third_party`, `dist`, `build`, `.build`, `target`, `.next`,
`.venv`, `venv`, `coverage`).

```yaml
layout:
  source_dirs: ["backend/src"] # extra source dirs (no cross-language built-in exists yet)
  test_dirs: ["e2e"] # extends the built-in tests/, test/, __tests__/, spec/
  config_dirs: [] # extends the built-in "config"
  vendor_dirs: ["proto-gen"] # extends the canonical vendored/build core
  mode: additive # additive (default): extend built-ins; replace: a SET list stands alone
```

**`mode: replace` only replaces a list the project actually SET** — an
unset list still falls back to its built-in even under `replace` (the
same scoping `secret_file_guard` already uses for its own `mode`).

---

## Transport (`daemon.transport:`)

**EXPERIMENTAL and opt-in for this release** (Plan 00290). A cross-cutting
`daemon:` sub-block governing the client-side hook transport — the process
that carries a hook's JSON payload from Claude Code to the daemon and back.
Every default is off/null, so a project with no `daemon.transport:` block at
all sees **zero behaviour change**: every hook still runs the existing
`bash` + `python3` forwarder path.

```yaml
daemon:
  transport:
    relay_enabled: false # rung 1: exec the static Rust relay binary (opt-in)
    nc_enabled: false # rung 2: bash `nc -U` path, tried before python3 (opt-in)
    timeout_seconds: 30 # relay --timeout-ms source; also the nc -w budget
    relay_binary: null # absolute-path override; null = {untracked}/bin/hooks-relay
    relay_source: null # "build" | "download" | null — see below
```

**The fallback ladder never loses its floor**: relay binary -> `nc -U` ->
the permanent bash+python3 transport. The last rung is never removed and
carries every existing guarantee (`ensure_daemon` auto-start, fail-open JSON
error emission on any failure) — enabling a faster rung only adds an
earlier successful exit, it never removes the safety net.

**`relay_enabled`/`nc_enabled` and `relay_source` are two SEPARATE, both
explicit, decisions** — nothing about this block acts implicitly:

- `relay_enabled`/`nc_enabled` opt a project's forwarders into trying the
  faster rungs at all.
- `relay_source: build|download` (both default `null`) separately governs
  **how the relay binary gets onto disk** at install/upgrade time. Leaving
  it `null` with `relay_enabled: true` means the ladder simply has nothing
  to exec at rung 1 and starts one rung down — that combination is valid,
  not an error.

**Build-from-source is the first-class route.** `relay_source: build` runs
`relay/build.sh` — a single `rustc --edition 2021 -O -C strip=symbols --target x86_64-unknown-linux-musl` invocation, no cargo, no crates, no
dependency tree — whenever a musl-capable toolchain is present, and is
preferred over downloading. `relay_source: download` fetches a
sha256-digest-verified precompiled asset from the GitHub release matching
the installed version as a convenience; a fetch failure or a digest
mismatch is always an advisory, never a hard install/upgrade failure. The
relay's own source (`relay/hooks_relay.rs`) ships in the package
**regardless of which route is chosen or whether the rung is enabled at
all** — this project's open-source posture means a compiled artifact is
never the only form a client can audit or build.

Run `bin/hooks-daemon transport-probe` after install/upgrade to see which
rungs are actually usable on the machine and which route (`build`/
`download`/unknown) produced the binary currently deployed.

**Toggle the relay with `bin/hooks-daemon transport on|off|status`** (Plan
00294\) — never by hand-editing the three pieces separately. One command
performs config flip (comment-preserving), forwarder regeneration, daemon
restart and a built-in verification pass that invokes the deployed
forwarders exactly as Claude Code does (socket stdin, real payload shapes):
a relay-eligible event must answer with a JSON decision object, the status
line with raw text, a blockable Stop with exit code 2 + reason on stderr,
the daemon's per-event listeners must match the configured state, and —
so a silent fallback can never masquerade as green — the relay binary
itself must answer a probe with fallback disabled. Only the catalogue's
wired forwarder names are judged, so a client's own files in
`.claude/hooks/` are never verification's business. When enabling with no
relay binary on disk, `transport on` provisions it via the configured
`relay_source` (the same build/download routine the installer uses) and
refuses cleanly — nothing flipped — when `relay_source` is null or
provisioning fails. A config with no `relay_enabled:` key at all gets the
key seeded (comment-preserving) instead of a refusal. Any
verification failure AUTO-REVERTS the previous state end-to-end (config +
forwarders + daemon), re-verifies it with the same probes, and exits
non-zero naming what failed — a toggle can never strand a session on a
broken transport. Repeating the current state is a clean no-op.
`transport status` reports the active rung, listener count, relay binary
path/digest and the last toggle's verification result (persisted in the
daemon's untracked dir).

See
`CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md` for
the full per-event-socket design, wire framing, and fallback-ladder
ownership rules.

---

## PreToolUse Handlers

These handlers run **before** Claude Code executes a tool call. They can block dangerous operations or inject advisory context.

### Safety Handlers (Priority 10-20)

Safety handlers protect against destructive or dangerous operations. Most are blocking.

#### destructive_git

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `destructive_git` |
| **Priority**   | 10                |
| **Type**       | Blocking          |
| **Event**      | PreToolUse        |

**Description:** Blocks git commands that permanently destroy data with no recovery possible. Protects against accidental data loss from force pushes, hard resets, and other destructive operations.

**Blocked commands:**

- `git reset --hard` -- destroys all uncommitted changes
- `git clean -f` -- permanently deletes untracked files
- `git checkout .` -- discards all working tree changes
- `git checkout -- <file>` -- discards local changes to specific files
- `git restore <file>` -- discards working tree changes (allows `--staged`)
- `git stash drop` / `git stash clear` -- permanently destroys stashed changes
- `git push --force` -- overwrites remote history
- `git branch -D` -- force-deletes a branch without checking it is merged (lowercase `-d` is allowed)
- `git commit --amend` -- rewrites the previous commit; create a new commit instead

**To delete a branch, always try `git branch -d` first (v3.52.0).** It is
allowed, battle-tested, and refuses unless the branch is genuinely merged.
`hooks-daemon delete-branch <name>...` is the fallback for the case where `-d`
has actually refused — not a general replacement for it.

That case is specific: `-d` requires the branch's commits to be ancestors of
the target, and both a **history rewrite** and a **squash merge** sever
ancestry while leaving the content upstream. After either, `-d` refuses every
affected branch even though nothing would be lost. `delete-branch` fills that
gap, refusing by default and deleting only what it can prove is recoverable,
across these tiers, evaluated cheapest-first:

| Tier                | Proof                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------- |
| `merged`            | Tip is an ancestor of the protected ref (what `git branch -d` proves)                 |
| `merged-unpushed`   | The same ancestry proof, but the branch is ahead of its OWN upstream                  |
| `patch-equivalent`  | Every commit is already upstream by patch-id -- the shape a history rewrite produces  |
| `content-preserved` | Every file version is byte-identical to a blob still reachable from the protected ref |
| `unproven`          | Everything else -- refused, naming the files whose content exists nowhere else        |

`merged-unpushed` exists because `git branch -d` enforces a **different
predicate** from the `merged` proof: *merged into its upstream if it has one*,
falling back to `HEAD` only when it has none. So a branch fully contained in
`main` is still refused while it sits ahead of `origin/<name>` -- git's own
warning says "not yet merged to `refs/remotes/origin/<name>`, even though it is
merged to HEAD". Nothing is at risk: a commit ahead of the upstream and absent
from the protected ref would fail the ancestry test and never reach this tier.
The tier is separate rather than folded into `merged` so that a reader can see
which proof licensed the force flag.

Blocking preconditions -- the current branch, a branch checked out in any
worktree, a protected branch name -- refuse absolutely and `--allow-unproven`
cannot override them.

Nothing is deleted until every branch has been classified and every blocker
resolved, so one unsafe branch in a batch removes none of the others. Git can
still refuse an individual branch on grounds this engine does not model; the run
then reports `refused` with git's own words, lists exactly what was deleted, and
keeps the recovery bundle. A run that deleted nothing removes its bundle, so an
orphaned bundle cannot be mistaken for evidence of a deletion. A bundle is
written first unless `--no-bundle` is passed. The proof is blob
identity, never path presence: a path existing upstream says nothing about the
content at that path.

**Abandoning unproven work is human-gated.** When no tier holds, the branch is
the only copy of real work, so deleting it is a judgement call rather than a
provable fact. `--allow-unproven --reason "..."` is necessary but NOT
sufficient: the command additionally requires a human to type `abandon` at an
interactive terminal. The flags declare *intent*; the prompt asks for
*consent*, and the party requesting a deletion cannot grant its own consent.
An agent's shell has no TTY, so the command refuses there with a message
telling it to hand the decision back — the only unattended route to abandoning
work is for a human to run it themselves. Provably-safe tiers never prompt, so
the safe path stays fully automatic.

For a `merged` branch the command delegates to `git branch -d` rather than
forcing, so git independently re-runs its own ancestry check. A bug in the
classifier therefore cannot cause a silent loss on that tier -- git refuses and
the command fails loudly. The force flag is used only on the tiers where git
would always refuse regardless.

```bash
git branch -d <name>                          # ALWAYS TRY THIS FIRST
hooks-daemon delete-branch --dry-run <name>   # only if -d refused
hooks-daemon delete-branch <name>             # deletes only if provably safe
```

**Example trigger:**

```bash
git reset --hard HEAD~3
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
```

---

#### sed_blocker

| Property       | Value         |
| -------------- | ------------- |
| **Config key** | `sed_blocker` |
| **Priority**   | 10            |
| **Type**       | Blocking      |
| **Event**      | PreToolUse    |

**Description:** Blocks `sed` used to **modify files**. Claude frequently gets sed syntax wrong, and a single mistake can silently corrupt hundreds of files with no recovery — especially via `find -exec sed` or `xargs sed -i`. The Edit tool is the safe alternative for file modifications.

This is **not** a blanket ban on the word `sed`: read-only pipelines that only transform stdout are explicitly allowed.

**What it blocks (strict mode, default):**

- In-place editing -- `sed -i`, `sed -e` invoked to rewrite a file
- Mass modification -- `grep -rl X | xargs sed -i ...`
- Shell scripts (`.sh`/`.bash`) written via the Write tool that contain `sed`

**What it allows:**

- Read-only pipelines that transform stdout only -- `cat file | sed 's/x/y/' | grep z`
- Markdown files mentioning sed (documentation)
- Git commit messages and PR bodies mentioning sed
- `grep` commands searching for the word "sed"
- `echo` commands mentioning sed (without sed command patterns)
- GitHub CLI commands with sed in text content

**Example trigger:**

```bash
sed -i 's/foo/bar/g' file.txt
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
      priority: 10
```

**Options:**

| Option          | Values                             | Default  | Description                            |
| --------------- | ---------------------------------- | -------- | -------------------------------------- |
| `blocking_mode` | `strict`, `direct_invocation_only` | `strict` | Controls which invocations are blocked |

- **`strict`** (default): Blocks both Bash direct invocation *and* the Write tool creating shell scripts that contain `sed`. Safest option.
- **`direct_invocation_only`**: Only blocks Bash tool direct invocation. Allows the Write tool to create shell scripts containing `sed`. Use when wrapper scripts around `sed` are acceptable but direct Claude `sed` calls are not.

```yaml
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
      options:
        blocking_mode: direct_invocation_only  # allow writing scripts that contain sed
```

---

#### absolute_path

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `absolute_path` |
| **Priority**   | 12              |
| **Type**       | Blocking        |
| **Event**      | PreToolUse      |

**Description:** Requires absolute paths (starting with `/`) for all Read, Write, and Edit tool operations. Prevents ambiguity about which file is being operated on.

**Example trigger:**

```
Read tool with file_path: "src/main.py"  (relative path -- blocked)
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    absolute_path:
      enabled: true
      priority: 12
```

---

#### daemon_location_guard

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `daemon_location_guard` |
| **Priority**   | 11                      |
| **Type**       | Blocking                |
| **Event**      | PreToolUse              |

**Description:** Blocks Bash commands that `cd` into `.claude/hooks-daemon/` (or into a daemon-internal subdirectory and then run something). The daemon is an upstream dependency: anything edited inside that directory is overwritten by the next upgrade, and a shell rooted there resolves project-relative paths against the wrong tree.

**Do this instead:** run the daemon CLI from the project root — it works regardless of the current directory.

```bash
.claude/hooks-daemon/bin/hooks-daemon status
.claude/hooks-daemon/bin/hooks-daemon restart
.claude/hooks-daemon/bin/hooks-daemon logs
```

To inspect daemon source for debugging, use the `Read` tool with an absolute path rather than changing directory into it.

**Example trigger:**

```bash
cd .claude/hooks-daemon && ./bin/hooks-daemon status
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    daemon_location_guard:
      enabled: true
      priority: 11
```

---

#### ask_user_question_blocker

| Property       | Value                       |
| -------------- | --------------------------- |
| **Config key** | `ask_user_question_blocker` |
| **Priority**   | 10                          |
| **Type**       | Terminal                    |
| **Event**      | PreToolUse                  |

**Description:** Allows an `AskUserQuestion` tool call only when **every** `question` string begins with the required justification prefix. Pausing the session for a human is a privilege that should carry declared intent — the convention mirrors the Stop handler's `STOPPING BECAUSE:` pattern.

Mixing prefixed and unprefixed questions in one call still blocks: prefix all, or none.

**Allowed:**

```
ASKING BECAUSE: the two schemas are equally valid and the choice is a product decision.
Which storage backend should we use?
```

**Blocked:** tautological or rhetorical questions with one obvious answer ("Should I continue?", "Would you like me to proceed?"), and any question whose options reduce to good-vs-bad. State the assumption in plain output and proceed instead.

**Options:**

| Option            | Type  | Default           | Description                                                                                      |
| ----------------- | ----- | ----------------- | ------------------------------------------------------------------------------------------------ |
| `required_prefix` | `str` | `ASKING BECAUSE:` | The prefix every question must start with. Matched case-sensitively; leading whitespace is fine. |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    ask_user_question_blocker:
      enabled: true
      priority: 10
      options:
        required_prefix: "ASKING BECAUSE:"
```

---

#### worktree_file_copy

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `worktree_file_copy` |
| **Priority**   | 15                   |
| **Type**       | Blocking             |
| **Event**      | PreToolUse           |

**Description:** Prevents copying files between git worktrees and the main repository using `cp`, `mv`, or `rsync`. This bypasses git tracking and destroys branch isolation. The correct approach is to commit in the worktree and merge.

**Example trigger:**

```bash
cp untracked/worktrees/feature-branch/src/file.py src/
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    worktree_file_copy:
      enabled: true
      priority: 15
```

---

#### curl_pipe_shell

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `curl_pipe_shell` |
| **Priority**   | 10                |
| **Type**       | Blocking          |
| **Event**      | PreToolUse        |

**Description:** Blocks piping curl or wget output directly to bash/sh. This pattern executes untrusted remote code without inspection and is a common vector for malware. The safe alternative is to download first, inspect, then execute.

**Example trigger:**

```bash
curl https://example.com/install.sh | bash
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    curl_pipe_shell:
      enabled: true
      priority: 10
```

---

#### root_recursion_guard

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `root_recursion_guard` |
| **Priority**   | 16                     |
| **Type**       | Blocking               |
| **Event**      | PreToolUse             |

**Description:** Blocks a recursive scanner whose path argument resolves to a catastrophic root location. Such a scan walks the entire filesystem, can pin every CPU core for hours, and almost never returns what was actually wanted.

**Blocked** (recursive scanner **and** dangerous root path):

- Scanners: `grep -r`/`-R`/`-rl`, `ugrep -r`, `rgrep`, `find`, `fd`/`fdfind`, `rg`
- Roots: `/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`

**Allowed:** the same scanners scoped to the project — `rg -l "x" /path/to/project`, `grep -rl "x" "$CLAUDE_PROJECT_DIR"`, `grep -rl x src/`, `find . -name y`. A non-recursive `grep x /etc/hosts` is never affected.

**Note:** piping to `head` does NOT bound a `-l`/`-rl` scan. A producer that matches nothing never writes, so it never receives `SIGPIPE` and runs to completion across the whole disk.

**Escape hatch** (a genuinely necessary whole-disk scan):

```bash
MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    root_recursion_guard:
      enabled: true
      priority: 16
```

---

#### pipe_blocker

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `pipe_blocker` |
| **Priority**   | 15             |
| **Type**       | Blocking       |
| **Event**      | PreToolUse     |

**Description:** Blocks piping expensive commands to `tail` or `head`, which causes information loss. If the needed data is not in those truncated lines, the entire expensive command must be re-run. Recommends redirecting to a temp file instead.

**What it allows:**

- Filtering commands piped to tail/head (`grep`, `awk`, `jq`, `sort`, `uniq`, etc.)
- Direct file operations (`tail -n 20 file.txt`)
- `tail -f` (follow mode) and `head -c` (byte count)

**Example trigger:**

```bash
npm test | tail -n 20
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    pipe_blocker:
      enabled: true
      priority: 15
```

**Options:**

| Option            | Type        | Default | Description                                                                                                                                     |
| ----------------- | ----------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `extra_whitelist` | `list[str]` | `[]`    | Additional regex patterns for commands that are CHEAP to re-run and may therefore be piped to `tail`/`head`. Matched case-insensitively.        |
| `extra_blacklist` | `list[str]` | `[]`    | Additional command substrings that must NEVER be piped to `tail`/`head`, even if a whitelist pattern would otherwise have allowed them through. |

`extra_whitelist` is the option the block message itself tells you to set, so it is the usual reason to configure this handler at all:

```yaml
handlers:
  pre_tool_use:
    pipe_blocker:
      enabled: true
      options:
        extra_whitelist:
          - "^my-fast-tool"      # cheap to re-run, safe to truncate
        extra_blacklist:
          - "terraform plan"     # expensive, never truncate
```

---

#### dangerous_permissions

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `dangerous_permissions` |
| **Priority**   | 15                      |
| **Type**       | Blocking                |
| **Event**      | PreToolUse              |

**Description:** Blocks `chmod 777` and `chmod a+rwx` commands that create security vulnerabilities by allowing anyone to read, write, and execute files. Suggests correct permission values (755 for directories, 644 for files, 600 for secrets).

**Example trigger:**

```bash
chmod 777 /var/www/html
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    dangerous_permissions:
      enabled: true
      priority: 15
```

---

#### github_auto_close_keywords

| Property       | Value                        |
| -------------- | ---------------------------- |
| **Config key** | `github_auto_close_keywords` |
| **Priority**   | 18                           |
| **Type**       | Blocking (non-terminal)      |
| **Event**      | PreToolUse                   |

**Description:** Denies a `git commit` / `git merge -m` / `git tag -m` — or a `gh pr create` / `gh pr edit` body — whose message contains a GitHub **auto-closing keyword reference**: one of the nine documented keywords (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`; case-insensitive, optional colon) followed on the **same line** by an issue reference (`#N`, `GH-N`, `owner/repo#N`, or a full issue/PR URL). Such a reference auto-closes the issue the moment the commit reaches the default branch (or the PR merges), and GitHub offers no repository-side switch to disable it. Agents write these forms accidentally ("Fixes #123" reads as changelog prose), so the guard sits at the source.

**Scanning is scoped to the message-bearing segment** (from the `git commit|merge|tag` or `gh pr create|edit` token onward within its `&&`/`||`/`;` segment), so reading is never blocked — `grep 'fixes #12' notes.txt && git commit -m 'clean'` is allowed. Heredoc and `$(cat ...)` shapes inside the segment are still caught.

**All message routes are checked:** inline `-m`/`--message` values, `gh pr` `--body`/`-b` values, and the content of a `-F <file>` / `--file=<file>` / `--body-file <file>` scratch file, read at check time (decoded with replacement, capped at 64 KiB). A missing, unreadable, binary or oversized file is allowed through — the command fails on its own. `-t`/`--template` is not a message source and is ignored.

**Not matched:** the keyword alone (`fixes the race condition`), a bare `#N` without a keyword, a keyword and reference on different lines, `git log --grep=fixes`, and `gh issue close` (a deliberate, different act).

**Rewrite instead:** `Addresses #123`, `Refs #123`, `See #123` — GitHub links these but does not close.

**No escape hatch — by design.** The only legitimate reason to want an auto-closing message is a project whose workflow deliberately uses closing keywords, and that project should set `enabled: false` (or `mode: warn`) instead. A per-command `MUST_..._BECAUSE` hatch existed briefly and was removed: it would normalise bypassing the guard one commit at a time.

**Options:**

| Option | Values          | Default | Description                         |
| ------ | --------------- | ------- | ----------------------------------- |
| `mode` | `block`, `warn` | `block` | `warn` allows with advisory context |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    github_auto_close_keywords:
      enabled: true
      priority: 18
      options:
        mode: block
```

---

#### git_message_backtick

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `git_message_backtick` |
| **Priority**   | 20                     |
| **Type**       | Blocking               |
| **Event**      | PreToolUse             |

**Description:** Blocks an unescaped backtick inside a **double-quoted** `-m`/`--message` value on `git commit` or `git tag`. Bash performs command substitution inside double quotes, so the backticked span is **executed** and its stdout replaces the text. The commit still succeeds, which is what makes the loss silent — a commit in this repository lost a phrase from its body exactly this way, and the stray `fatal:` on the terminal read as git rejecting the commit rather than as bash running a command nobody asked for.

`git tag` is covered because `git tag -a vX.Y.Z -m "..."` is the form the release process itself uses, so the corruption path is live on the release route.

**Options:** none.

**Always allowed** — none of these substitute:

| Form                                       | Why it is safe                               |
| ------------------------------------------ | -------------------------------------------- |
| `git commit -m 'text with \`backticks\`'\` | Single quotes suppress substitution entirely |
| `git commit -F <file>`                     | The message never passes through the shell   |
| `git commit -m "see \\\`cmd\\\` output"\`  | A backslash-escaped backtick is literal      |

**Not matched:** `$(...)`. It substitutes identically, but unlike a backtick it has a legitimate deliberate use in a message (`git commit -m "Release $(cat VERSION)"`). Backticks in a message are essentially always markdown that was meant to be single-quoted.

**Scope:** this handler covers the *corruption* half only. A **dangerous** command inside the backticks is already denied by the full-command-string matching in [`destructive_git`](#destructive_git) and its siblings, which run at a lower priority and give the more useful reason.

**Example trigger:**

```bash
git commit -m "pipe_blocker now allows `git branch`, so the form holds"
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    git_message_backtick:
      enabled: true
      priority: 20
```

---

#### write_clobber_guard

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `write_clobber_guard`   |
| **Priority**   | 16                      |
| **Type**       | Blocking (non-terminal) |
| **Event**      | PreToolUse              |

**Description:** Denies a `Write` to a file that already exists and that the session has not `Read`. `Write` replaces a file's entire contents, so an agent writing blind destroys content it cannot describe — it could not report the loss even afterwards.

**Never blocked:** creating a new file; rewriting a file read or written earlier in the same session; any `Edit` (a targeted replacement of known text, not a whole-file overwrite).

**The remedy is one call:** `Read` the file and retry, or use `Edit`. There is deliberately **no escape hatch** — not for Plan 00259's reason (irreversibility) but because none is needed: a `Read` actually removes the hazard, whereas a typed justification would only declare it acceptable.

**Why it exists.** The `Write` tool documents *"Overwriting an existing file you haven't Read will fail."* Measured under `bypassPermissions`, it does not — an unread file was clobbered and its contents destroyed, reproduced both inside and outside the project. In other permission modes the approval prompt is a real net, so this closes a gap specific to unattended operation. This handler restores a documented contract rather than adding a new rule.

**Why reads and not sizes.** The natural design is to generalise [`plan-shrink-without-journal`](#plan_qa_edit) and block a write that loses many bytes. The incident that motivated this handler defeats that: the clobbering `Write` made the file **bigger** (58 → ~67 lines). The hazard is replacement without knowledge, not shrinkage.

**Non-terminal by design.** The handler ALLOWs on its common path (recording a read), and a terminal ALLOW ends the dispatch chain, disabling every handler behind it. The chain merges most-restrictive-wins, so a non-terminal DENY still denies.

**Not covered:** Bash-mediated writes (`>`, `>>`, `tee`, heredoc) — that surface belongs to the shared bash-write-target work, not here.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    write_clobber_guard:
      enabled: true
      priority: 16
```

---

#### artifact_publish_blocker

| Property       | Value                      |
| -------------- | -------------------------- |
| **Config key** | `artifact_publish_blocker` |
| **Priority**   | 14                         |
| **Type**       | Blocking (terminal)        |
| **Event**      | PreToolUse                 |

**Description:** Blocks publishing an artefact. The `Artifact` tool renders a local file to a page hosted on claude.ai and returns a URL. The page starts private, but it lives **outside** the project: the repository cannot audit what left it, and deleting the artefact later does not un-share a link somebody has already opened. Whether content leaves is the user's decision, so an agent may not make it.

**What it matches:** any `Artifact` call that would create or update a hosted page — an absent `action` (which means publish), `action: "publish"`, or passing `url` to update an existing page. An **unrecognised** action is treated as publishing rather than allowed, so an added action cannot silently open a hole.

**Always allowed:** `action: "list"`. Enumerating existing artefacts discloses nothing new.

**Options:**

| Option           | Values         | Default | Description                                                                                                              |
| ---------------- | -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| `source_disable` | `true`/`false` | `false` | Plan 00293: also keep `.claude/settings.json` at `"enableArtifact": false`, removing the tool at source for new sessions |

**`source_disable` (opt-in, ships off):** for a project that never wants the Artifact tool at all. On the first PreToolUse event after a daemon start, the handler ensures the project's `.claude/settings.json` carries `"enableArtifact": false` — the documented Claude Code switch (honoured in project settings from Claude Code v2.1.242; once any file sets it false, no file can turn it back on) that removes the tool and its multi-thousand-token schema from every **new** session. The write is additive (other keys preserved), idempotent (no write when already `false`), atomic, and takes a one-shot backup at `settings.json.bak.pre-artifact-source-disable` before the first rewrite; failures are logged, never raised. The call-time deny stays as the in-session backstop, since settings are read only at session start. Note the trade: a new session also loses the allowed `list` action, because the whole tool is gone.

**No escape hatch — by design.** Unlike [`git_stash`](#git_stash) and [`ancestry_preserving_merge`](#ancestry_preserving_merge), this handler accepts no `MUST_..._BECAUSE` declaration. Those hatches cover actions whose consequences stay inside the repository; publishing leaves it. An agent able to type its own justification would have self-authorised disclosure, which is the precise thing this guard exists to prevent — the same reasoning behind `delete-branch --allow-unproven` still requiring an interactive human.

**Not covered:** a human publishing through the claude.ai UI. The daemon sees tool calls, not browser clicks — the same honest limitation [`ancestry_preserving_merge`](#ancestry_preserving_merge) records about the GitHub merge button. This handler also does not scan artefact **content**; that is [`sensitive_content`](#sensitive_content)'s job and it already ran when the file was written.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    artifact_publish_blocker:
      enabled: true   # default; only a HUMAN should set this to false
      priority: 14
      options:
        source_disable: true  # opt-in: also write enableArtifact:false to .claude/settings.json
```

---

#### git_stash

| Property       | Value                                        |
| -------------- | -------------------------------------------- |
| **Config key** | `git_stash`                                  |
| **Priority**   | 20                                           |
| **Type**       | Blocking (deny mode) or Advisory (warn mode) |
| **Event**      | PreToolUse                                   |

**Description:** Blocks (or, in `warn` mode, advises against) git stash creation commands. Stashes get forgotten, lost, and block `git pull`. Use `git commit -m 'WIP: ...'` instead — WIP commits are acceptable.

**Options:**

| Option | Values         | Default | Description                                                       |
| ------ | -------------- | ------- | ----------------------------------------------------------------- |
| `mode` | `deny`, `warn` | `deny`  | `deny` hard-blocks stash creation; `warn` allows with an advisory |

- **`deny`** (default) -- Blocks `git stash`, `git stash push`, `git stash save`. This is the shipped default; a stash is not a safe place to leave work.
- **`warn`** -- Allows the command through with an advisory warning suggesting alternatives.

**Escape hatch (deny mode):** prefix the command with a non-empty `MUST_STASH_BECAUSE` reason and the handler stands aside:

```bash
MUST_STASH_BECAUSE="explain why commit won't work"; git stash
```

**Always allowed:** `git stash pop`, `git stash apply`, `git stash list`, `git stash show` (recovery/query operations). Note that `git stash drop` and `git stash clear` are blocked by [`destructive_git`](#destructive_git), not by this handler.

**Example trigger:**

```bash
git stash
git stash push -m "temp changes"
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    git_stash:
      enabled: true
      priority: 20
      options:
        mode: "deny"  # default; use "warn" for advisory-only
```

---

#### ancestry_preserving_merge

| Property       | Value                                         |
| -------------- | --------------------------------------------- |
| **Config key** | `ancestry_preserving_merge`                   |
| **Priority**   | 19                                            |
| **Type**       | Blocking (block mode) or Advisory (warn mode) |
| **Event**      | PreToolUse                                    |

**Description:** Blocks (or, in `warn` mode, advises against) merge integrations that sever ancestry: `git merge --squash`, `gh pr merge --squash`, and `gh pr merge --rebase`. A squash merge collapses every commit into one new commit on the target; a rebase merge replays them with new shas. Either way the branch's commits never become ancestors of the target, so `git branch -d` (the safe, battle-tested delete) refuses the branch forever, even though its content is fully upstream. Only a `--no-ff` merge commit preserves ancestry.

**Options:**

| Option | Values          | Default | Description                                                                       |
| ------ | --------------- | ------- | --------------------------------------------------------------------------------- |
| `mode` | `block`, `warn` | `block` | `block` hard-blocks the ancestry-severing command; `warn` allows with an advisory |

- **`block`** (default) -- Blocks `git merge --squash`, `gh pr merge --squash`, `gh pr merge --rebase`. This is the shipped default; ancestry survives every merge so `git branch -d` stays usable.
- **`warn`** -- Allows the command through with an advisory warning naming the ancestry-preserving alternative.

**Escape hatch (block mode):** prefix the command with a non-empty `MUST_SQUASH_BECAUSE` reason and the handler stands aside (covers both the squash and rebase-merge spellings):

```bash
MUST_SQUASH_BECAUSE="platform mandates squash-only merging"; git merge --squash feature-branch
```

**Always allowed:** `git merge`, `git merge --no-ff`, `gh pr merge --merge` (all preserve ancestry), and a LOCAL `git rebase <branch>` on your own feature branch before merging -- it is the REBASE MERGE *integration button* that severs ancestry, not local rebasing.

**Not covered:** a squash or rebase merge performed through the GitHub web UI. The daemon sees tool calls, not browser clicks.

**Example trigger:**

```bash
git merge --squash feature-branch
gh pr merge --squash 123
gh pr merge --rebase 123
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    ancestry_preserving_merge:
      enabled: true
      priority: 19
      options:
        mode: "block"  # default; use "warn" for advisory-only
```

---

#### lock_file_edit_blocker

| Property       | Value                    |
| -------------- | ------------------------ |
| **Config key** | `lock_file_edit_blocker` |
| **Priority**   | 10                       |
| **Type**       | Blocking                 |
| **Event**      | PreToolUse               |

**Description:** Blocks direct editing of package manager lock files via Write or Edit tools. Lock files must only be modified through their package manager commands (e.g., `npm install`, `composer update`). Supports 14 lock file types across 8 language ecosystems.

**Protected files:** `composer.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `bun.lockb`, `poetry.lock`, `Pipfile.lock`, `pdm.lock`, `Gemfile.lock`, `Cargo.lock`, `go.sum`, `packages.lock.json`, `project.assets.json`, `Package.resolved`

**Example trigger:**

```
Edit tool targeting package-lock.json
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    lock_file_edit_blocker:
      enabled: true
      priority: 10
```

---

#### pip_break_system

| Property       | Value              |
| -------------- | ------------------ |
| **Config key** | `pip_break_system` |
| **Priority**   | 10                 |
| **Type**       | Blocking           |
| **Event**      | PreToolUse         |

**Description:** Blocks `pip install --break-system-packages`, which disables pip's protection against conflicting with the system package manager. This can corrupt the system Python installation and break OS tools. Recommends using virtual environments instead.

**Example trigger:**

```bash
pip install --break-system-packages requests
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    pip_break_system:
      enabled: true
      priority: 10
```

---

#### sudo_pip

| Property       | Value      |
| -------------- | ---------- |
| **Config key** | `sudo_pip` |
| **Priority**   | 10         |
| **Type**       | Blocking   |
| **Event**      | PreToolUse |

**Description:** Blocks `sudo pip install` commands that create system-wide package installations. These conflict with OS package managers and can break system tools. Recommends using virtual environments or `pip install --user` instead.

**Example trigger:**

```bash
sudo pip install requests
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    sudo_pip:
      enabled: true
      priority: 10
```

---

#### daemon_restart_verifier

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `daemon_restart_verifier` |
| **Priority**   | 10                        |
| **Type**       | Advisory                  |
| **Event**      | PreToolUse                |

**Description:** Suggests verifying that the daemon can restart before committing code changes in the hooks daemon repository. This catches import errors and loading failures that unit tests miss. Only activates for git commit commands when working inside the daemon's own repository.

**Example trigger:**

```bash
git commit -m "Add new handler"
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    daemon_restart_verifier:
      enabled: true
      priority: 10
```

---

### Code Quality Handlers

Code quality handlers prevent QA suppression comments and enforce development practices.

#### qa_suppression

| Property       | Value            |
| -------------- | ---------------- |
| **Config key** | `qa_suppression` |
| **Priority**   | 30               |
| **Type**       | Blocking         |
| **Event**      | PreToolUse       |

**Description:** Blocks QA suppression annotations in code written via the Write or Edit tools, across **every supported language**. Suppressions hide real problems and accumulate as technical debt — fix the underlying issue instead.

> **Migration note:** this single handler replaces the former per-language handlers `python_qa_suppression_blocker`, `php_qa_suppression_blocker`, `go_qa_suppression_blocker` and `eslint_disable`. Those config keys no longer exist; a config that still names one fails validation with `Unknown handler '...'`. Delete them and configure `qa_suppression` instead. Language coverage is now added by registering a new strategy (Strategy Pattern), not by adding a handler.

**Blocked annotations, by language:**

| Language              | Blocked annotations                                                     |
| --------------------- | ----------------------------------------------------------------------- |
| Python                | `# noqa`, `# type: ignore`                                              |
| JavaScript/TypeScript | `eslint-disable` inline directives                                      |
| Go                    | `//nolint` directives (golangci-lint)                                   |
| PHP                   | `@phpstan-ignore`, `@psalm-suppress`                                    |
| Java / Kotlin         | `@SuppressWarnings`, `@Suppress`                                        |
| C#                    | `#pragma warning disable`                                               |
| Rust                  | `allow(...)` attributes anywhere in the file (`#[allow]` / `#![allow]`) |

Ruby, Swift and Dart strategies are also registered — see the supported-language table in the project `CLAUDE.md` for the authoritative list.

**Example trigger:**

```python
x = some_func()  # type: ignore
```

**Options:**

| Option          | Type        | Default        | Description                                                                                                                   |
| --------------- | ----------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `exclude_paths` | `list[str]` | `[]`           | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and the built-in defaults.           |
| `languages`     | `list[str]` | all registered | Restrict enforcement to specific languages. Empty/unset enforces every registered strategy; falls back to `daemon.languages`. |

**Built-in exclusions:** per-language vendor / build / `node_modules` directories are always skipped. Use `exclude_paths` for fixtures that must legitimately contain suppression annotations, rather than disabling the handler — see [Path Exclusion](#path-exclusion-exclude_paths).

**Config example:**

```yaml
handlers:
  pre_tool_use:
    qa_suppression:
      enabled: true
      priority: 30
      options:
        exclude_paths:
          - "tests/fixtures/**"
```

---

#### comment_changelog

| Property       | Value               |
| -------------- | ------------------- |
| **Config key** | `comment_changelog` |
| **Priority**   | 31                  |
| **Type**       | Blocking            |
| **Event**      | PreToolUse          |

**Description:** Blocks Write/Edit content that writes HISTORICAL NARRATIVE
into a code comment. A comment describes CURRENT STATE; changelog narrative
belongs in git (the commit message), the project's changelog file, or a
plan's `JOURNAL/` day-file. The failure mode is monotonic — nobody deletes
from a comment changelog, so it only ever grows (Plan 00208's field report: a
bash version-marker trailing comment reached 5,645 characters, six releases
deep, and broke the banner that echoed it).

**Blocked (high-precision) signals**, either denies the write:

- `Prior <version>:` / `Previously <version>:` phrasing
- a dated entry (`2026-08-12: ...`)

Both were measured with zero false positives across this project's own
~1,080 source/test files. The proposal originally specified three further
signals as blocking (a version-transition arrow, a changelog verb naming a
version, and two-or-more distinct versioned entries); the same measurement
found each firing on legitimate code — version-processing utilities citing
multiple example versions in their own docstrings, and "removed in vX.Y"
describing an *external* tool's deprecation. All three are **advisory
only** now (still surfaced as context, never block), alongside `Fixed:`/
`Added:`/`Changed:` bullet runs and retrospective phrasing (`used to`, `no longer`, `we switched from`).

**History as RATIONALE is legitimate and is NOT flagged.** A comment may
recount the past when the past is the reason the code looks the way it is
now — e.g. `# Plan 00047: do NOT re-add DISABLE_MOUSE, see...`. The
separating test: an entry keyed by a RELEASE NUMBER is a changelog; an entry
keyed by a FAILURE MODE (a plan number, a bug description) is a rationale.

**No escape hatch** — unlike `comment_size`, changelog content should be
MOVED to git/a changelog file/a plan `JOURNAL/`, never exempted in place.

**Options:**

| Option                | Type        | Default        | Description                                                                                               |
| --------------------- | ----------- | -------------- | --------------------------------------------------------------------------------------------------------- |
| `max_history_entries` | `int`       | `1`            | More than this many distinct dated/versioned entries in one comment triggers the advisory entries signal. |
| `mode`                | `str`       | `block`        | `block` denies a high-precision hit; `warn` downgrades every finding to advisory context.                 |
| `languages`           | `list[str]` | all registered | Restrict enforcement to specific languages.                                                               |
| `exclude_paths`       | `list[str]` | `[]`           | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and defaults.    |

**Built-in exclusions:** `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, `migrations/`, `.venv/`/`venv/`, `build/`, `dist/`. `.md` files are skipped entirely — markdown prose is not a comment. Only the ADDED text is checked on `Edit` (`new_string`) — removing changelog content is never blocked.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    comment_changelog:
      enabled: true
      priority: 31
      options:
        max_history_entries: 1
        mode: block
```

---

#### comment_size

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `comment_size` |
| **Priority**   | 33             |
| **Type**       | Blocking       |
| **Event**      | PreToolUse     |

**Description:** Caps over-long comments, tiered exactly like `plan-doc-size`
(Plan 00190): only an edit that GROWS an already-over-limit comment can be
denied. Shrinking is silent (always allowed); a same-size edit only advises.
That keeps an over-commented legacy file editable so it can be refactored
down, instead of freezing it. Comment length is mostly a symptom —
`comment_changelog` is the actual defect this project cares about — but a
single comment can still grow unboundedly even without changelog-shaped
phrasing.

**Two independent limits** (either trips it):

- a single comment line longer than `max_comment_line_chars` (default 400)
- a contiguous comment block longer than `max_comment_block_lines` (default 40)

Growth is measured as the aggregate non-doc comment character count in the
edit's touched region (`old_string`/`new_string` for `Edit`; on-disk content
vs. new content for `Write` — `None` for a brand-new file, which always
counts as growth since there is nothing to compare against).

**Docstrings and JSDoc are API documentation, not comments** — exempt from
this handler entirely (still subject to `comment_changelog`).

**Escape hatch** (in-content, matching the daemon's `MUST_..._BECAUSE`
convention):

```bash
# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim upstream licence text, must not be reflowed
```

**Options:**

| Option                    | Type        | Default        | Description                                                                                            |
| ------------------------- | ----------- | -------------- | ------------------------------------------------------------------------------------------------------ |
| `max_comment_line_chars`  | `int`       | `400`          | Single comment line character limit.                                                                   |
| `max_comment_block_lines` | `int`       | `40`           | Contiguous comment block line-count limit.                                                             |
| `mode`                    | `str`       | `block`        | `block` denies a GROWING breach; `warn` downgrades every finding to advisory context.                  |
| `languages`               | `list[str]` | all registered | Restrict enforcement to specific languages.                                                            |
| `exclude_paths`           | `list[str]` | `[]`           | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and defaults. |

**Built-in exclusions:** `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, `migrations/`, `.venv/`/`venv/`, `build/`, `dist/`.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    comment_size:
      enabled: true
      priority: 33
      options:
        max_comment_line_chars: 400
        max_comment_block_lines: 40
        mode: block
```

---

#### verification_result_gate

| Property       | Value                      |
| -------------- | -------------------------- |
| **Config key** | `verification_result_gate` |
| **Priority**   | 34                         |
| **Type**       | Blocking (ships advisory)  |
| **Event**      | PreToolUse                 |

**Description:** Flags a **verifier** (`ansible-lint`, `shellcheck`, `pytest`,
`ruff`, `mypy`, `yamllint`, `go vet`, `bash -n`, `php -l`, `golangci-lint`,
`npm test`, `ansible-playbook --syntax-check`, …) followed by a **mutator**
(`git add`/`commit`/`push`/`tag`, `gh pr create`/`gh issue create`/`gh pr merge`, a real `ansible-playbook` run) in the SAME Bash invocation with
nothing consuming the verifier's exit status. A NEWLINE separates commands
exactly as `;` does — the motivating incident put the lint on one line and the
commit on the next, so the lint failed and the commit ran anyway.

Any of these stands the handler down: `verifier && mutator`; `verifier || { …; exit 1; }`; `rc=$?` followed by an `if`/`case` on it; `set -euo pipefail`
at the top of the invocation. Printing `$?` is NOT consuming it.
`ansible-playbook` appears on both tables and is classified by its flags —
`--syntax-check`/`--check` make it a verifier, their absence a mutator.

This is not a style rule about `;` versus `&&`: statements with no mutator
(no-match `grep -q`, labelled diagnostic sweeps, `echo "exit=$?"` observers)
never fire.

**Options:**

| Option            | Type        | Default | Description                                                                    |
| ----------------- | ----------- | ------- | ------------------------------------------------------------------------------ |
| `mode`            | `str`       | `warn`  | `warn` injects advisory context naming the pair; `block` denies the tool call. |
| `extra_verifiers` | `list[str]` | `[]`    | Additive literal command names treated as verifiers (never regexes).           |
| `extra_mutators`  | `list[str]` | `[]`    | Additive literal command names treated as mutators. Tables cannot be replaced. |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    verification_result_gate:
      enabled: true
      priority: 34
      options:
        mode: warn
        extra_verifiers:
          - "my-project-check"
        extra_mutators:
          - "terraform apply"
```

---

#### bash_safe_mode

| Property       | Value                                |
| -------------- | ------------------------------------ |
| **Config key** | `bash_safe_mode`                     |
| **Priority**   | 36                                   |
| **Type**       | Blocking (ships disabled + advisory) |
| **Event**      | PreToolUse                           |

**Description:** Opt-in bash safe-mode forcer (Plan 00270) — the counterpart
Plan 00268 deferred. When enabled, a Bash invocation with multiple sequenced
statements (`;` or newline separated) must declare the required `set` safety
flags — by default `set -e` (errexit) and `set -o pipefail` (`set -euo pipefail` satisfies both). A command already carrying a satisfying prelude, a
single statement, and a pure `&&` chain (which splits to one statement) are
never flagged. The message and resident guidance teach `set -e`'s blind spots
(disabled inside `if`/`while` conditions and under `!`; non-final `&&`/`||`
operands; `local x=$(fail)` masking; SIGPIPE under `pipefail`) so the prelude
is never mistaken for a guarantee. Complementary to
`verification_result_gate`, which stands down when a prelude is present — the
two never double-fire.

`mode: inject` (auto-prepending the prelude via PreToolUse `updatedInput`) is
reserved but NOT implemented: the daemon's PreToolUse response schema does not
model the field. The value is rejected at config load with a message naming
that gap.

**Escape hatch** for commands that must run every statement (diagnostic
sweeps, exit-code observers): `MUST_SKIP_SAFE_MODE_BECAUSE="explain why"; <command>`.

**Options:**

| Option              | Type        | Default                   | Description                                                                    |
| ------------------- | ----------- | ------------------------- | ------------------------------------------------------------------------------ |
| `mode`              | `str`       | `warn`                    | `warn` injects advisory context; `block` denies. `inject` is rejected at load. |
| `require`           | `list[str]` | `["errexit", "pipefail"]` | Flags to demand: `errexit`, `pipefail`, `nounset`. `nounset` is off-default.   |
| `min_statements`    | `int`       | `2`                       | Sequenced-statement threshold; single statements are never flagged.            |
| `only_with_mutator` | `bool`      | `false`                   | Scope to commands containing an entry from the shared mutator table.           |
| `exempt_patterns`   | `list[str]` | `[]`                      | Additive regexes matched against the whole command.                            |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    bash_safe_mode:
      enabled: true          # ships OFF; enabling is a per-project policy act
      priority: 36
      options:
        mode: warn
        require: [errexit, pipefail]
        min_statements: 2
        only_with_mutator: false
```

---

#### security_antipattern

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `security_antipattern` |
| **Priority**   | 14                     |
| **Type**       | Blocking               |
| **Event**      | PreToolUse             |

**Description:** Blocks Write/Edit of files containing OWASP-class security antipatterns, across every supported language. Fix the code to use the safe pattern instead.

**Blocked categories:**

- **Code injection** -- `eval`, `exec`, `new Function`, `__import__`, `instance_eval`, `yaml.load`
- **Command injection** -- `os.system`, `subprocess(..., shell=True)`, `shell_exec`, `proc_open`, `Runtime.exec`, `Process.Start`, `IO.popen`
- **Unsafe deserialization** -- `pickle.load`, `Marshal.load`, `unserialize`, `ObjectInputStream`, `XMLDecoder`, `BinaryFormatter`
- **XSS** -- `innerHTML`, `dangerouslySetInnerHTML`, `document.write`, `template.HTML`/`JS`/`URL`
- **Hardcoded credentials** -- AWS access keys, GitHub tokens, Stripe keys, private key blocks

**What it does NOT detect:** this is pattern matching on known-dangerous
constructs, not analysis. **SQL injection, weak hashing and path traversal are
not detected** in any language -- each is a property of how a value *flows*,
which a regex cannot see (a concatenated query is only a vulnerability if the
concatenated part is attacker-controlled). Do not read a passing write as
"this code is secure". Coverage also varies by language: a construct blocked
in one is not necessarily blocked in another. See Plan 00204.

**Options:**

| Option          | Type        | Default | Description                                                                                            |
| --------------- | ----------- | ------- | ------------------------------------------------------------------------------------------------------ |
| `exclude_paths` | `list[str]` | `[]`    | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and defaults. |

**Built-in exclusions:** `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, docs and rule-definition directories.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    security_antipattern:
      enabled: true
      priority: 14
      options:
        exclude_paths:
          - "samples/insecure/**"
```

---

#### sensitive_content

| Property       | Value               |
| -------------- | ------------------- |
| **Config key** | `sensitive_content` |
| **Priority**   | 14                  |
| **Type**       | Blocking            |
| **Event**      | PreToolUse          |

**Description:** Blocks a Write/Edit whose ADDED text matches a configured
sensitive pattern or a term in a gitignored secret word list. Only added text
is checked — on `Edit` that is `new_string` — so removing sensitive content is
never blocked.

Two sources, with **deliberately different disclosure rules**:

- **Public patterns** (`public_patterns`) — named regexes that are safe to name.
  The deny reason shows the pattern's name and the exact matched text, so the
  writer can fix it directly.
- **Secret word list** (`secret_word_list_path`) — a gitignored file of terms
  that must never be echoed. A matched term appears nowhere: not in the deny
  reason, not in any log, not in payload capture, not in an archived
  transcript. The deny reason names only a position (`entry N of M in the secret word list`), which is meaningless without the gitignored file. Ask
  the operator what the entry covers — do not try to guess what matched, and do
  not open the file: it is itself read-protected by
  [`secret_file_guard`](#secret_file_guard) (Plan 00272).

A missing, empty or comments-only secret file makes that source silently inert
by design, so a checkout without the file still works.

**Options:**

| Option                  | Type         | Default                      | Description                                                                                                                 |
| ----------------------- | ------------ | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `public_patterns`       | `list[dict]` | `[]`                         | Named regexes: `{name, pattern, description}`. Safe to name, so matches are reported in full.                               |
| `secret_word_list_path` | `str`        | `.claude/block-words.secret` | Path to the gitignored term list, one per line; `#` comments ignored. Matches are reported by index only, never by content. |
| `exclude_paths`         | `list[str]`  | `[]`                         | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and the built-in defaults.         |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    sensitive_content:
      enabled: true
      priority: 14
      options:
        public_patterns:
          - name: internal-host-prefix
            pattern: "internal\\.example\\.corp"
            description: "Internal hostname convention — do not commit"
        secret_word_list_path: ".claude/block-words.secret"
```

Add the secret list to `.gitignore` (`*.secret` covers it) so the terms it
protects are never committed alongside the rule that blocks them.

---

#### secret_file_guard

| Property       | Value               |
| -------------- | ------------------- |
| **Config key** | `secret_file_guard` |
| **Priority**   | 14                  |
| **Type**       | Blocking (terminal) |
| **Event**      | PreToolUse          |

**Description:** Denies any tool call that would put a protected file's
CONTENTS into context (Plan 00272). `Read`, `Write`, `Edit`, `NotebookEdit`
and `Grep` on a protected path are denied (Grep is a content oracle in every
output mode), and so is ANY `Bash` command whose text mentions one — `cat`,
`head`, interpreter one-liners, `cp`/`mv` relocation, command substitution,
sourcing. **Deny-by-default, not a list of bad readers** (the `sed_blocker`
framing); there is no echo exemption and no commit-message exemption.
Authoring a SCRIPT that references a protected path is denied too (the
write-then-execute route); markdown/prose naming a protected file stays
writable. `Glob` is never blocked — presence is the feature.

Two sanctioned routes remain: the `hooks-daemon secret-meta <path>` CLI
(existence, bucketed size, mtime, permissions with a `chmod 600` hygiene
hint, and a keyed HMAC digest — never content), and allowlisted consumers
with the path in flag position (`ansible-playbook --vault-password-file …`;
`ansible-vault view|decrypt` stay denied — those subcommands print secrets).

**No agent escape hatch** (same doctrine as `artifact_publish_blocker`): a
human edits this config block to lift protection. Honest limits: this is
defence in depth over an OS boundary the project must set independently.
A `Grep` rooted at a DIRECTORY gets a bounded protected-name walk (capped —
a very large tree is not fully checked); NOT covered at all: a Bash
recursive content search rooted at an ancestor directory (`grep -r`/`rg`
over a tree containing the file), string-assembled paths, cross-invocation
shell state, pre-existing hard links or copies made before the guard was
enabled, pre-existing scripts that open the file internally, and a
look-alike consumer created in-session (the allowlist matches the command
BASENAME, so a local wrapper named `ansible` passes as the real one).
`*.secret*` is intentionally broad: any Bash token containing `.secret`
trips it — including repo-wide greps for that string; ask the user or have
a human narrow the config when that bites.

**Options:**

| Option              | Type         | Default        | Description                                                                                                                                                                                                                                                        |
| ------------------- | ------------ | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `protected_paths`   | `list[str]`  | `[]`           | Gitignore-style globs, combined with the defaults per `mode`.                                                                                                                                                                                                      |
| `mode`              | `str`        | `additive`     | `additive` merges `protected_paths` onto the defaults (`*.secret*`, `.vault-pass*`, `*.vault-password`, `*vault_pass*`, `id_rsa`, `id_ed25519`); `replace` uses only the project list. An unknown mode behaves as `additive` (fail closed toward more protection). |
| `allowed_consumers` | `list[dict]` | Ansible family | Additive entries: `{command, path_flags, denied_subcommands}`.                                                                                                                                                                                                     |
| `allow_plain_hash`  | `bool`       | `false`        | When true, `secret-meta` also reports exact `size_bytes` and plain `sha256`. Config-only — the CLI has no flag, so an agent cannot self-grant it.                                                                                                                  |
| `exclude_paths`     | `list[str]`  | `[]`           | Scopes ONLY the authored-script content scan (a protected path itself is never excludable). Unioned with `daemon.exclude_paths`.                                                                                                                                   |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    secret_file_guard:
      enabled: true
      priority: 14
      options:
        mode: additive
        protected_paths:
          - "secrets/prod-token"
        allowed_consumers:
          - command: "my-deploy-tool"
            path_flags: ["--secret-file"]
```

---

#### flaggable_content_channel_guard

| Property       | Value                             |
| -------------- | --------------------------------- |
| **Config key** | `flaggable_content_channel_guard` |
| **Priority**   | 14                                |
| **Type**       | Blocking (terminal)               |
| **Event**      | PreToolUse                        |

**Description:** Ships DISABLED (opt-in; Plan 00278 Phase 3d.1). Closes the
one contamination channel [`flaggable_work_advisor`](#flaggable_work_advisor)
can only advise about: content-revealing git commands (`git diff`,
`git show`, `git log -p`/`--patch`, `git add -p`/`--patch`) and the
`grep`/`rg`/`egrep`/`fgrep` family pull a flaggable file's content into
context inside a routine command's output, with no deliberate `Read` at all.

Denies a Bash command segment (statements and pipe/`&&`/`||` spans, quote-
and heredoc-aware) whose SHAPE is content-revealing AND that references a
path matching `flaggable_path_globs`. A plain `git status`, `git log` (no
`-p`), or `git add <path>` (no `-p`) is NOT content-revealing and stays
allowed even when it names a flaggable path — this is a command-SHAPE guard,
not a blanket ban on mentioning a flaggable path in Bash.

**No agent escape hatch** (same doctrine as `secret_file_guard`): an agent
that could type its own justification would have self-authorised exactly the
disclosure this guard exists to prevent. Only a human may lift it, by
editing config.

**Options:**

| Option                             | Type        | Default    | Description                                                                                                               |
| ---------------------------------- | ----------- | ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| `flaggable_path_globs`             | `list[str]` | `[]`       | Gitignore-style globs. Inert until configured — the flaggable boundary is project-specific.                               |
| `extra_content_revealing_patterns` | `list[str]` | `[]`       | Raw regexes matched against a command segment. ALWAYS additive — there is no way to discard the built-in git/grep shapes. |
| `mode`                             | `str`       | `additive` | Governs only `flaggable_path_globs`: `additive` merges onto the (empty) seed; `replace` uses only the project list.       |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    flaggable_content_channel_guard:
      enabled: true
      priority: 14
      options:
        flaggable_path_globs:
          - "firewall/**"
        extra_content_revealing_patterns:
          - '^git\s+blame\b'
```

---

#### quarantine_artefact_read_guard

| Property       | Value                            |
| -------------- | -------------------------------- |
| **Config key** | `quarantine_artefact_read_guard` |
| **Priority**   | 14                               |
| **Type**       | Blocking (terminal)              |
| **Event**      | PreToolUse                       |

**Description:** Ships DISABLED but PRE-SEEDED (opt-in; Plan 00278 Phase
3d.2) — unlike `flaggable_work_advisor`'s empty seed, the marker convention
is project-independent, so enabling this handler needs no configuration.

Enforces the two-file artefact contract's read boundary by PATTERN, not
trust: a subagent reports back through a mandatory
`<topic>-opus-security-SUMMARY` (always safe to read) and an optional
`<topic>-opus-security-DETAIL` holding the raw flaggable substance, which the
coordinator must NEVER read. Denies `Read`/`Edit`/`Grep`/`NotebookEdit` on a
path matching `quarantine_artefact_globs` (default seed:
`*-opus-security-DETAIL*`), and any Bash command whose SHAPE reveals file
content (`cat`, `head`, `tail`, `less`, `more`,
`grep`/`egrep`/`fgrep`/`rg`, `strings`, `xxd`/`hexdump`/`od`, `awk`, or an
interpreter one-liner) mentioning such a path. A `Grep` rooted at a
DIRECTORY gets the same bounded protected-name walk as `secret_file_guard`.

Writing/creating the artefact is deliberately ALLOWED — the subagent authors
it — so `Write` is never checked, and a Bash command that AUTHORS the path
(`cat > file <<EOF` with a redirect) is not treated as a reveal. The
subagent also owns the entire git cycle for its own artefacts, so
`git add`/`git commit`/`git push` mentioning the path are unaffected —
content-revealing git commands are `flaggable_content_channel_guard`'s job,
configured against its own path list.

**No agent escape hatch** (same doctrine as `secret_file_guard`). Only a
human may lift it, by editing config.

**Options:**

| Option                      | Type        | Default                                                    | Description                                                                                        |
| --------------------------- | ----------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `quarantine_artefact_globs` | `list[str]` | `["*-opus-security-DETAIL*", "*-opus-security-DETAIL.md"]` | Gitignore-style globs, combined with the seed per `mode`.                                          |
| `mode`                      | `str`       | `additive`                                                 | `additive` merges `quarantine_artefact_globs` onto the seed; `replace` uses only the project list. |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    quarantine_artefact_read_guard:
      enabled: true
      priority: 14
      options:
        quarantine_artefact_globs:
          - "*-project-quarantine-RAW*"
```

---

#### error_hiding_blocker

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `error_hiding_blocker` |
| **Priority**   | 13                     |
| **Type**       | Blocking               |
| **Event**      | PreToolUse             |

**Description:** Blocks code written via Write/Edit that silently swallows errors. Silent suppression masks bugs and makes debugging impossible — handle errors explicitly: log them, return them, or propagate them.

**Blocked patterns (examples):**

- **Python** -- bare `except` clauses with an empty body; catching and discarding all exceptions
- **Shell** -- redirecting stderr to `/dev/null` to silence a failure; `|| true` to suppress a non-zero exit
- **JavaScript/TypeScript** -- empty `catch` blocks
- **Go** -- `_ = err` (discarding an error return without handling it)

**Options:**

| Option          | Type        | Default | Description                                                                                            |
| --------------- | ----------- | ------- | ------------------------------------------------------------------------------------------------------ |
| `exclude_paths` | `list[str]` | `[]`    | Gitignore-style globs exempting files from scanning. Unioned with `daemon.exclude_paths` and defaults. |

**Built-in exclusions:** the canonical vendored/build-directory core (`node_modules`, `vendor`, `third_party`, `dist`, `build`, `.build`, `target`, `.next`, `.venv`, `venv`, `coverage`) plus `tests/fixtures/`, `tests/assets/`, `__fixtures__/`. Use `exclude_paths` for fixtures of deliberately-broken code instead of disabling the handler.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    error_hiding_blocker:
      enabled: true
      priority: 13
      options:
        exclude_paths:
          - "generated/**"
```

---

#### tdd_enforcement

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `tdd_enforcement` |
| **Priority**   | 15                |
| **Type**       | Blocking          |
| **Event**      | PreToolUse        |

**Description:** Enforces test-driven development by blocking creation of a production source file until a corresponding test file exists. Write the test first (RED), then the source (GREEN), then refactor.

**This handler is NOT Python-only.** It delegates to per-language strategies (Strategy Pattern) and currently covers **11 languages**: Python, Go, JavaScript/TypeScript, PHP, Rust, Java, C#, Kotlin, Ruby, Swift and Dart. Each strategy knows its own test-file conventions.

**Test file locations checked** (any one satisfies the block):

- Separate mirror tree -- `tests/unit/{subdir}/test_{module}.py`
- Collocated -- `{source_dir}/{module}.test.ts` (JS/TS projects)
- Test subdirectory -- `{source_dir}/__tests__/{module}.test.ts`

**Allowed through without blocking:** vendor directories, `node_modules`, build outputs, generated files, and any extension with no registered strategy.

**The deny message lists every location it searched.** If a project's real test directory is absent from that list, the gate can never be satisfied by moving the test — the directory has to be declared with `test_path_map` below.

**Example trigger:**

```
Write tool creating src/handlers/pre_tool_use/new_handler.py
(when tests/unit/handlers/pre_tool_use/test_new_handler.py does not exist)
```

**Options:**

| Option           | Type         | Default        | Description                                                                                                                                                                                               |
| ---------------- | ------------ | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `languages`      | `list[str]`  | all registered | Restrict TDD enforcement to specific languages. Unset or empty enforces EVERY registered language. Takes precedence over the project-wide `daemon.languages` list when both are set.                      |
| `test_locations` | `list[str]`  | all three      | Which INFERENCE styles to try: `separate`, `collocated`, `test_subdir`. Does not affect `test_path_map`, which is a declaration rather than a style.                                                      |
| `test_path_map`  | `list[dict]` | `[]`           | Declared `{source_glob, test_dir}` mappings for layouts no resolver can infer. `test_dir` is project-root-relative (or absolute) and FLAT — the test filename goes directly in it, not mirrored under it. |
| `exclude_paths`  | `list[str]`  | `[]`           | Gitignore-style globs exempted from TDD enforcement entirely. Additive with the project-wide `daemon.exclude_paths`; neither overrides the other.                                                         |

**Declaring a test root vs. excluding a path.** Both escape a false block, but they are not equivalent — `exclude_paths` turns the gate OFF for those files, while `test_path_map` keeps it ON and only tells it where to look. Prefer the map. Reach for the exclusion when the files genuinely are not TDD-able, not when their tests merely live somewhere unusual.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      priority: 15
      options:
        languages: ["python", "typescript"]  # omit to enforce all 11
        # A monorepo whose custom PHPStan rules are tested in a flat PSR-4
        # namespace with no src/ segment anywhere in the path. One entry per
        # app: test_dir is project-root-relative, so it is explicit rather
        # than inferred from the source path.
        test_path_map:
          - source_glob: "**/qaConfig/PHPStan/Rules/**"
            test_dir: "apps/app/qaConfig/Tests"
        exclude_paths:
          - "**/generated/**"
```

A malformed `test_path_map` entry (not a mapping, or missing either key) is logged and skipped rather than raised — one bad line must not disable TDD enforcement wholesale. The skip is visible where you are already looking: the declared directory is simply absent from the deny message's searched-locations list.

---

### Workflow Handlers (Priority 30-55)

Workflow handlers enforce development practices, provide guidance, and manage project structure.

#### plan_number_helper

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `plan_number_helper` |
| **Priority**   | 30                   |
| **Type**       | Blocking             |
| **Event**      | PreToolUse           |

**Description:** Detects bash commands that attempt to discover plan numbers (e.g., `ls -d CLAUDE/Plan/0*`) and blocks them, injecting the correct next plan number instead. Prevents broken bash glob patterns from returning incorrect plan numbers.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    plan_number_helper:
      enabled: true
      priority: 30
      options:
        track_plans_in_project: "CLAUDE/Plan"
```

---

#### lsp_enforcement

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `lsp_enforcement` |
| **Priority**   | 38                |
| **Type**       | Blocking          |
| **Event**      | PreToolUse        |

**Description:** Redirects `Grep` (and Bash `grep`/`rg`) *symbol* lookups to the LSP tools, which are faster and semantically accurate — a text search for a class name matches comments, strings and unrelated files; `goToDefinition` does not.

**Prefer LSP for:**

| Intent                                | LSP operation     |
| ------------------------------------- | ----------------- |
| Where is this class/function defined? | `goToDefinition`  |
| Where is this symbol used?            | `findReferences`  |
| What is this symbol's type/docs?      | `hover`           |
| What symbols does this file define?   | `documentSymbol`  |
| Find a symbol across the project      | `workspaceSymbol` |

**Grep is still correct for:** text patterns in content, log searching, and finding strings in config files. Those are never blocked.

**Options:**

| Option        | Values                             | Default      | Description                                                                                                                                        |
| ------------- | ---------------------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mode`        | `block_once`, `advisory`, `strict` | `block_once` | `block_once` denies the first symbol-lookup grep per session with guidance and allows retries; `strict` denies every one; `advisory` never denies. |
| `no_lsp_mode` | `block`, `advisory`, `disable`     | `block`      | Behaviour when no LSP server is configured. `disable` switches the handler off entirely in that case.                                              |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    lsp_enforcement:
      enabled: true
      priority: 38
      options:
        mode: block_once
        no_lsp_mode: disable  # no LSP configured? stay out of the way
```

---

#### gh_issue_comments

| Property       | Value               |
| -------------- | ------------------- |
| **Config key** | `gh_issue_comments` |
| **Priority**   | 40                  |
| **Type**       | Blocking            |
| **Event**      | PreToolUse          |

**Description:** Ensures `gh issue view` commands always include the `--comments` flag. Issue comments often contain critical context, clarifications, and updates not in the issue body. Blocks the command and suggests adding `--comments`.

**Example trigger:**

```bash
gh issue view 123
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    gh_issue_comments:
      enabled: true
      priority: 40
```

---

#### gh_pr_comments

| Property       | Value            |
| -------------- | ---------------- |
| **Config key** | `gh_pr_comments` |
| **Priority**   | 40               |
| **Type**       | Blocking         |
| **Event**      | PreToolUse       |

**Description:** Ensures `gh pr view` always includes the `--comments` flag. PR comments carry review feedback, reviewer requests and decisions that never appear in the PR body; reading the body alone routinely misses the reason the PR is open.

**Blocked:** `gh pr view 123`, `gh pr view 123 --repo owner/repo`

**Allowed:** `gh pr view 123 --comments`, `gh pr view 123 --json title,body,comments`

When using `--json`, include `comments` in the field list instead of adding `--comments`.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    gh_pr_comments:
      enabled: true
      priority: 40
```

---

#### global_npm_advisor

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `global_npm_advisor` |
| **Priority**   | 40                   |
| **Type**       | Advisory             |
| **Event**      | PreToolUse           |

**Description:** Provides non-blocking advice when global npm/yarn packages are installed (`npm install -g`, `yarn global add`). Suggests using `npx` as a modern alternative that avoids global namespace pollution and version conflicts.

**Example trigger:**

```bash
npm install -g typescript
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    global_npm_advisor:
      enabled: true
      priority: 40
```

---

#### plan_qa_edit

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `plan_qa_edit` |
| **Priority**   | 44             |
| **Type**       | Blocking       |
| **Event**      | PreToolUse     |

**Description:** Lints every Write/Edit of a `PLAN.md` under the plan directory in real time, running the plan QA edit-stage checks against the content the file *would* have after the tool call (for Edit, the old/new replacement is applied to the current file first). Single-file invariants only -- cross-file checks belong to `plan_qa_commit_gate` and `plan_qa_sweep`.

**Fires when:** a Write or Edit targets a file named `PLAN.md` inside the configured plan directory (`plan_workflow.directory`, default `CLAUDE/Plan`), a journal day-file under a plan's `JOURNAL/`, or the plan-index `README.md` at the plan directory root.

**Enforcement mode:** honours `plan_workflow.qa.edit_mode` (`block` | `warn` | `off`, default `block`). In `block`, block-level findings on new material deny the tool call with the exact remediation; `warn` downgrades everything to advisory context; `off` disables the handler. Plans listed in `legacy_plan_allowlist` only ever advise.

**Block-level checks (new material):** a parseable `**Status**:` line must exist (`status-line-present`); the token must be one of Not Started, In Progress, Complete, Blocked, Cancelled, Superseded, Dormant (`status-enum-and-date`); the header must not contradict an all-ticked body (`header-body-coherence`); tasks must use the template grammar `- [ ] ⬜ **Task N.N**:` rather than ad-hoc markers (`task-grammar`). Advisory-level checks cover missing Created/Owner/Priority headers, a terminal status set while the folder is still in the plan root, edits to archived plans, and backticked `src/...` paths that no longer exist.

**The plan index (`README.md`) is linted against TWO rules:** `index-row-length` -- every line must stay under 500 characters, because an index row is a pointer (a link, a status and one clause), not a summary duplicated from the linked `PLAN.md`. Only an edit that makes the index worse blocks (a new over-long line, or a longer worst offender), so an index that already has one stays editable, including by the edit that fixes it. The limit is not configurable: it is shared with the batch guard `tests/integration/test_plan_index_navigability.py`, which asserts a fixed ceiling, and two guards over one rule must read one number. `index-no-log` (advisory, on all three plan QA surfaces) flags a bullet written in LOG grammar -- a bold "Before that"/"Prior to that"/"Previously" lead-in, or a bold ISO date -- because the index has twice re-grown a stacked reconciliation ledger of past recounts instead of stating current truth; history belongs in git or in the relevant plan's `JOURNAL/`. No plan-document rule applies to the index -- it has no `**Status**:` line and needs none.

**Policy configuration:** all three plan QA surfaces (this handler, `plan_qa_commit_gate`, `plan_qa_sweep`) plus the `plan-qa` CLI share ONE policy block under the top-level `plan_workflow.qa` key -- not per-handler `options`:

```yaml
plan_workflow:
  enabled: true
  directory: CLAUDE/Plan
  qa:
    enabled: true               # master switch for all plan QA surfaces
    completed_dir: Completed     # archive dir for completed plans
    cancelled_dir: Cancelled     # archive dir for cancelled plans (null = use completed_dir)
    edit_mode: block             # Stage 1 edit lint: block | warn | off
    commit_gate_mode: warn       # Stage 2 commit gate: block | warn | off
    sweep_mode: advise           # Stage 3 session sweep: advise | off
    require_terminal_date: false # require (YYYY-MM-DD) qualifier on terminal statuses
    staleness_days: 30           # nag active plans with no commit in N days
    legacy_plan_allowlist: []    # plan numbers held to advise-only (grandfathered)
    collision_allowlist: []      # historic duplicate plan numbers to tolerate
    extra_root_files: []         # extra non-plan filenames allowed at the plan root
    journal:                     # per-plan journalling (Plan 00163)
      enabled: true              # master switch for all journal checks
      mode: advise               # advise | block | off (only naming honours block)
      dir_name: JOURNAL           # journal sub-directory name inside a plan folder
      freshness_days: 3          # nag a plan whose newest day-file is older than N days
      enforce_on_completion: false
      grandfather_before: 0      # plans below this number are never nagged for a JOURNAL/
      today_only_mode: block     # advise | block | off (Plan 00197; independent of `mode`)
    plan_doc_size:               # tiered read-cost limits on PLAN.md (Plan 00190)
      enabled: true              # master switch for the plan-doc-size check
      advisory_bytes: 18000      # first nudge (~4,500 tokens)
      advisory_lines: 350
      warning_bytes: 25000       # escalated wording (~6,300 tokens)
      warning_lines: 500
      block_bytes: 35000         # edits denied above this (~8,800 tokens)
      block_lines: 900
```

`plan_doc_size` bounds **plan documents only**. A `PLAN.md` is read in full at
the start of every session that touches the plan, so its size is a recurring
context cost; a `JOURNAL/` day-file is only ever tailed, grepped or read by a
sub-agent, so journals -- and the plan-index `README.md` -- are exempt at any
size. Each tier trips on `bytes > B OR lines > L`, since a long thin plan and a
short dense one cost the same to read. Tiers must increase strictly on both
axes or config validation FAILS FAST, because a non-monotonic setting silently
disables a tier.

Only the top tier denies, and only for an edit that makes the problem worse: an
edit must GROW the file to be blocked. Shrinking is silent (that is the remedy
in progress) and a same-size edit such as ticking a checkbox only advises, so
an already-oversized plan can always be updated and refactored down. Beyond
that, plans in `legacy_plan_allowlist` only ever advise, and a file declaring
`<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->` is downgraded to advice. The
remediation always names three remedies, listed in this order -- extract
durable-but-current detail into a named supporting document in the plan
folder (the most common correct answer), relocate dated narrative into
`JOURNAL/`, or split an over-scoped plan -- and never suggests deleting
content. When the plan folder has no supporting documents at all, the
remediation also appends a folder-shape HINT (never an assertion) to check
whether the bulk is detail wanting a name. See
[CLAUDE/PlanJournalling.md](../../CLAUDE/PlanJournalling.md) for the full
PLAN-vs-supporting-doc-vs-JOURNAL contract.

`extra_root_files` is an ADDITIVE allowlist layered on top of the built-in
accepted set (`README.md`, `CLAUDE.md`, `mkplan.bash`, `_TEMPLATE_.md`,
`_JOURNAL_TEMPLATE_.md`, `_planlib.inc.bash`): list any legitimately-placed
non-plan file of your OWN at the plan root here so the `structure-archive-dirs`
check does not report it as a stray file (a bespoke sourced helper script,
say). Matching is by exact filename; the default empty list is byte-identical
to prior behaviour. `_planlib.inc.bash` -- see below -- is now itself a
built-in member of the accepted set, so a project no longer needs this
allowlist just to deploy it.

The `journal` sub-block governs per-plan journalling (Plan 00163): each plan
folder may carry a `JOURNAL/` of append-only `NNNNN-Journal-YY-MM-DD.md`
day-files, scaffolded by `mkplan.bash`. Seven checks ride the existing plan QA
surfaces (no new handler): `journal-dayfile-naming` + `journal-append-only`
(edit stage, ADVISE), `journal-folder-present` + `journal-freshness` (sweep
stage, ADVISE), `journal-entry-with-progress` + `journal-completion-entry`
(commit stage, ADVISE), and `journal-dayfile-is-today` (edit stage, **BLOCK by
default** — Plan 00197). `journal-entry-with-progress` advises when a commit
changes a plan's PLAN.md tasks but stages no journal entry;
`journal-completion-entry` advises when a commit flips a plan to a terminal
status without a closing journal entry — the latter is OPT-IN, firing only
when `enforce_on_completion: true`.

`journal-dayfile-naming` validates grammar, plan-number coherence and calendar
validity only; it does NOT judge recency. `journal-dayfile-is-today` owns
recency exclusively: a Write/Edit to a journal day-file dated anything other
than TODAY (including yesterday) is blocked, with a remediation naming the
exact today-dated filename to use instead. The split keeps the two checks from
ever giving contradictory advice about one file. `journal-dayfile-naming` may
ratchet to BLOCK via `mode: block`; `journal-dayfile-is-today` has its own
independent `today_only_mode` knob (default `block`) rather than sharing
`mode`, because unlike the rest of the journalling feature it does not ship
advise-first — the failure mode it defends against (an agent silently logging
against the wrong day) is exactly what "yesterday is fine" used to permit.

`journal.mode` and `journal.today_only_mode` are both a CEILING, not a
guarantee — each is **subordinate to the surface mode**. A journal blocker
only denies when the owning surface mode is also `block`: with `edit_mode: warn` (the documented rollout posture) either mode set to `block` degrades to
an advisory, and `edit_mode: off` disables every journal edit check outright
regardless of `journal.enabled`. Set the surface mode first, then ratchet
`journal.mode` / `journal.today_only_mode`.

Set
`grandfather_before` to the plan number at which your project adopted
journalling so pre-existing journal-less plans are never nagged (no backfill),
and `freshness_days` to nag a quiet `JOURNAL/` sooner than the 30-day plan
staleness window. See
[CLAUDE/PlanJournalling.md](../../CLAUDE/PlanJournalling.md) for the entry
grammar, append-only discipline, and the POLICY-vs-CONVENTION split.

**`plan_workflow.scripts`** (Plan 00213 Phase 2, adopted from an externally
proposed `planlib` library) is a SEPARATE, sibling config block under
`plan_workflow` -- not part of `plan_workflow.qa`. When
`plan_workflow.scripts.enabled` is true (and the parent `plan_workflow.enabled`
is also true), the daemon deploys `_planlib.inc.bash` -- a sourced bash
library of safety-critical primitives for plan-folder ORCHESTRATOR scripts an
operator runs from their own terminal (deploy/verify/triage scripts filed
inside a plan folder): script-relative boundary-bounded repo-root resolution,
a tee'd run log with a deterministic drain, ssh-agent key loading, and a
state-change gate. It ships through the SAME idempotent seam as `mkplan.bash`
(daemon-owned, overwritten on every redeploy), but at file mode `0644` --
never `0755` -- because it is SOURCED, not executed.

```yaml
plan_workflow:
  enabled: true
  scripts:
    enabled: false          # ships OFF; deploys _planlib.inc.bash when true
    root_marker: ""         # REQUIRED when enabled -- NO default (see below)
    delegate: ""            # optional: project-relative command runner
    check_flag: "--check"   # dry-run flag threaded into delegated commands
    force_color_var: ""     # optional: env var forced to 1 on a real TTY
    scrubber: ""            # optional: project-relative secret scrubber
    track_run_logs: false   # require scrubber; quarantine unscrubbed logs
```

`root_marker` names the file that marks your project's repository root for
the library's upward filesystem walk (e.g. `pyproject.toml`, `go.mod`,
`ansible.cfg`). There is deliberately **no default**: a wrong default
silently resolves to *some* directory and a deployed script then operates on
the wrong repository without complaint -- the exact incident class the
library exists to prevent. Setting `enabled: true` without `root_marker` (or
setting `root_marker: ".git"`, which is the walk's BOUNDARY rather than a
valid marker) FAILS config validation at daemon start, not at first live
script run.

This is not a universally-recommended feature -- it is for a project whose
`CLAUDE/Plan/` folders contain operator-run deploy/verify/triage scripts
against live infrastructure (Ansible, Kubernetes, bespoke ops tooling). A
pure software-development project has nothing to point it at.

The handler itself is enabled/prioritised in the usual place:

```yaml
handlers:
  pre_tool_use:
    plan_qa_edit:
      enabled: true
      priority: 44
```

**CLI:** lint any file on demand with `.claude/hooks-daemon/bin/hooks-daemon plan-qa --lint <PLAN.md>` (add `--json` for machine-readable output).

---

#### staged_lint_gate

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `staged_lint_gate`        |
| **Priority**   | 43                        |
| **Type**       | Blocking (ships advisory) |
| **Event**      | PreToolUse                |

**Description:** On a `git commit` Bash command, runs the CHEAP/syntax tier of
each staged Added/Copied/Modified file's `LintStrategy` (`python -m py_compile`, `bash -n`, `go vet`, `php -l`, …) -- never the deeper `extended`
linter. This is the backstop half of Plan 00268: `lint_on_edit` only ever sees
a file at the moment `Write`/`Edit` touches it, so a file that reaches the
index by any OTHER route (`git add` of something written earlier in the
session, a merge, a commit of pre-existing changes) is never linted before it
lands. This handler catches that at the one point guaranteed to see it -- the
commit itself.

**Fires when:** a Bash command's command string contains a `git commit`
invocation in any segment (evasion-resistant via `GIT_INVOCATION`/`ENV_PREFIX`
-- `git -C <path> commit`, `env git commit`, and line-continued spellings are
all recognised). Commits inside nested/vendor repos or foreign worktrees are
exempt.

**Enforcement mode:** `mode: warn` (default) renders a failing file's cheap
syntax diagnosis as advisory context; `mode: block` denies the commit with the
same diagnosis as the reason. Above `max_files` staged lintable files (default
20\) the WHOLE check stands down with an advisory naming how many files were
skipped, rather than linting a subset silently.

**Options:**

| Option      | Type  | Default | Description                                                          |
| ----------- | ----- | ------- | -------------------------------------------------------------------- |
| `mode`      | `str` | `warn`  | `warn` injects advisory context naming each failure; `block` denies. |
| `max_files` | `int` | `20`    | Stand down the whole check above this many staged lintable files.    |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    staged_lint_gate:
      enabled: true
      priority: 43
      options:
        mode: warn
        max_files: 20
```

---

#### plan_qa_commit_gate

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `plan_qa_commit_gate` |
| **Priority**   | 44                    |
| **Type**       | Blocking              |
| **Event**      | PreToolUse            |

**Description:** On a `git commit` Bash command, evaluates the *staged* tree against the cross-file plan QA invariants that a single-file edit hook cannot see -- index-at-birth, terminal-state atomicity, number collisions, row/folder bijection, statistics recount, counter sanity, and commit-message hygiene -- at exactly the moment the drift would otherwise become history.

**Fires when:** a Bash command tokenises to a `git commit` (shlex-parsed, so quoted prose like `echo 'git commit'` never false-positives). Commits inside nested/vendor repos or foreign worktrees are exempt, and a missing plan directory degrades to a structural warning rather than crashing the chain.

**Enforcement mode:** honours `plan_workflow.qa.commit_gate_mode` (`block` | `warn` | `off`, default `warn`). In `warn` (the rollout default) findings render as advisory context -- read them and amend the commit content before it lands; `block` denies the commit with a diffable TODO list of what the commit must also contain; `off` disables the gate.

**Invariants checked:** creating a plan folder ⇒ the same commit stages its README index row (`index-at-birth`) with a number from the git counter / `mkplan.bash` (`counter-sanity`, `no-new-collisions`); flipping a plan to Complete/Cancelled/Superseded ⇒ the same commit contains the `git mv` into the archive dir plus the README row and statistics update (`terminal-state-atomic`); a `PLAN.md` staged under an archive dir must carry a terminal status in its STAGED content, not merely in the worktree file — `git mv` stages a rename using the index's existing blob, so a status flip made in the worktree but never re-`git add`ed can land a non-terminal status inside `Completed/`/`Cancelled/` (`archived-status-coherence`); every folder has a README row in the section matching its location and every row link resolves (`row-folder-bijection`, `stats-recount`); every line of the README index stays under 500 characters (`index-row-length`); a commit claiming `Plan NNNNN` that stages src/test/config changes should also touch that plan's PLAN.md (`same-commit-plan-doc`), and plans are referenced as `Plan NNNNN:` (`plan-ref-format`).

**Policy configuration:** shares the top-level `plan_workflow.qa` block documented under [`plan_qa_edit`](#plan_qa_edit).

**CLI:** check the staged tree any time without committing with `.claude/hooks-daemon/bin/hooks-daemon plan-qa --check-staged`.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    plan_qa_commit_gate:
      enabled: true
      priority: 44
```

---

#### plan_time_estimates

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `plan_time_estimates` |
| **Priority**   | 40                    |
| **Type**       | Blocking              |
| **Event**      | PreToolUse            |

**Description:** Blocks time estimates in plan documents. Detects patterns like "Estimated Effort: 2 hours", "Target Completion: 2026-01-15" and prevents them from being written to plan files. Time estimates from LLMs are unreliable.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    plan_time_estimates:
      enabled: true
      priority: 40
```

---

#### plan_workflow

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `plan_workflow` |
| **Priority**   | 45              |
| **Type**       | Advisory        |
| **Event**      | PreToolUse      |

**Description:** Provides guidance when creating plan files in the `CLAUDE/Plan/` directory. Reminds about plan structure, templates, and workflow standards.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    plan_workflow:
      enabled: true
      priority: 45
```

---

#### docs_qa_edit

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `docs_qa_edit` |
| **Priority**   | 47             |
| **Type**       | Blocking       |
| **Event**      | PreToolUse     |

**Description:** Lints every Write/Edit of a documentation-scoped file in real time, running the docs QA EDIT-stage checks against the content the file *would* have after the tool call. Ships as the write-time half of the documentation SSoT enforcement system (`CLAUDE/DocumentationStrategy.md`); the cross-file half is [`docs_qa_commit_gate`](#docs_qa_commit_gate) and the whole-corpus half is [`docs_qa_sweep`](#docs_qa_sweep).

**Fires when:** a Write/Edit targets a file in-scope for the doc corpus (the two audience trees `documentation.trees.agent`/`documentation.trees.human`, `.claude/rules`, `.claude/skills`, `.claude/agents`, a root-level `.md`, a path declared in `documentation.qa.generated_docs`, or any sub-folder `CLAUDE.md` regardless of tree).

**Enforcement mode:** honours `documentation.qa.edit_mode` (`warn` | `block`, default `warn`) as the default for checks without a `check_modes` override.

**Checks:** `pointer-resolves` (a plain markdown link whose target file does not exist — block-eligible only for a link NEW in this edit), `generated-doc-hand-edit` (hand-editing a file `documentation.qa.generated_docs` declares — regenerate it instead), `rules-file-shape` (`.claude/rules/*.md` must stay pointer-only: no fences, tables, numbered procedures or `ssot-quote` blocks, and a 15-line body budget — block-eligible only when an edit adds a violation or grows an already-over-budget body), `quote-drift` (an `<!-- ssot-quote: file.md#anchor -->` block whose body no longer matches its source section, or whose source is missing entirely), `at-import-census` (an `@path.md` import outside `documentation.qa.resident_at_imports` — block-eligible only for an import NEW in this edit), `module-doc-budget` (a sub-folder `CLAUDE.md` outside the two canonical roots gets a line budget: unregistered stays advisory-only under ~40 lines, a doc listed in `documentation.qa.registered_module_docs` gets a larger block tier instead, worse-only).

Every block-eligible check honours `documentation.qa.grandfather_allowlist` — a matching path is held to ADVISE-only regardless of mode (R12).

**Policy configuration:** all three docs QA surfaces (this handler, `docs_qa_commit_gate`, `docs_qa_sweep`) plus the `docs-qa` CLI share ONE policy block under the top-level `documentation` key — not per-handler `options`:

```yaml
documentation:
  enabled: true                # master switch for the docs QA HANDLERS (CLI always runs)
  trees:
    agent: CLAUDE               # root of the agent-facing (verbose) tree
    human: docs                 # root of the human-facing (terse) tree
  qa:
    edit_mode: warn              # Stage 1 EDIT lint: warn | block
    commit_gate_mode: warn       # Stage 2 STAGED commit gate: warn | block
    sweep_mode: advise           # Stage 3 SessionStart sweep: advise | off
    check_modes: {}              # per-check override, e.g. {rules-file-shape: block}
    grandfather_allowlist: []    # file globs held to advise-only forever (R12)
    generated_docs:               # manifest of generated docs (R10)
      - glob: ".claude/HOOKS-DAEMON.md"
        generator: "bin/hooks-daemon generate-docs"
    registered_module_docs: []   # sub-CLAUDE.md files that ARE a canonical home (R7d)
    resident_at_imports:         # the @-import allowlist (R6)
      - "CLAUDE.md"
```

`documentation.enabled` gates only the three HANDLERS — the `docs-qa` CLI always runs regardless, since an explicit invocation is consent. `generated_docs` is pre-seeded with the daemon's own `.claude/HOOKS-DAEMON.md` entry; extend it for a project's own generated docs. `resident_at_imports` defaults to `["CLAUDE.md"]` — the deliberate resident set an `@`-import from root `CLAUDE.md` is exempt from `at-import-census`.

The handler itself is enabled/prioritised in the usual place:

```yaml
handlers:
  pre_tool_use:
    docs_qa_edit:
      enabled: true
      priority: 47
```

**CLI:** lint any file on demand with `.claude/hooks-daemon/bin/hooks-daemon docs-qa --lint <file>` (add `--json` for machine-readable output).

---

#### docs_qa_commit_gate

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `docs_qa_commit_gate` |
| **Priority**   | 47                    |
| **Type**       | Blocking              |
| **Event**      | PreToolUse            |

**Description:** On a `git commit` Bash command, evaluates the *staged* tree against the cross-file docs QA invariants a single-file edit hook cannot see.

**Fires when:** a Bash command tokenises to a `git commit`. Commits inside nested/vendor repos or foreign worktrees are exempt.

**Enforcement mode:** honours `documentation.qa.commit_gate_mode` (`warn` | `block`, default `warn`). In `warn` (the rollout default) findings render as advisory context — read them and amend the commit content before it lands; `block` denies the commit.

**Checks:** `pointer-resolves` (a new dead link in a staged documentation file) and `quote-drift` (a staged `ssot-quote` block that no longer verifies against its source) are block-eligible. `rules-file-orphan-shrink` (advisory-only) flags a staged `.claude/rules/*.md` shrink with no staged growth anywhere in the canonical agent tree, a mechanical approximation of the "promote then thin" transition rule. `plan-promotion-disposition` (advisory-only) flags a staged terminal-status flip of a `PLAN.md` whose folder has supporting docs, where the staged closing journal entry mentions none of PROMOTE/HISTORICAL/DELETE.

`generated-doc-hand-edit` deliberately has no STAGED-stage check — EDIT catches a hand-edit the moment it happens and SWEEP catches anything already on disk at the next session start, so a commit-time check would only restate one of those two.

**Policy configuration:** shares the top-level `documentation` block documented under [`docs_qa_edit`](#docs_qa_edit).

**CLI:** check the staged tree any time without committing with `.claude/hooks-daemon/bin/hooks-daemon docs-qa --check-staged`.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    docs_qa_commit_gate:
      enabled: true
      priority: 47
```

---

#### dispatch_declaration

| Property       | Value                                       |
| -------------- | ------------------------------------------- |
| **Config key** | `dispatch_declaration`                      |
| **Priority**   | 48                                          |
| **Type**       | Advisory (Blocking in opt-in `strict` mode) |
| **Event**      | PreToolUse                                  |

**Description:** On a `Task` tool dispatch, checks the prompt for a file-handoff declaration — either the plan folder the subagent is working in, or an explicit "not plan work" statement paired with a declared file destination. A subagent's final message travels back over a bounded-size wire channel that can silently elide an oversized inline report in the MIDDLE, so a coordinator can receive what looks like a complete report while content is missing (Plan 00307). Declaring a file destination up front is the dispatch-time half of the fix; [`subagent_report_size_blocker`](#subagent_report_size_blocker) is the return-time half.

**Fires when:** the dispatched prompt names neither a plan-folder path (`CLAUDE/Plan/NNNNN-name/`, or the project's configured plan directory) nor the `not plan work` phrase plus a declared write/save/report/output/store destination.

**Enforcement mode:** advisory by default — injects the contract as `additionalContext` and still allows the dispatch. `options.strict: true` denies an undeclared dispatch instead.

**Options:**

| Option                | Type   | Default                    | Description                                                           |
| --------------------- | ------ | -------------------------- | --------------------------------------------------------------------- |
| `strict`              | `bool` | `false`                    | When true, denies a dispatch that declares neither destination shape. |
| `fallback_report_dir` | `str`  | `untracked/agent-reports/` | Directory named in the contract text for non-plan-work dispatches.    |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    dispatch_declaration:
      enabled: true
      priority: 48
      options:
        strict: false
        fallback_report_dir: "untracked/agent-reports/"
```

---

#### npm_command

| Property       | Value         |
| -------------- | ------------- |
| **Config key** | `npm_command` |
| **Priority**   | 50            |
| **Type**       | Blocking      |
| **Event**      | PreToolUse    |

**Description:** Enforces the use of `llm:` prefixed npm script commands and blocks direct `npx` tool usage. Maps common npm commands to their `llm:` equivalents (e.g., `npm run build` should be `npm run llm:build`).

**Config example:**

```yaml
handlers:
  pre_tool_use:
    npm_command:
      enabled: true
      priority: 50
```

---

#### markdown_organization

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `markdown_organization` |
| **Priority**   | 35                      |
| **Type**       | Blocking                |
| **Event**      | PreToolUse              |

**Full documentation:** [`docs/guides/handlers/markdown_organization.md`](handlers/markdown_organization.md)

Enforces markdown file organization rules, plan tracking, allowed paths, and monorepo support. To allow extra locations, prefer the additive `extra_allowed_markdown_paths` option over the legacy `allowed_markdown_paths` full override. See per-handler docs for all options, monorepo interaction, and examples.

**Key options** (the full set is in the per-handler doc linked above):

| Option                          | Type        | Default | Description                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------------- | ----------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extra_allowed_markdown_paths`  | `list[str]` | `[]`    | Additive allowlist of extra locations where markdown may be written. Prefer this over the legacy full override.                                                                                                                                                                                                                                               |
| `allowed_markdown_paths`        | `list[str]` | builtin | Legacy FULL override of the allowed-location list. Setting it discards the built-in defaults.                                                                                                                                                                                                                                                                 |
| `allow_untracked_claude_memory` | `bool`      | `false` | **Blocking behaviour switch.** When `false` (default), writing to Claude auto-memory files (`~/.claude/projects/*/memory/*.md`) is BLOCKED — via Write/Edit *and* via bash redirect/`tee` side-doors. Reading memory stays allowed so existing memory can be migrated out. Set `true` to restore the pre-policy behaviour and permit untracked memory writes. |

The default of `false` is deliberate: durable knowledge belongs in tracked project docs (`CLAUDE.md`, `.claude/rules/*.md`, `docs/`), where teammates and code review can see it — not in per-developer untracked memory.

```yaml
handlers:
  pre_tool_use:
    markdown_organization:
      enabled: true
      priority: 35
      options:
        allow_untracked_claude_memory: false
        extra_allowed_markdown_paths:
          - "design-notes/**"
```

---

#### remote_docs_provenance

| Property       | Value                    |
| -------------- | ------------------------ |
| **Config key** | `remote_docs_provenance` |
| **Priority**   | 36                       |
| **Type**       | Blocking                 |
| **Event**      | PreToolUse               |

Denies a markdown `Write`/`Edit` inside the remote-docs tree whose content lacks valid provenance frontmatter: `source_url`, `fetched_at`, `fidelity`, `source_sha256`, `licence` and `stale_after`. Only the ADDED text is judged on an `Edit`, so removing content is never blocked.

That tree is **captured, not authored** — use `hooks-daemon remote-docs add <url>` to vendor a page and `remote-docs refresh` to pick up upstream changes. Hand-editing a vendored document silently falsifies its recorded `fidelity`, which is what separates a citable corpus from a cache.

The deny names every invalid field at once rather than one per retry. The tree location follows `documentation.trees.remote` (default `remote-docs/`).

```yaml
handlers:
  pre_tool_use:
    remote_docs_provenance:
      enabled: true
      priority: 36
```

---

#### validate_instruction_content

| Property       | Value                          |
| -------------- | ------------------------------ |
| **Config key** | `validate_instruction_content` |
| **Priority**   | 50                             |
| **Type**       | Blocking                       |
| **Event**      | PreToolUse                     |

**Description:** Validates content written to CLAUDE.md and README.md files. Blocks ephemeral content like implementation logs, status indicators, timestamps, and LLM summaries that should not be committed to permanent instruction files.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    validate_instruction_content:
      enabled: true
      priority: 50
```

---

#### web_search_year

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `web_search_year` |
| **Priority**   | 55                |
| **Type**       | Advisory          |
| **Event**      | PreToolUse        |

**Description:** Validates that WebSearch tool queries use the current year instead of outdated years. Claude's training data has a knowledge cutoff, so it may default to searching for older years. This handler detects old years in queries and suggests using the current year.

**Example trigger:**

```
WebSearch with query: "React documentation 2024"
(when current year is 2026)
```

**Config example:**

```yaml
handlers:
  pre_tool_use:
    web_search_year:
      enabled: true
      priority: 55
```

---

### Advisory Handlers

#### flaggable_work_advisor

| Property       | Value                    |
| -------------- | ------------------------ |
| **Config key** | `flaggable_work_advisor` |
| **Priority**   | 58                       |
| **Type**       | Advisory                 |
| **Event**      | PreToolUse               |

**Description:** Delegate-first advisory for safeguard-flaggable work (Plan 00278 Phase 3). Some caller models carry an API-side content safety classifier that keys on attack-mechanics CONTENT, not intent — reading such material into the main context can silently downgrade the session's model for its whole remainder. When a `Read`/`Edit`/`Write`/`Grep` targets a path matching `flaggable_path_globs`, a `Bash` command mentions such a path, or the tool input text carries 2+ of `flaggable_topic_terms`, it advises (NEVER denies) delegating the whole sub-task to the quarantine subagent BEFORE opening the content — `Agent(subagent_type: "<quarantine_agent>")` — deciding from framing/path never by reading first, taking back only the clean summary. Rate-limited once per session per matched path, so retries pass silently. Ships **disabled**: the flaggable boundary is project-specific.

**Options:**

| Option                  | Default                                        | Description                                                           |
| ----------------------- | ---------------------------------------------- | --------------------------------------------------------------------- |
| `flaggable_path_globs`  | `[]`                                           | Globs of paths whose content is likely to trip the classifier         |
| `flaggable_topic_terms` | `[spoof, spoofing, evasion, exploit, rootkit]` | Topic terms; 2+ distinct hits in the tool input trigger the advisory  |
| `quarantine_agent`      | `hooks-daemon-opus-security`                   | Subagent named in the delegation advice                               |
| `mode`                  | `additive`                                     | `additive` extends the built-in seed lists; `replace` uses only yours |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    flaggable_work_advisor:
      enabled: true
      priority: 58
      options:
        flaggable_path_globs:
          - "firewall/**"
          - "intrusion-detection/**"
        flaggable_topic_terms:
          - tarpit
        quarantine_agent: hooks-daemon-opus-security
        mode: additive
```

---

#### british_english

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `british_english` |
| **Priority**   | 60                |
| **Type**       | Advisory          |
| **Event**      | PreToolUse        |

**Description:** Warns about American English spellings in content files (.md, .ejs, .html, .txt). Checks for common American spellings and suggests British equivalents (e.g. `color` to `colour`, `organize` to `organise`). Non-blocking -- allows the operation but adds a warning.

**Checked directories:** the project's configured agent/human documentation
trees (`documentation.trees.agent`/`.human`, default `CLAUDE`/`docs`), plus
the `private_html` extra. The doc-tree names are read from the
`ProjectLayout` facade, so a project configuring non-default tree names is
checked consistently rather than against the hardcoded default.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    british_english:
      enabled: true
      priority: 60
      options:
        extra_check_directories: [private_html] # additive on top of the doc trees
```

---

## PostToolUse Handlers

These handlers run **after** a tool call completes. They analyse output and provide feedback.

#### command_hints

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `command_hints` |
| **Priority**   | 29              |
| **Type**       | Advisory        |
| **Event**      | PostToolUse     |

**Description:** Generic, config-driven advisory: when a Bash command matches a configured hint's `pattern` — a literal command name matched at the start of a shell segment, recognising path-qualified (`/usr/local/bin/agent-browser`) and `env`-prefixed spellings — a reminder is injected as advisory context. ONE handler, not a handler per hinted command. Ships with a single default hint: running `agent-browser` reminds the agent to close the browser session when finished. Never blocks (`terminal: false`).

The pattern never fires on the configured word appearing as an unrelated argument (`grep agent-browser notes.md`) or inside a commit message — only at the START of a shell segment (after stripping an optional `env `/path prefix), using `utils/shell_segmentation.py` and `utils/command_evasion.py` rather than a hand-rolled match.

Each hint is rate-limited independently via `ttl_seconds`, tracked per `(session_id, hint_id)` in a bounded, in-memory map (state resets on daemon restart — a hint may fire once more than strictly necessary after one). An optional `min_calls_between` adds a secondary count-based gate: even once the TTL has elapsed, at least that many further matching calls must also occur before the hint fires again.

**Config paradigm** (mirrors `idle_housekeeping_advisor`'s `custom_guidance_mode`): `options.mode` is `additive` (default) — the project's `options.hints` list is appended to the built-in set, and a project entry whose `id` matches a built-in one OVERRIDES it — or `replace`, which discards the built-in set entirely and uses only the project's list (possibly zero hints, if none are supplied).

**Hint fields:** `id` (stable identifier, also used for override matching), `pattern` (literal command name), `hint` (the reminder text), `ttl_seconds`, and optional `min_calls_between` (default `0`, disabled).

**Config example:**

```yaml
handlers:
  post_tool_use:
    command_hints:
      enabled: true
      priority: 29
      options:
        mode: additive          # additive (default) | replace
        hints:
          - id: agent-browser-close-session   # overrides the built-in hint of the same id
            pattern: "agent-browser"
            hint: "Custom reminder text"
            ttl_seconds: 1800
            min_calls_between: 0
```

---

#### goal_injection

| Property       | Value            |
| -------------- | ---------------- |
| **Config key** | `goal_injection` |
| **Priority**   | 31               |
| **Type**       | Advisory         |
| **Event**      | PostToolUse      |

**Description:** Plan-execution-start sensor for the ccy PTY supervisor's `/goal` injection (Plan 00269). When a `PLAN.md` Write/Edit under the active plan directory (never `Completed/`) results in `**Status**: In Progress`, the handler renders the configured goal lines, joins them into ONE physical line, and atomically writes a `<session>.goal-intent` signal into the context-sidecar directory. The supervisor (actuator) consumes the signal and types `/goal 🤖 [ccy-supervisor] ...` into the foreground chat, subject to every existing injection rail (idle gate, empty-input-box gate, own-session/foreground scoping, structural validation gate). Ships disabled (opt-in); never blocks.

The trigger is STATE-based (first qualifying write per plan per session), not transition-based: the first edit to an already-In-Progress plan in a NEW session re-fires deliberately, re-establishing the goal after a session restart. Manual fallback / debugging tool: `bin/hooks-daemon inject-goal NNNNN` (requires `CLAUDE_CODE_SESSION_ID` in the environment).

**Config paradigm** (mirrors `command_hints`): `options.mode` is `additive` (default) — project `lines` merge onto the built-in set, an entry whose `id` matches a built-in overrides it in place — or `replace`, which uses only the project's lines. The fixed `header` line (machine-origin marker + "NOT human authorisation" clause) is never overridable or removable, even in `replace` mode. Per-line `enabled` flags let a project turn a vetted built-in line on without restating its text.

**Built-in lines:** `header` (always), `work-until-complete` (enabled), `subagents-encouraged` (disabled), `qa-review-subagents` (disabled). The authorisation-flavoured lines ship disabled and their text points at the project's `standing_authorisations` config rather than asserting fresh consent — enabling one is the same deliberate repository-owner act as enabling a standing authorisation entry.

**Placeholders** (closed set; an unknown `{token}` skips the line): `{plan_number}` (5 digits, validated), `{plan_title}` (first PLAN.md heading, sanitised, capped), `{plan_path}` (project-root-relative plan folder).

**Goal ledger (Plan 00276):** every successful emission is also recorded in a daemon-side ledger (`goal-ledger.json` under the daemon untracked dir). Claude Code's `/goal` slot holds ONE condition (last writer wins), so when a new emission lands while another ledgered plan is still `In Progress`, the older entry is marked displaced and the handler injects an advisory naming the displaced plan(s). Entries retire automatically when their plan reaches a terminal status (Complete/Cancelled/Superseded) or leaves the active plan directory. The ledger is fail-open: a missing, corrupt, or unwritable ledger never affects the tool call. `auto_continue_stop` consults the same ledger at Stop time.

| Option                      | Values                 | Default    | Effect                                                          |
| --------------------------- | ---------------------- | ---------- | --------------------------------------------------------------- |
| `mode`                      | `additive` / `replace` | `additive` | Merge project lines onto built-ins, or use only project lines   |
| `lines`                     | list                   | `[]`       | `{id, text, enabled}` entries; matching `id` overrides built-in |
| `once_per_plan_per_session` | `true`/`false`         | `true`     | Latch: fire at most once per `(plan, session)` per daemon run   |

**Config example:**

```yaml
handlers:
  post_tool_use:
    goal_injection:
      enabled: true
      priority: 31
      options:
        mode: additive
        once_per_plan_per_session: true
        lines:
          - id: subagents-encouraged   # enable a vetted built-in line
            enabled: true
          - id: project-motto
            text: "All findings are logged to {plan_path}/REPORTS/."
```

---

#### validate_eslint_on_write

| Property       | Value                      |
| -------------- | -------------------------- |
| **Config key** | `validate_eslint_on_write` |
| **Priority**   | 10                         |
| **Type**       | Advisory                   |
| **Event**      | PostToolUse                |

**Description:** Runs ESLint validation on TypeScript/TSX files after they are written. Automatically checks for lint errors after file writes and reports issues. Skips files under the canonical vendored/build-directory core (`node_modules`, `vendor`, `third_party`, `dist`, `build`, `.build`, `target`, `.next`, `.venv`, `venv`, `coverage`) plus `test-results`, matched by slash-bounded path containment (Plan 00288) so a first-party path like `src/builder/x.ts` is never wrongly skipped.

**Checked extensions:** `.ts`, `.tsx`

**Bash-authored files**: a `.ts`/`.tsx` file written by a Bash command is checked too, not only one written with `Write`/`Edit`. Only AUTHORING routes count — a `>`, `>>`, `>|` or `&>` redirect, `tee`, or a `cat <<EOF` heredoc. A file the command merely RELOCATES (`cp`, `mv`, `install`, `dd`) is never checked, because those bytes were already on disk and denying the copy would report a defect the command did not introduce. A predicted target that does not exist on disk is skipped.

| Option              | Values         | Default | Effect                                                                                                     |
| ------------------- | -------------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| `check_bash_writes` | `true`/`false` | `true`  | Check `.ts`/`.tsx` files authored by a Bash command. `false` restricts the handler to `Write`/`Edit` only. |

**Config example:**

```yaml
handlers:
  post_tool_use:
    validate_eslint_on_write:
      enabled: true
      priority: 10
      options:
        check_bash_writes: true   # false = Write/Edit only
```

---

#### lint_on_edit

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `lint_on_edit` |
| **Priority**   | 25             |
| **Type**       | Blocking       |
| **Event**      | PostToolUse    |

**Description:** Runs a language-aware lint check on source files after they are written, and DENIES on failure. Each language runs a cheap syntax check first (`python -m py_compile`, `bash -n`, `go vet`, `php -l`, …) then an optional deeper linter (`ruff`, `shellcheck`, `golangci-lint`, `rubocop`, …). Tools resolve from the daemon's venv before `PATH`. A linter that is not installed ALLOWs with an advisory — that message means the check was skipped, not that it passed. `.ts`/`.tsx` files are handled by `validate_eslint_on_write` instead, which is stricter.

**Bash-authored files**: as for `validate_eslint_on_write` above — authoring routes are linted, relocation routes are not. A command that authors several files (`tee a.py b.py`) has each linted, and the first failure is reported.

**Ansible YAML** (Plan 00268): a `.yml`/`.yaml` file is linted when it is
plausibly a playbook or role task file — by Ansible's own path conventions
(`playbooks/`, `roles/`, `tasks/`, `handlers/`, `site.yml`, `play-*`,
`playbook-*`) or by carrying a top-level `- hosts:` / `- import_playbook:`
line wherever it sits. Everything else sharing the extension is left alone
(`.github/workflows/`, `docker-compose*`, `group_vars/`, `host_vars/`,
inventories, vault files — never read). The cheap tier is
`ansible-playbook --syntax-check`, which catches a play that will not LOAD
(e.g. an unbalanced quote inside a `shell:` block); full `ansible-lint` runs
at the `extended` tier. The linter runs from the nearest directory containing
`ansible.cfg`, because roles and collections resolve relative to it.

| Option              | Values         | Default | Effect                                                                                          |
| ------------------- | -------------- | ------- | ----------------------------------------------------------------------------------------------- |
| `lint_bash_writes`  | `true`/`false` | `true`  | Lint files authored by a Bash command. `false` restricts the handler to `Write`/`Edit` only.    |
| `languages`         | list           | all     | Restrict which languages are checked.                                                           |
| `command_overrides` | map            | none    | Replace a language's `default`/`extended` command; `extended: null` runs only the syntax check. |
| `exclude_paths`     | glob list      | none    | Exempt paths entirely; unions with `daemon.exclude_paths`.                                      |

**Config example:**

```yaml
handlers:
  post_tool_use:
    lint_on_edit:
      enabled: true
      priority: 25
      options:
        lint_bash_writes: true   # false = Write/Edit only
```

---

#### budget_exhaustion_detector

| Property       | Value                        |
| -------------- | ---------------------------- |
| **Config key** | `budget_exhaustion_detector` |
| **Type**       | Advisory                     |
| **Event**      | PostToolUse                  |

**Description:** Scans a completed tool call's response for budget/quota-exhaustion messaging and tells the agent to report it to you prominently instead of retrying the exhausted tool or quietly degrading to a worse alternative. These budgets are otherwise invisible: the harness replaces the tool result with a system message, so an agent can lose a capability mid-task and you never learn why the work came back thinner. Advisory only — it never blocks.

Matched shapes: the web-search refusal fragments, plus generic "budget…exhausted/used up/exceeded", "quota exceeded" and "budget…limit reached". It deliberately never keys on the ceiling NUMBER (e.g. `CLAUDE_CODE_MAX_WEB_SEARCHES`), which would false-fire on ordinary counts. Each hit is appended to an untracked `budget-exhaustion-events.jsonl` ledger.

**Two self-referential guards** stop it feeding on its own material: a Bash command naming the handler or its ledger is skipped, and so is a tool RESPONSE containing either marker (reading a changelog entry that describes the detector is documentation, not a live signal). Both key on those markers only — prose that discusses budget exhaustion without naming the detector is still matched, by design.

| Option           | Values     | Default                                                 | Effect                                                              |
| ---------------- | ---------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| `excluded_tools` | list       | `Read`, `Grep`, `Glob`, `Edit`, `Write`, `NotebookEdit` | Tools whose responses are never scanned (they return file content). |
| `extra_patterns` | regex list | none                                                    | Additional project-specific shapes; additive to the built-ins.      |
| `exclude_paths`  | glob list  | none                                                    | Exempt paths entirely; unions with `daemon.exclude_paths`.          |

**Config example:**

```yaml
handlers:
  post_tool_use:
    budget_exhaustion_detector:
      enabled: true
      options:
        extra_patterns:
          - "custom budget ceiling hit"
```

---

## SessionStart Handlers

These handlers run when a new Claude Code session begins. They provide environment information and configuration checks.

#### optimal_config_checker

| Property       | Value                    |
| -------------- | ------------------------ |
| **Config key** | `optimal_config_checker` |
| **Priority**   | 52                       |
| **Type**       | Advisory                 |
| **Event**      | SessionStart             |

**Description:** Audits Claude Code environment variables and settings.json for optimal configuration on new sessions. Checks for agent teams, effort level, extended thinking, max output tokens, auto memory, and bash working directory settings. Reports issues with explanations and fix instructions.

**Config example:**

```yaml
handlers:
  session_start:
    optimal_config_checker:
      enabled: true
      priority: 52
```

---

#### git_filemode_checker

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `git_filemode_checker` |
| **Priority**   | 53                     |
| **Type**       | Advisory               |
| **Event**      | SessionStart           |

**Description:** Warns once per new session when the current repo has `git config core.fileMode=false`. That setting causes git to lose `100755` on hook scripts during checkout/merge/rebase, which is the primary trigger for the broken-hook-bit bug class. The handler emits an advisory `additionalContext` block explaining the impact and the fix (`git config core.fileMode true`). Skipped on session resume, no-ops outside git repos.

**Config example:**

```yaml
handlers:
  session_start:
    git_filemode_checker:
      enabled: true
      priority: 53
```

---

#### suggest_status_line

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `suggest_status_line` |
| **Priority**   | 55                    |
| **Type**       | Advisory              |
| **Event**      | SessionStart          |

**Description:** Suggests setting up the daemon-based status line in `.claude/settings.json` if not already configured. Provides example configuration for user reference. Only runs on new sessions, not resumes.

**Config example:**

```yaml
handlers:
  session_start:
    suggest_status_line:
      enabled: true
      priority: 55
```

---

#### version_check

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `version_check` |
| **Priority**   | 55              |
| **Type**       | Advisory        |
| **Event**      | SessionStart    |

**Description:** Checks if the daemon is up-to-date with the latest GitHub release on new sessions. Uses a 24-hour cache to avoid excessive git operations. Only runs on new sessions (not resumes).

**Config example:**

```yaml
handlers:
  session_start:
    version_check:
      enabled: true
      priority: 55
```

---

#### contract_staleness

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `contract_staleness` |
| **Priority**   | 60                   |
| **Type**       | Advisory             |
| **Event**      | SessionStart         |

**Description:** Advises a refresh of the vendored Claude Code hooks contract (`contracts/claude-code-hooks/`) when the installed Claude Code version is newer than `META.json`'s `last_audited_claude_code_version`. **The remedy depends on the install (Plan 00322):** in the daemon repo itself the advisory points at the refresh procedure in `docs/guides/HOOK-CONTRACT-REFRESH.md` (raw-fetch-only extraction); in a client install — where the vendored copy lives under the upgrade-overwritten `.claude/hooks-daemon/` and the refresh is upstream maintainer work — it instead says to upgrade the daemon, or report it upstream if already current. An unresolvable install mode falls back to the client message. Runs on new sessions only, caches the `claude --version` probe for 24 hours, and stays silent when the vendored contract is absent or unreadable — the `hook_contract` QA check owns that failure. Advisory by design, never an auto-refresh (Plan 00271 Decision 3).

**Config example:**

```yaml
handlers:
  session_start:
    contract_staleness:
      enabled: true
      priority: 60
```

---

#### skill_opportunity_detector

| Property       | Value                        |
| -------------- | ---------------------------- |
| **Config key** | `skill_opportunity_detector` |
| **Priority**   | 61                           |
| **Type**       | Advisory                     |
| **Event**      | SessionStart                 |

**Description:** TTL-gated advisory that says when a skill-opportunity scan is due and points at the `bin/hooks-daemon skill-scan` CLI (Plan 00274). The handler itself does file-stat work only — the pipeline (transcript extraction, clustering, redacted digest, report to `untracked/reports/YYYY-MM-DD-skill-opportunities.md`) lives entirely in the CLI, outside every hook path. The report embeds the judging rubric; the agent dispatches an in-session subagent at it and appends the answer under `## Findings` — the CLI never invokes a model. Report-only: a skill is never auto-created. Ships **disabled** — enabling it is the project's explicit opt-in to transcript mining. The CLI works with the handler disabled (a manual run is consent by definition); `enabled` gates only the advisory. Runs on new sessions only; a corrupt or missing state file counts as "scan due"; a recent failed attempt quietens the advisory for a day so an offline box is not nagged every session.

**Options:**

| Option                   | Default  | Description                                                           |
| ------------------------ | -------- | --------------------------------------------------------------------- |
| `check_interval_days`    | `7`      | Advisory cadence floor; never advises more often                      |
| `transcript_window_days` | `14`     | Only transcript files modified inside this window are read            |
| `max_prompts`            | `100`    | Digest cluster cap — bounds judging input regardless of volume        |
| `extra_exclude_patterns` | `[]`     | Additional content-level noise markers, additive to the built-in list |
| `transcript_dir`         | *(none)* | Override of `~/.claude/projects/<slug>` for tests or unusual layouts  |

**Config example:**

```yaml
handlers:
  session_start:
    skill_opportunity_detector:
      enabled: true
      priority: 61
      options:
        check_interval_days: 7
        transcript_window_days: 14
```

---

#### secret_file_hygiene_checker

| Property       | Value                         |
| -------------- | ----------------------------- |
| **Config key** | `secret_file_hygiene_checker` |
| **Priority**   | 62                            |
| **Type**       | Advisory                      |
| **Event**      | SessionStart                  |

**Description:** Session-start half of the on-disk hygiene the `secret-meta` CLI already reports on demand for one path at a time (Plan 00272 Task 6.1). For every configured protected path (the effective `secret_file_guard` globs) that EXISTS on disk, advises — never blocks — when it is not gitignored, is git-tracked, or is group/world-readable. Uses `os.walk`, `git check-ignore`/`git ls-files` and `stat()` only; the file's contents are never opened.

**Options:** none.

**Config example:**

```yaml
handlers:
  session_start:
    secret_file_hygiene_checker:
      enabled: true
      priority: 62
```

---

#### model_fallback_detector

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `model_fallback_detector` |
| **Priority**   | 63                        |
| **Type**       | Advisory                  |
| **Event**      | SessionStart              |

**Description:** Loud alert when the session transcript records a safety-triggered model fallback (Plan 00278 Phase 3/3b). Scans the transcript JSONL for the platform's own `subtype: "model_refusal_fallback"` record (with assistant-message `content[].type == "fallback"` blocks as corroboration) and injects a PROTECTION-DEGRADED-style advisory naming the original model, the fallback model and the refusal category: the substitution is `scope: session`, so the session will not recover on its own — a restart is the only cure. Also writes a secret-redacted diagnostic snapshot (the fallback record plus a bounded window of preceding transcript records) so the project can diagnose WHY it was flagged and tune its `flaggable_work_advisor` delegation config. Advises once per session per distinct fallback record; malformed transcript lines are skipped fail-silent; snapshot write failures degrade to a mention in the advisory.

**Options:**

| Option                    | Default             | Description                                                    |
| ------------------------- | ------------------- | -------------------------------------------------------------- |
| `snapshot_enabled`        | `true`              | Write a diagnostic snapshot per newly detected fallback record |
| `snapshot_dir`            | `untracked/reports` | Snapshot destination, resolved against the project root        |
| `snapshot_window_records` | `20`                | Preceding transcript records captured into each snapshot       |

**Config example:**

```yaml
handlers:
  session_start:
    model_fallback_detector:
      enabled: true
      priority: 63
      options:
        snapshot_enabled: true
        snapshot_dir: untracked/reports
        snapshot_window_records: 20
```

---

#### plan_qa_sweep

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `plan_qa_sweep` |
| **Priority**   | 57              |
| **Type**       | Advisory        |
| **Event**      | SessionStart    |

**Description:** At the start of each new session, sweeps the whole plan directory with the plan QA check catalogue and injects ONE compact drift report as advisory context. Silent when the tree is clean; skipped on session resume.

The catalogue has two halves. The **cross-file** checks compare documents against each other and against git (index/folder bijection, number collisions, statistics recount, index row length, archive structure, status-vs-location coherence, staleness and dormancy). The **document-level** checks apply single-document rules to every `PLAN.md` already on disk: `status-line-present`, `status-enum-and-date`, `header-body-coherence`, `task-grammar`, `path-existence` and `journal-dayfile-naming`.

That second half exists because a rule enforced only at write time cannot see what predates it — a violation introduced before the rule shipped, or by a `git mv`, a merge, or any path other than a Write/Edit tool call, would otherwise never be examined again. The rules that stay edit-only are the ones about the *act of writing* rather than about on-disk state (`archive-immutability`, `journal-append-only`, `journal-dayfile-is-today`, `plan-doc-size`, `template-metadata`), plus `terminal-placement-hint`, whose condition `location-status-coherence` already reports at sweep. Each records its reason in `src/claude_code_hooks_daemon/plan_qa/checks/common.py`, and a test enforces that the classification stays total.

`path-existence` is scoped to plans whose work has begun: a `Not Started`, `Blocked` or `Dormant` plan names the files it *intends* to create, so a missing path there is the expected state rather than drift.

**Fires when:** a new (non-resumed) session starts with `plan_workflow.qa.enabled` true and `sweep_mode: advise`. A configured plan directory that does not exist is itself reported as a structural finding.

**Enforcement mode:** honours `plan_workflow.qa.sweep_mode` (`advise` | `off`, default `advise`). The sweep never blocks -- it only reports drift for you to fix as plan housekeeping.

**Policy configuration:** shares the top-level `plan_workflow.qa` block documented under [`plan_qa_edit`](#plan_qa_edit) -- the archive dir names, `staleness_days`, and the legacy/collision allowlists all apply to the sweep.

**CLI:** the same catalogue runs against the HEAD tree with `.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep`, which exits 1 while findings remain (CI-able). Single-file lint is `plan-qa --lint <PLAN.md>` and the staged-commit check is `plan-qa --check-staged`; add `--json` to any of these for machine-readable output.

`--lint` accepts a relative or absolute path — a relative one resolves against the current directory — and it never reports "clean" for a file it did not examine: a target outside the plan tree exits 2 naming the directory it expected, and a clean single-file run names the file it read rather than claiming the whole tree is clean.

**Config example:**

```yaml
handlers:
  session_start:
    plan_qa_sweep:
      enabled: true
      priority: 57
```

---

#### docs_qa_sweep

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `docs_qa_sweep` |
| **Priority**   | 64              |
| **Type**       | Advisory        |
| **Event**      | SessionStart    |

**Description:** At the start of each new session, rebuilds the doc corpus index (link graph over the two audience trees, `.claude/rules`, `.claude/skills`, `.claude/agents`, and root-level `.md` files) and checks it with the docs QA SWEEP-stage catalogue, injecting a compact drift report as advisory context. Never blocks; silent when the corpus is clean.

**Checks:** `pointer-resolves` (dead links), `generated-doc-hand-edit` (a generated doc that looks hand-edited or stale against the daemon's own version), `rules-file-shape` (a `.claude/rules/*.md` file violating the pointer-only contract), `quote-drift` (re-verified fresh from disk every sweep — the backstop for the advisory-only `quote-source-stale` check, which only fires at edit time), `at-import-census` (an `@path.md` import outside the resident allowlist, found anywhere in the corpus), `module-doc-budget` (every sub-folder `CLAUDE.md` re-measured against its line budget — SWEEP has no before/after to judge worse-only against, so a block-eligible-at-EDIT finding is always reported here as advisory), `duplicate-block` (a structured block — fenced code, table, or list run of 3+ items — whose normalised content matches one in a DIFFERENT document; always advisory, with no block path at all), and `source-tree-markdown` (Plan 00288: a `.md` file under a declared `layout.source_dirs`/`test_dirs` entry that is not a `CLAUDE.md`, `README.md`, generated-docs entry, or test-fixture file — SWEEP-only by design so it never double-reports with `markdown_organization`'s write-time location gate; silent when no `layout:` source/test dirs are declared).

The injected report is capped at the first 8 findings, with a trailing `...and N more` line naming the CLI for the rest — the CLI report itself is never capped.

**Fires when:** a new (non-resumed) session starts with `documentation.enabled` true and `sweep_mode: advise`.

**Enforcement mode:** honours `documentation.qa.sweep_mode` (`advise` | `off`, default `advise`).

**Policy configuration:** shares the top-level `documentation` block documented under [`docs_qa_edit`](#docs_qa_edit).

**CLI:** the same catalogue runs against the current tree with `.claude/hooks-daemon/bin/hooks-daemon docs-qa --sweep`, which exits 1 while findings remain (CI-able); add `--json` for machine-readable output.

**Config example:**

```yaml
handlers:
  session_start:
    docs_qa_sweep:
      enabled: true
      priority: 64
```

---

#### tool_disable_advisor

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `tool_disable_advisor` |
| **Priority**   | 65                     |
| **Type**       | Advisory               |
| **Event**      | SessionStart           |

**Description:** Plan 00293. When the project declares tools in `tool_policy.never_want`, this advisory checks at session start whether each one's source-level disable is actually present in the project's `.claude/settings.json` — `"enableArtifact": false` for Artifact, a bare tool name in `permissions.deny` for any other tool — and, when it is not, names the exact settings change. It never edits settings itself. When Artifact's disable IS in place but the [`artifact_publish_blocker`](#artifact_publish_blocker) `source_disable` option is off, it names that option so the enforcement lives in one deliberate place.

**Honest limits:** detection reads PROJECT settings only. A disable applied at user level, via env var, or in managed settings is invisible to this scan, so findings are worded as "no source disable found in project settings", never "not disabled". Pairs with `bin/hooks-daemon tool-report`, which recommends disable candidates from transcript usage.

**Opt-in (ships disabled).**

**Config example:**

```yaml
handlers:
  session_start:
    tool_disable_advisor:
      enabled: true   # opt-in; requires tool_policy.never_want declarations to do anything
      priority: 65
```

---

#### monorepo_detector

| Property       | Value               |
| -------------- | ------------------- |
| **Config key** | `monorepo_detector` |
| **Priority**   | 66                  |
| **Type**       | Advisory            |
| **Event**      | SessionStart        |

**Description:** Plan 00296 Task 3.4. Detection advises, never decides (`CLAUDE/Code/WorkspaceResolution.md`): when manifest files (`package.json`, `composer.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`) are found BELOW the repository root with none AT it, and no `projects:` block is declared, this advisory names the workspaces it found and prints a ready-to-paste `projects:` block for `.claude/hooks-daemon.yaml`. It never resolves a project boundary itself — only a declared `projects:` entry does that.

**Honest limits:** the walk skips vendored/build directories and dotdirs, and does not descend into a directory holding its own `.git` (a different repository, not a sub-project). It is bounded to a few directory levels below the root so a huge repository cannot make session start slow — a workspace nested deeper than that bound goes unreported.

**Silent when:** a manifest exists at the repository root (an ordinary single-project repo), `projects:` is already declared, or no manifest exists anywhere below the root.

**Config example:**

```yaml
handlers:
  session_start:
    monorepo_detector:
      enabled: true
      priority: 66
```

---

## PreCompact Handlers

These handlers run before Claude Code compacts (summarises) the conversation to save context window space.

#### transcript_archiver — REMOVED

This handler archived the full conversation transcript to a timestamped file before each compaction. It was **removed in Plan 00233**, and the daemon now accepts a leftover `transcript_archiver:` config key without complaint, so an unedited config keeps working.

It was removed because it protected nothing:

- Compaction never deletes the original transcript.
- The original already lives on the same persistent storage as the copies.
- Nothing ever read the archives — no code parsed one.

**Action on upgrade:** delete the `transcript_archiver:` block from your config (optional — it is ignored), and delete `untracked/transcripts/` to reclaim the disk. Those archives are copies of transcripts you still have.

**If you want the transcript:** read Claude Code's own file at `~/.claude/projects/<project-slug>/<session-id>.jsonl`. Note it is **not** redacted.

---

## SessionEnd Handlers

None ship today. `cleanup`, the only one, was removed in Plan 00237: it reaped a `temp/hooks/` directory that nothing in the codebase has ever written. SessionEnd remains a dispatchable event, so a project-level handler can be registered under `session_end` in the usual way.

---

## Stop Handlers

These handlers run when Claude stops generating a response.

#### auto_continue_stop

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `auto_continue_stop` |
| **Priority**   | 15                   |
| **Type**       | Blocking             |
| **Event**      | Stop                 |

**Description:** Enables true auto-continue without user input. Reads the conversation transcript to detect if Claude's last message was a confirmation question ("Would you like me to continue?", "Should I proceed?", etc.) and blocks the stop with an auto-continue instruction. Includes loop prevention via `stop_hook_active` check.

**Goal-ledger Stop defence (Plan 00276):** on the default explain-or-continue denial, the handler consults the daemon-side goal ledger (`goal-ledger.json`, written by `goal_injection`) and appends a challenge naming EVERY ledgered plan still `In Progress` — including plans whose `/goal` condition was displaced by a later goal (the upstream slot is last-writer-wins). Entries retire when their plan reaches a terminal status or is archived, after which stops are no longer challenged on their behalf. Fail-open: a missing or unreadable ledger leaves the default message unchanged.

**Human-input blockage marker (Plan 00298):** when the explicit-stop-explanation branch ALLOWs a stop whose `STOPPING BECAUSE:` text matches a narrow "blocked only on human input" shape (e.g. "blocked only on human input", "need user input", "waiting on the owner's decision" — a short enumerated set, never a broad "input" substring match), the handler records a session-scoped marker (`human-input-blockage-marker.json` under the daemon's untracked dir). `failsafe_cron_blockage_suppressor` reads it to drop the next delivered failsafe-cron tick before it reaches the model. Fail-open: a missing `session_id` or unresolvable project context skips the write silently and never affects the Stop decision.

**Options:**

| Option               | Type   | Default | Description                                                                                                                                                                                                            |
| -------------------- | ------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `continue_on_errors` | `bool` | `true`  | When true, auto-continues even when Claude's message contains error patterns ("error:", "failed:"). Prevents sessions blocking until user returns. Set to `false` to restore original behaviour of stopping on errors. |

**Config example:**

```yaml
handlers:
  stop:
    auto_continue_stop:
      enabled: true
      priority: 15
      options:
        continue_on_errors: true  # default: auto-continue on errors too
```

---

### Why `auto_continue_stop` is the only Stop handler

`auto_continue_stop` is **terminal** and its `matches()` returns true for
almost every Stop event. The handler chain stops at the first matching terminal
handler *regardless of the decision it returns*, so an ordinary ALLOW ends the
chain just as completely as a deny. **Any Stop handler you register above
priority 10 will never run on a normal stop.**

This is not theoretical: `hedging_language_detector`, `dismissive_language_detector`
and `task_completion_checker` all shipped under `stop:`, all looked live in the
config, and none of them ever executed. They were removed in v3.53.0.

If you want to audit assistant messages, use the **`nitpick` pseudo-event**
instead — it fires per turn rather than once per session, and nothing shadows
it. See [Pseudo-Events](CONFIGURATION.md). If you genuinely need the Stop event,
register **below** priority 10 and confirm it fires;
`tests/integration/test_stop_chain_terminal_shadowing.py` pins the boundary.

---

## SubagentStop Handlers

These handlers run when a subagent (Task tool agent) completes.

#### subagent_report_size_blocker

| Property       | Value                          |
| -------------- | ------------------------------ |
| **Config key** | `subagent_report_size_blocker` |
| **Priority**   | 15                             |
| **Type**       | Blocking (terminal)            |
| **Event**      | SubagentStop                   |

**Description:** Denies a SubagentStop whose `last_assistant_message` exceeds a configured character threshold. The vendored SubagentStop contract (v2.1.252) delivers `last_assistant_message` directly on `hook_input`. A live reproduction (Plan 00307) measured a ~24k-token inline report silently truncated in the MIDDLE by the harness while both start/end sentinels survived intact — the coordinator received something that looked complete while roughly seven sections were missing. This handler is the return-time half of the fix; [`dispatch_declaration`](#dispatch_declaration) is the dispatch-time half.

**Fires when:** `last_assistant_message` is a string longer than `threshold_chars`. The deny message instructs the agent to write the full report to a file (the declared plan folder's `subagent-reports/{yymmdd}-{agent-name}-{model}.md`, or the configured fallback directory) and reply with a short summary plus the file path.

**Fails open when:** `last_assistant_message` is missing or not a string (no verdict without a readable report), and never re-fires on `stop_hook_active` re-entry — a subagent that complies after one block cannot be looped.

**Options:**

| Option                | Type  | Default                    | Description                                                          |
| --------------------- | ----- | -------------------------- | -------------------------------------------------------------------- |
| `threshold_chars`     | `int` | `4000`                     | Character length above which the SubagentStop is denied.             |
| `fallback_report_dir` | `str` | `untracked/agent-reports/` | Directory rendered in the deny message for non-plan-work dispatches. |

**Config example:**

```yaml
handlers:
  subagent_stop:
    subagent_report_size_blocker:
      enabled: true
      priority: 15
      options:
        threshold_chars: 4000
        fallback_report_dir: "untracked/agent-reports/"
```

---

## UserPromptSubmit Handlers

These handlers run when the user submits a prompt.

#### git_context_injector

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `git_context_injector` |
| **Priority**   | 20                     |
| **Type**       | Advisory               |
| **Event**      | UserPromptSubmit       |

**Description:** Injects current git status (branch, uncommitted changes) as context when the user submits a prompt. Helps Claude make better decisions by being aware of the repository state.

**Config example:**

```yaml
handlers:
  user_prompt_submit:
    git_context_injector:
      enabled: true
      priority: 20
```

---

#### failsafe_cron_blockage_suppressor

| Property       | Value                               |
| -------------- | ----------------------------------- |
| **Config key** | `failsafe_cron_blockage_suppressor` |
| **Priority**   | 37                                  |
| **Type**       | Blocking                            |
| **Event**      | UserPromptSubmit                    |

**Description:** Zero-token cadence for a session that is stably blocked only on human input (Plan 00298). When `auto_continue_stop` allows a Stop whose `STOPPING BECAUSE:` text matches a narrow "blocked only on human input" shape, it records a session-scoped marker (`human-input-blockage-marker.json` under the daemon's untracked dir). This handler recognises a DELIVERED failsafe-cron tick — the canonical prompt from `recovery_cron_advisor` — and, while a still-valid marker exists for the session, blocks the prompt before it ever reaches the model (Claude Code's documented `UserPromptSubmit` block behaviour). This is genuinely zero-token, unlike a convention/prompt-text backoff that still costs a full turn to read and act on.

**Fails open everywhere:** no marker, a marker for a different session, an expired marker, a corrupt/unreadable marker, or no resolvable project context all ALLOW the tick through unchanged — suppression is a positive assertion made only when every condition is individually verified, never the default. Any genuine (non-cron) user prompt clears the marker immediately (a different handler-independent behaviour of `auto_continue_stop`'s narrow write conditions never re-arming outside a new matching stop).

**Never terminal:** `idle_housekeeping_advisory` and `standing_authorisations` also key off the same canonical cron prompt and must keep running on every non-suppressed tick. A non-terminal DENY still survives later handlers regardless of registration order.

**Options:**

| Option         | Type  | Default | Description                                                                                                                                          |
| -------------- | ----- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `expiry_hours` | float | `24`    | How long a recorded marker stays valid without re-confirmation. Past this, cron ticks resume normally even if the session never sent another prompt. |

**Config example:**

```yaml
handlers:
  user_prompt_submit:
    failsafe_cron_blockage_suppressor:
      enabled: true
      priority: 37
      options:
        expiry_hours: 24
```

**On by default** (dogfooding purpose, Plan 00298). Set `enabled: false` to restore unconditional hourly cron delivery.

---

#### standing_authorisations

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `standing_authorisations` |
| **Priority**   | 57                        |
| **Type**       | Advisory                  |
| **Event**      | UserPromptSubmit          |

**Description:** Gives a project a durable place to record a standing request it has genuinely made. Several instructions an agent receives are conditional on the user having asked ("do not do X unless the user requested it"); those instructions are not wrong, but a request made in conversation is gone by the next session while the restriction is restated on every subsequent request. This handler replays recorded authorisations so the condition stays satisfied.

It is a filing cabinet, not a countermand. A test asserts that no entry's text contains *ignore*, *disregard*, *override*, *overrule* or *bypass*, and that every entry attributes the request to the project and names the config key holding it — an authorisation that cannot be audited is not a request, and one that cannot be revoked is not one either.

**Nothing is authorised by default.** The handler ships enabled so the options are discoverable; every built-in entry ships disabled. Every other default-on handler in this daemon *adds* a restriction — this one relaxes one, and shipping that active would have the daemon assert consent nobody gave.

**Options:**

| Option                       | Type  | Default | Description                                                                                                                                                                                                                           |
| ---------------------------- | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `authorisations`             | list  | `[]`    | List of `{id, enabled}` entries. Built-in ids: `subagent-delegation`, `workflow-orchestration`, `commit-push-cadence`. An unrecognised id is ignored, never fatal.                                                                    |
| `prompt_interval`            | int   | `5`     | Reinforce after this many HUMAN prompts since the last delivery (Plan 00283). Automated turns do not count.                                                                                                                           |
| `interval_minutes`           | float | `15`    | Reinforce once this many minutes have elapsed since the last delivery, whichever fires first with `prompt_interval` (Plan 00283).                                                                                                     |
| `supervisor_channel_enabled` | bool  | `false` | Opt-in (Plan 00283). When on AND a ccy supervisor is armed+live, a due reinforcement is typed by the supervisor as a real user-role line instead of folded hook-context; fails open to hook-context otherwise. See the caution below. |

The two built-in ids are separate because the restrictions they answer are separate: authorising sub-agent delegation says nothing about authorising multi-agent workflow orchestration.

**Delivery cadence (why UserPromptSubmit):** measured, not assumed. Against a real 37,475-record transcript spanning 18 compactions, `SessionStart` proved to be a different transport (`hook_system_message`, appearing zero times in `hook_additional_context`) whose full payload was delivered exactly **once** — the prevailing `is_resume_session` gate is a transcript-size heuristic that is true for every post-compaction session. `UserPromptSubmit` delivered **198** times, one per prompt. Since the instruction being answered lives in a system prompt re-sent on every request, only a per-prompt channel keeps pace with it.

**Bounded cadence, not one-per-prompt (Plan 00283).** The original mechanism injected the short-form text on *every* prompt — reliable but noisy, and it rode along on every automated failsafe-recovery tick. It now delivers the **full** text once per session to establish it, then reinforces only on whichever comes first: `prompt_interval` human prompts or `interval_minutes` elapsed. The 00223 reliability finding is preserved by a *different* mechanism rather than abandoned — the reinforcement still arrives many times per session and still survives compaction; only the redundant one-per-prompt repeats are dropped, and the silence between reinforcements is **bounded** (at most `prompt_interval` prompts / `interval_minutes`), nothing like the unbounded once-ever silence that made SessionStart injection fail. Automated turns (a failsafe-recovery cron tick, a goal-injection line, or the handler's own supervisor-typed reinforcement) are recognised by their machine-origin markers and neither advance the counter nor earn a reinforcement — that both removes the cron-tick spam and gives the supervisor-channel loop-guard for free.

**Supervisor channel (opt-in, `supervisor_channel_enabled`, default off).** Where the ccy PTY supervisor is armed and live, a due reinforcement can be routed through it as a **real typed user-role line** — a stronger channel than folded hook-additional-context — by writing a `<session>.standing-auth-intent` signal the supervisor consumes at its next idle choke point (the same contract as `goal_injection`'s `*.goal-intent`). A fail-closed verbatim machine-origin header gates the signal so anything able to write the file cannot smuggle arbitrary text into a typed line. The first (establishing) delivery of a session is always immediate hook-context; only later reinforcements route. It **fails open** to folded hook-context whenever the channel is off, no supervisor is armed, or the signal write fails, so a reinforcement is never silently lost. **Leave it off unless the deployed supervisor already supports the signal:** a running supervisor only learns to consume it on a ccy *relaunch* (not a daemon restart), so enabling it against an older supervisor would route reinforcements to a signal nothing reads and drop them.

**Config example:**

```yaml
handlers:
  user_prompt_submit:
    standing_authorisations:
      enabled: true
      priority: 57
      options:
        authorisations:
          - id: subagent-delegation
            enabled: true
          - id: workflow-orchestration
            enabled: false
```

Remove an entry (or set `enabled: false`) to withdraw that authorisation. Note this only makes a recorded request visible to the agent — it does not, and cannot, change what the agent is permitted to do.

---

## Notification Handlers

None ship today. `notification_logger`, the only one, was removed in Plan 00237: it appended every Notification event to a JSONL file that nothing in the codebase has ever read. Notification remains a dispatchable event, so a project-level handler can be registered under `notification` in the usual way.

---

## PermissionRequest Handlers

#### auto_approve_reads

| Property       | Value                |
| -------------- | -------------------- |
| **Config key** | `auto_approve_reads` |
| **Priority**   | 10                   |
| **Type**       | Blocking             |
| **Event**      | PermissionRequest    |

**Description:** Automatically approves file read permission requests to reduce permission prompt friction. Write operations still require manual approval.

**Config example:**

```yaml
handlers:
  permission_request:
    auto_approve_reads:
      enabled: true
      priority: 10
```

---

## StatusLine Handlers

These handlers generate the terminal status line displayed by Claude Code. They build segments that are concatenated into a single status display.

#### git_repo_name

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `git_repo_name` |
| **Priority**   | 3               |
| **Type**       | Advisory        |
| **Event**      | StatusLine      |

**Description:** Shows the git repository name at the start of the status line. Cached for performance.

---

#### account_display

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `account_display` |
| **Priority**   | 5                 |
| **Type**       | Advisory          |
| **Event**      | StatusLine        |

**Description:** Reads and displays the Claude account username from `~/.claude/.last-launch.conf`.

---

#### model_context

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `model_context` |
| **Priority**   | 10              |
| **Type**       | Advisory        |
| **Event**      | StatusLine      |

**Description:** Formats a colour-coded model name (blue for Haiku, green for Sonnet, orange for Opus) with effort level, plus a colour-coded context window usage percentage using quarter-circle icons.

---

#### downgrade_indicator

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `downgrade_indicator` |
| **Priority**   | 11                    |
| **Type**       | Advisory              |
| **Event**      | StatusLine            |

**Description:** Surfaces a silent model-family downgrade (Anthropic's safety classifier substituting the session model, e.g. fable to opus, with `scope: session`). Tracks each session's high-water model-family rank (haiku=0, sonnet=1, opus=2, fable=3; `mythos` canonicalises to fable) in a small per-session state file, keyed by session id so a genuinely-fresh session starting on a high-ranked model is never mislabelled a downgrade. Renders a compact warning segment naming the drop (high-water family, an arrow, current family) only while the current render's family ranks below the recorded high-water; silent on a first render, a new high, a recovered render, or an unrecognised model id.

**Options:**

| Option         | Type | Default                   | Description                                                                                           |
| -------------- | ---- | ------------------------- | ----------------------------------------------------------------------------------------------------- |
| `emoji`        | str  | `⚠️`                      | Emoji prefix rendered ahead of the family names.                                                      |
| `label_format` | str  | `{emoji}{high}→{current}` | Placeholders: `{emoji}`, `{high}` (recorded high-water family), `{current}` (family this render saw). |
| `color`        | str  | bold red ANSI code        | ANSI escape sequence wrapping the rendered label.                                                     |

```yaml
handlers:
  status_line:
    downgrade_indicator:
      enabled: true
      priority: 11
```

---

#### git_branch

| Property       | Value        |
| -------------- | ------------ |
| **Config key** | `git_branch` |
| **Priority**   | 20           |
| **Type**       | Advisory     |
| **Event**      | StatusLine   |

**Description:** Shows the current git branch name in the status line, with magicmonty-style status icons (↑N ahead, ↓N behind, ●N staged, ✚N changed, ✖N conflicts, …N untracked, ⚑N stashed).

**Options:**

| Option                   | Type | Default | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------ | ---- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auto_fetch`             | bool | `true`  | Keep remote-tracking refs fresh with a TTL-gated background `git fetch`. The ahead/behind counts compare against LOCAL remote-tracking refs, which are only as fresh as the last fetch — without this, a long-lived daemon shows "in sync" forever while the remote moves on. The fetch runs in a daemon thread (never on the render path), non-interactively (`GIT_TERMINAL_PROMPT=0`, SSH batch mode — it can never hang on a credential prompt), and failures are silently tolerated (offline use is unaffected). |
| `fetch_interval_seconds` | int  | `300`   | Minimum seconds between background fetches per repository. The first status-line render after daemon start always triggers a fetch.                                                                                                                                                                                                                                                                                                                                                                                  |

```yaml
handlers:
  status_line:
    git_branch:
      enabled: true
      options:
        auto_fetch: true
        fetch_interval_seconds: 300
```

---

#### daemon_stats

| Property       | Value          |
| -------------- | -------------- |
| **Config key** | `daemon_stats` |
| **Priority**   | 30             |
| **Type**       | Advisory       |
| **Event**      | StatusLine     |

**Description:** Shows daemon uptime, memory usage, log level, and error count in the status line.

---

## Quick Reference Table

### All Blocking Handlers

Priorities below are the **shipped defaults** from `constants/priority.py`. Several handlers share a priority; ties run in registration order.

| Config Key                     | Event             | Priority | What It Blocks                                                       |
| ------------------------------ | ----------------- | -------- | -------------------------------------------------------------------- |
| `destructive_git`              | PreToolUse        | 10       | git reset --hard, clean -f, push --force, branch -D, etc.            |
| `sed_blocker`                  | PreToolUse        | 10       | sed used to MODIFY files (read-only pipelines are allowed)           |
| `curl_pipe_shell`              | PreToolUse        | 10       | curl/wget piped to bash/sh                                           |
| `lock_file_edit_blocker`       | PreToolUse        | 10       | Direct editing of lock files                                         |
| `pip_break_system`             | PreToolUse        | 10       | pip --break-system-packages                                          |
| `sudo_pip`                     | PreToolUse        | 10       | sudo pip install                                                     |
| `ask_user_question_blocker`    | PreToolUse        | 10       | AskUserQuestion without an `ASKING BECAUSE:` prefix                  |
| `daemon_location_guard`        | PreToolUse        | 11       | cd into .claude/hooks-daemon/                                        |
| `absolute_path`                | PreToolUse        | 12       | Relative paths in Read/Write/Edit                                    |
| `error_hiding_blocker`         | PreToolUse        | 13       | Code that silently swallows errors                                   |
| `security_antipattern`         | PreToolUse        | 14       | Dangerous constructs (eval, shell exec, deserialization, XSS, creds) |
| `artifact_publish_blocker`     | PreToolUse        | 14       | Publishing an artefact (a claude.ai URL outside the project)         |
| `write_clobber_guard`          | PreToolUse        | 16       | Write to an existing file not read this session                      |
| `worktree_file_copy`           | PreToolUse        | 15       | cp/mv/rsync between worktrees                                        |
| `pipe_blocker`                 | PreToolUse        | 15       | Expensive commands piped to tail/head                                |
| `dangerous_permissions`        | PreToolUse        | 15       | chmod 777, chmod a+rwx                                               |
| `tdd_enforcement`              | PreToolUse        | 15       | Production code without tests (11 languages)                         |
| `root_recursion_guard`         | PreToolUse        | 16       | Recursive scans rooted at /, /home, $HOME, ...                       |
| `github_auto_close_keywords`   | PreToolUse        | 18       | GitHub auto-closing keyword refs (Fixes #N) in git/gh pr messages    |
| `git_stash`                    | PreToolUse        | 20       | git stash creation (deny by default; configurable)                   |
| `git_message_backtick`         | PreToolUse        | 20       | Backticks in a double-quoted git -m (bash executes them)             |
| `ancestry_preserving_merge`    | PreToolUse        | 19       | git merge --squash, gh pr merge --squash/--rebase (severs ancestry)  |
| `qa_suppression`               | PreToolUse        | 30       | noqa, type: ignore, eslint-disable, nolint, ... (all langs)          |
| `plan_number_helper`           | PreToolUse        | 30       | Broken plan number discovery commands                                |
| `comment_changelog`            | PreToolUse        | 31       | Changelog narrative in a comment (`Prior <version>:`, dated entries) |
| `comment_size`                 | PreToolUse        | 33       | Over-long comments growing past the size limit                       |
| `markdown_organization`        | PreToolUse        | 35       | Disorganised markdown; untracked Claude memory writes                |
| `lsp_enforcement`              | PreToolUse        | 38       | Grep/rg used for symbol lookups (use LSP)                            |
| `gh_issue_comments`            | PreToolUse        | 40       | gh issue view without --comments                                     |
| `gh_pr_comments`               | PreToolUse        | 40       | gh pr view without --comments                                        |
| `plan_time_estimates`          | PreToolUse        | 40       | Time estimates in plan docs                                          |
| `npm_command`                  | PreToolUse        | 50       | Non-llm: npm commands                                                |
| `validate_instruction_content` | PreToolUse        | 50       | Ephemeral content in CLAUDE.md                                       |
| `auto_continue_stop`           | Stop              | 15       | Stops after confirmation questions                                   |
| `auto_approve_reads`           | PermissionRequest | 10       | (Approves) read-only tools in bypassPermissions mode                 |

### All Advisory Handlers

| Config Key                 | Event            | Priority | What It Does                                   |
| -------------------------- | ---------------- | -------- | ---------------------------------------------- |
| `daemon_restart_verifier`  | PreToolUse       | 10       | Suggests daemon restart before commits         |
| `verification_result_gate` | PreToolUse       | 34       | Verifier result unconsumed before a mutator    |
| `bash_safe_mode`           | PreToolUse       | 36       | Opt-in safe-prelude forcer (ships disabled)    |
| `staged_lint_gate`         | PreToolUse       | 43       | Cheap syntax check over staged files           |
| `global_npm_advisor`       | PreToolUse       | 40       | Suggests npx over global installs              |
| `plan_workflow`            | PreToolUse       | 45       | Guidance for plan creation                     |
| `web_search_year`          | PreToolUse       | 55       | Warns about outdated search years              |
| `british_english`          | PreToolUse       | 60       | Warns about American spellings                 |
| `validate_eslint_on_write` | PostToolUse      | 10       | Runs ESLint after .ts/.tsx writes              |
| `command_hints`            | PostToolUse      | 29       | Config-driven reminder after a command         |
| `goal_injection`           | PostToolUse      | 31       | Goal-intent signal on plan flip to In Progress |
| `optimal_config_checker`   | SessionStart     | 52       | Audits Claude Code settings                    |
| `git_filemode_checker`     | SessionStart     | 53       | Warns when core.fileMode=false                 |
| `suggest_status_line`      | SessionStart     | 55       | Suggests status line setup                     |
| `version_check`            | SessionStart     | 55       | Checks for daemon updates                      |
| `plan_qa_sweep`            | SessionStart     | 57       | Reports plan-tree drift once a session         |
| `contract_staleness`       | SessionStart     | 60       | Advises a hooks-contract audit refresh         |
| `git_context_injector`     | UserPromptSubmit | 20       | Injects git status context                     |
| `nitpick.hedging_language` | Nitpick          | 20       | Detects guessing language per turn             |

---

## Disabling a Handler

To disable any handler, set `enabled: false` in your config:

```yaml
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: false  # Allow sed commands
```

## Handler Priority System

Priority determines execution order. Lower numbers run first. The priority
bands are documented once, in the agent-tree
[Priority Guide](../../CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide); the band
boundaries derive from `PriorityRange` in
`src/claude_code_hooks_daemon/constants/priority.py`.

When two handlers have the same priority, they run in registration order.
