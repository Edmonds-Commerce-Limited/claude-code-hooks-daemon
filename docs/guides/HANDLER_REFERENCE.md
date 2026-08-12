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

## Content-Blocker Path Exclusion (`exclude_paths`)

The three content-scanning blocking handlers -- `security_antipattern`, `qa_suppression`, and `error_hiding_blocker` -- accept gitignore-style glob patterns that exempt matching files from scanning. This is the supported way for a project (e.g. a QA/linting library) to keep intentionally-"bad" fixture code out of the blockers instead of disabling a whole handler.

Globs support `*` (within a segment), `?` (single char), and `**` (zero-or-more path segments). Examples: `**/fixtures/**`, `samples/**/*.py`, `tests/assets/**`.

**Two levels, combined as a union:**

- **Project-wide** -- `daemon.exclude_paths` (a top-level `daemon:` key). Inherited by all three handlers.
- **Per-handler** -- `handlers.pre_tool_use.<handler>.options.exclude_paths`. Applies to that handler only.

A file is exempt if it matches the union of the project-wide list, the handler's own list, and the handler's built-in defaults.

**Built-in defaults** (always skipped, no config needed):

- `error_hiding_blocker`: `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, `__fixtures__/` (added in v3.35.0 for parity with its siblings).
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
across four tiers evaluated cheapest-first:

| Tier                | Proof                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------- |
| `merged`            | Tip is an ancestor of the protected ref (what `git branch -d` proves)                 |
| `patch-equivalent`  | Every commit is already upstream by patch-id -- the shape a history rewrite produces  |
| `content-preserved` | Every file version is byte-identical to a blob still reachable from the protected ref |
| `unproven`          | Everything else -- refused, naming the files whose content exists nowhere else        |

Blocking preconditions -- the current branch, a branch checked out in any
worktree, a protected branch name -- refuse absolutely and `--allow-unproven`
cannot override them. Deletion is all-or-nothing across the batch and writes a
recovery bundle first unless `--no-bundle` is passed. The proof is blob
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

**Built-in exclusions:** per-language vendor / build / `node_modules` directories are always skipped. Use `exclude_paths` for fixtures that must legitimately contain suppression annotations, rather than disabling the handler — see [Content-Blocker Path Exclusion](#content-blocker-path-exclusion-exclude_paths).

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
  transcript. The deny reason names only a position (`entry N of M in the secret word list`), which is meaningless without the gitignored file. Read
  that file, or ask the operator — do not try to guess what matched.

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

**Built-in exclusions:** `vendor/`, `node_modules/`, `tests/fixtures/`, `tests/assets/`, `__fixtures__/`. Use `exclude_paths` for fixtures of deliberately-broken code instead of disabling the handler.

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

**Example trigger:**

```
Write tool creating src/handlers/pre_tool_use/new_handler.py
(when tests/unit/handlers/pre_tool_use/test_new_handler.py does not exist)
```

**Options:**

| Option      | Type        | Default        | Description                                                                                                                                                                          |
| ----------- | ----------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `languages` | `list[str]` | all registered | Restrict TDD enforcement to specific languages. Unset or empty enforces EVERY registered language. Takes precedence over the project-wide `daemon.languages` list when both are set. |

**Config example:**

```yaml
handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      priority: 15
      options:
        languages: ["python", "typescript"]  # omit to enforce all 11
```

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

#### task_tdd_advisor

| Property       | Value              |
| -------------- | ------------------ |
| **Config key** | `task_tdd_advisor` |
| **Priority**   | 45                 |
| **Type**       | Advisory           |
| **Event**      | PreToolUse         |

**Description:** Advises on TDD workflow when the Task tool is used to spawn agents for implementation work. Detects keywords like "implement", "create handler", "add feature" and reminds about the Red/Green/Refactor cycle.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    task_tdd_advisor:
      enabled: true
      priority: 45
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

#### validate_plan_number

| Property       | Value                  |
| -------------- | ---------------------- |
| **Config key** | `validate_plan_number` |
| **Priority**   | 30                     |
| **Type**       | Blocking               |
| **Event**      | PreToolUse             |

**Description:** Validates plan folder numbering before directory creation to ensure sequential plan numbers. Prevents gaps or duplicates in the `CLAUDE/Plan/` numbering scheme.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    validate_plan_number:
      enabled: true
      priority: 30
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

**Fires when:** a Write or Edit targets a file named `PLAN.md` inside the configured plan directory (`plan_workflow.directory`, default `CLAUDE/Plan`).

**Enforcement mode:** honours `plan_workflow.qa.edit_mode` (`block` | `warn` | `off`, default `block`). In `block`, block-level findings on new material deny the tool call with the exact remediation; `warn` downgrades everything to advisory context; `off` disables the handler. Plans listed in `legacy_plan_allowlist` only ever advise.

**Block-level checks (new material):** a parseable `**Status**:` line must exist (`status-line-present`); the token must be one of Not Started, In Progress, Complete, Blocked, Cancelled, Superseded, Dormant (`status-enum-and-date`); the header must not contradict an all-ticked body (`header-body-coherence`); tasks must use the template grammar `- [ ] ⬜ **Task N.N**:` rather than ad-hoc markers (`task-grammar`). Advisory-level checks cover missing Created/Owner/Priority headers, a terminal status set while the folder is still in the plan root, edits to archived plans, and backticked `src/...` paths that no longer exist.

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
remediation always names two remedies -- relocate narrative into `JOURNAL/`, or
split an over-scoped plan -- and never suggests deleting content. See
[CLAUDE/PlanJournalling.md](../../CLAUDE/PlanJournalling.md) for the full
PLAN-vs-JOURNAL contract.

`extra_root_files` is an ADDITIVE allowlist layered on top of the built-in
accepted set (`README.md`, `CLAUDE.md`, `mkplan.bash`, `_TEMPLATE_.md`): list any
legitimately-placed non-plan file at the plan root here so the
`structure-archive-dirs` check does not report it as a stray file. Typical use is
a sourced shell library such as `_planlib.bash` shared by plan orchestrator
scripts. Matching is by exact filename; the default empty list is byte-identical
to prior behaviour.

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

**Invariants checked:** creating a plan folder ⇒ the same commit stages its README index row (`index-at-birth`) with a number from the git counter / `mkplan.bash` (`counter-sanity`, `no-new-collisions`); flipping a plan to Complete/Cancelled/Superseded ⇒ the same commit contains the `git mv` into the archive dir plus the README row and statistics update (`terminal-state-atomic`); every folder has a README row in the section matching its location and every row link resolves (`row-folder-bijection`, `stats-recount`); a commit claiming `Plan NNNNN` that stages src/test/config changes should also touch that plan's PLAN.md (`same-commit-plan-doc`), and plans are referenced as `Plan NNNNN:` (`plan-ref-format`).

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

#### plan_completion_advisor

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `plan_completion_advisor` |
| **Priority**   | 50                        |
| **Type**       | Advisory                  |
| **Event**      | PreToolUse                |

**Description:** Detects when a plan's PLAN.md status is being changed to "Complete" and reminds to follow the plan completion checklist: move to `Completed/` folder, update `README.md` index, and update plan statistics.

**Config example:**

```yaml
handlers:
  pre_tool_use:
    plan_completion_advisor:
      enabled: true
      priority: 50
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

### Advisory Handlers (Priority 60)

#### british_english

| Property       | Value             |
| -------------- | ----------------- |
| **Config key** | `british_english` |
| **Priority**   | 60                |
| **Type**       | Advisory          |
| **Event**      | PreToolUse        |

**Description:** Warns about American English spellings in content files (.md, .ejs, .html, .txt). Checks for common American spellings and suggests British equivalents (e.g. `color` to `colour`, `organize` to `organise`). Non-blocking -- allows the operation but adds a warning.

**Checked directories:** `private_html`, `docs`, `CLAUDE`

**Config example:**

```yaml
handlers:
  pre_tool_use:
    british_english:
      enabled: true
      priority: 60
```

---

## PostToolUse Handlers

These handlers run **after** a tool call completes. They analyse output and provide feedback.

#### bash_error_detector

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `bash_error_detector` |
| **Priority**   | 50                    |
| **Type**       | Advisory              |
| **Event**      | PostToolUse           |

**Description:** Detects errors and warnings in Bash command output. Provides feedback context when commands exit with errors or when output contains error/warning keywords. Non-terminal to allow execution to proceed while providing awareness.

**Config example:**

```yaml
handlers:
  post_tool_use:
    bash_error_detector:
      enabled: true
      priority: 50
```

---

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

#### validate_eslint_on_write

| Property       | Value                      |
| -------------- | -------------------------- |
| **Config key** | `validate_eslint_on_write` |
| **Priority**   | 10                         |
| **Type**       | Advisory                   |
| **Event**      | PostToolUse                |

**Description:** Runs ESLint validation on TypeScript/TSX files after they are written. Automatically checks for lint errors after file writes and reports issues. Skips files in `node_modules`, `dist`, `.build`, `coverage`, and `test-results` directories.

**Checked extensions:** `.ts`, `.tsx`

**Config example:**

```yaml
handlers:
  post_tool_use:
    validate_eslint_on_write:
      enabled: true
      priority: 10
```

---

## SessionStart Handlers

These handlers run when a new Claude Code session begins. They provide environment information and configuration checks.

#### yolo_container_detection

| Property       | Value                      |
| -------------- | -------------------------- |
| **Config key** | `yolo_container_detection` |
| **Priority**   | 40                         |
| **Type**       | Advisory                   |
| **Event**      | SessionStart               |

**Description:** Detects YOLO container environments (Docker, CI, etc.) using a multi-tier confidence scoring system. Provides informational context about the runtime environment to help Claude adapt its behaviour (e.g., relaxing safety checks in isolated containers).

**Config example:**

```yaml
handlers:
  session_start:
    yolo_container_detection:
      enabled: true
      priority: 40
```

---

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

#### plan_qa_sweep

| Property       | Value           |
| -------------- | --------------- |
| **Config key** | `plan_qa_sweep` |
| **Priority**   | 57              |
| **Type**       | Advisory        |
| **Event**      | SessionStart    |

**Description:** At the start of each new session, sweeps the whole plan directory with the plan QA check catalogue (index/folder bijection, number collisions, statistics recount, archive structure, status-vs-location coherence, staleness and dormancy) and injects ONE compact drift report as advisory context. Silent when the tree is clean; skipped on session resume.

**Fires when:** a new (non-resumed) session starts with `plan_workflow.qa.enabled` true and `sweep_mode: advise`. A configured plan directory that does not exist is itself reported as a structural finding.

**Enforcement mode:** honours `plan_workflow.qa.sweep_mode` (`advise` | `off`, default `advise`). The sweep never blocks -- it only reports drift for you to fix as plan housekeeping.

**Policy configuration:** shares the top-level `plan_workflow.qa` block documented under [`plan_qa_edit`](#plan_qa_edit) -- the archive dir names, `staleness_days`, and the legacy/collision allowlists all apply to the sweep.

**CLI:** the same catalogue runs against the HEAD tree with `.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep`, which exits 1 while findings remain (CI-able). Single-file lint is `plan-qa --lint <PLAN.md>` and the staged-commit check is `plan-qa --check-staged`; add `--json` to any of these for machine-readable output.

**Config example:**

```yaml
handlers:
  session_start:
    plan_qa_sweep:
      enabled: true
      priority: 57
```

---

## PreCompact Handlers

These handlers run before Claude Code compacts (summarises) the conversation to save context window space.

#### transcript_archiver

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `transcript_archiver` |
| **Priority**   | 10                    |
| **Type**       | Advisory              |
| **Event**      | PreCompact            |

**Description:** Archives the full conversation transcript to a timestamped file before compaction. Provides a historical record for debugging and audit purposes.

**Options:**

| Option                 | Type | Default | Description                                                                                                                                                       |
| ---------------------- | ---- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_archives`         | int  | `40`    | Retention cap (Plan 00181): after each write the `transcripts/` directory is pruned to the newest `max_archives` files. The just-written archive always survives. |
| `max_archive_age_days` | int  | `14`    | Retention cap (Plan 00181): archives older than this many days are pruned after each write, independent of `max_archives`.                                        |

Both caps apply together (a file is removed if it exceeds *either* the count or the age limit), bounding what was an unbounded `transcripts/` directory.

**Config example:**

```yaml
handlers:
  pre_compact:
    transcript_archiver:
      enabled: true
      priority: 10
      options:
        max_archives: 40
        max_archive_age_days: 14
```

---

## SessionEnd Handlers

#### cleanup

| Property       | Value      |
| -------------- | ---------- |
| **Config key** | `cleanup`  |
| **Priority**   | 100        |
| **Type**       | Advisory   |
| **Event**      | SessionEnd |

**Description:** Cleans up temporary hook-related files from the `untracked/temp` directory when a session ends.

**Config example:**

```yaml
handlers:
  session_end:
    cleanup:
      enabled: true
      priority: 100
```

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

#### task_completion_checker

| Property       | Value                     |
| -------------- | ------------------------- |
| **Config key** | `task_completion_checker` |
| **Priority**   | 50                        |
| **Type**       | Advisory                  |
| **Event**      | Stop                      |

**Description:** Reminds the agent to verify task completion before stopping. Provides a context reminder on all stop events to ensure tasks are properly completed.

**Config example:**

```yaml
handlers:
  stop:
    task_completion_checker:
      enabled: true
      priority: 50
```

---

#### hedging_language_detector

| Property       | Value                       |
| -------------- | --------------------------- |
| **Config key** | `hedging_language_detector` |
| **Priority**   | 30                          |
| **Type**       | Advisory                    |
| **Event**      | Stop                        |

**Description:** Detects hedging language in Claude's responses that signals guessing instead of researching. Scans the last assistant message for phrases like "if I recall", "IIRC", "should probably", "I'm not sure but", "I believe" and injects a warning telling the agent to verify with tools (Read, Grep, Glob) instead of guessing.

**Config example:**

```yaml
handlers:
  stop:
    hedging_language_detector:
      enabled: true
      priority: 30
```

---

## SubagentStop Handlers

These handlers run when a subagent (Task tool agent) completes.

#### subagent_completion_logger

| Property       | Value                        |
| -------------- | ---------------------------- |
| **Config key** | `subagent_completion_logger` |
| **Priority**   | 100                          |
| **Type**       | Advisory                     |
| **Event**      | SubagentStop                 |

**Description:** Logs subagent completion events to a JSONL file with timestamps for debugging and tracking.

**Options:**

| Option          | Type | Default           | Description                                                                                                                                                                                              |
| --------------- | ---- | ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_log_bytes` | int  | `5242880` (5 MiB) | Retention cap (Plan 00181): after each append the `subagent_completions.jsonl` log is front-truncated to below this size, keeping the newest whole lines. Bounds a previously unbounded append-only log. |

**Config example:**

```yaml
handlers:
  subagent_stop:
    subagent_completion_logger:
      enabled: true
      priority: 100
      options:
        max_log_bytes: 5242880
```

---

#### remind_prompt_library

| Property       | Value                   |
| -------------- | ----------------------- |
| **Config key** | `remind_prompt_library` |
| **Priority**   | 100                     |
| **Type**       | Advisory                |
| **Event**      | SubagentStop            |

**Description:** Reminds to capture successful prompts to a prompt library after every subagent completion. Helps build a library of effective prompts for reuse.

**Config example:**

```yaml
handlers:
  subagent_stop:
    remind_prompt_library:
      enabled: true
      priority: 100
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

## Notification Handlers

#### notification_logger

| Property       | Value                 |
| -------------- | --------------------- |
| **Config key** | `notification_logger` |
| **Priority**   | 100                   |
| **Type**       | Advisory              |
| **Event**      | Notification          |

**Description:** Logs all notification events to a JSONL file with timestamps for debugging and audit purposes.

**Options:**

| Option          | Type | Default           | Description                                                                                                                                                                                       |
| --------------- | ---- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_log_bytes` | int  | `5242880` (5 MiB) | Retention cap (Plan 00181): after each append the `notifications.jsonl` log is front-truncated to below this size, keeping the newest whole lines. Bounds a previously unbounded append-only log. |

**Config example:**

```yaml
handlers:
  notification:
    notification_logger:
      enabled: true
      priority: 100
      options:
        max_log_bytes: 5242880
```

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

#### usage_tracking

| Property       | Value            |
| -------------- | ---------------- |
| **Config key** | `usage_tracking` |
| **Priority**   | 15               |
| **Type**       | Advisory         |
| **Event**      | StatusLine       |

**Description:** Tracks and displays daily/weekly token usage percentages.

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

> **Note:** `stats_cache_reader` is a helper **module** used by `usage_tracking` to read `~/.claude/stats-cache.json`. It is not a handler, has no config key, and cannot be enabled, disabled or prioritised.

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
| `worktree_file_copy`           | PreToolUse        | 15       | cp/mv/rsync between worktrees                                        |
| `pipe_blocker`                 | PreToolUse        | 15       | Expensive commands piped to tail/head                                |
| `dangerous_permissions`        | PreToolUse        | 15       | chmod 777, chmod a+rwx                                               |
| `tdd_enforcement`              | PreToolUse        | 15       | Production code without tests (11 languages)                         |
| `root_recursion_guard`         | PreToolUse        | 16       | Recursive scans rooted at /, /home, $HOME, ...                       |
| `git_stash`                    | PreToolUse        | 20       | git stash creation (deny by default; configurable)                   |
| `qa_suppression`               | PreToolUse        | 30       | noqa, type: ignore, eslint-disable, nolint, ... (all langs)          |
| `plan_number_helper`           | PreToolUse        | 30       | Broken plan number discovery commands                                |
| `validate_plan_number`         | PreToolUse        | 30       | Invalid plan numbering                                               |
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

| Config Key                   | Event            | Priority | What It Does                           |
| ---------------------------- | ---------------- | -------- | -------------------------------------- |
| `daemon_restart_verifier`    | PreToolUse       | 10       | Suggests daemon restart before commits |
| `global_npm_advisor`         | PreToolUse       | 40       | Suggests npx over global installs      |
| `task_tdd_advisor`           | PreToolUse       | 45       | Reminds about TDD workflow             |
| `plan_workflow`              | PreToolUse       | 45       | Guidance for plan creation             |
| `plan_completion_advisor`    | PreToolUse       | 50       | Reminds about plan completion steps    |
| `web_search_year`            | PreToolUse       | 55       | Warns about outdated search years      |
| `british_english`            | PreToolUse       | 60       | Warns about American spellings         |
| `validate_eslint_on_write`   | PostToolUse      | 10       | Runs ESLint after .ts/.tsx writes      |
| `command_hints`              | PostToolUse      | 29       | Config-driven reminder after a command |
| `bash_error_detector`        | PostToolUse      | 50       | Detects errors in bash output          |
| `yolo_container_detection`   | SessionStart     | 40       | Detects container environments         |
| `optimal_config_checker`     | SessionStart     | 52       | Audits Claude Code settings            |
| `git_filemode_checker`       | SessionStart     | 53       | Warns when core.fileMode=false         |
| `suggest_status_line`        | SessionStart     | 55       | Suggests status line setup             |
| `version_check`              | SessionStart     | 55       | Checks for daemon updates              |
| `plan_qa_sweep`              | SessionStart     | 57       | Reports plan-tree drift once a session |
| `transcript_archiver`        | PreCompact       | 10       | Archives transcripts                   |
| `git_context_injector`       | UserPromptSubmit | 20       | Injects git status context             |
| `hedging_language_detector`  | Stop             | 30       | Detects guessing language              |
| `task_completion_checker`    | Stop             | 50       | Reminds about task completion          |
| `remind_prompt_library`      | SubagentStop     | 100      | Reminds about prompt library           |
| `subagent_completion_logger` | SubagentStop     | 100      | Logs subagent completions              |
| `notification_logger`        | Notification     | 100      | Logs notifications                     |
| `cleanup`                    | SessionEnd       | 100      | Cleans up temp files                   |

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

Priority determines execution order. Lower numbers run first.

| Range | Category        | Examples                                            |
| ----- | --------------- | --------------------------------------------------- |
| 5     | Test            | hello_world (disabled by default)                   |
| 10-20 | Safety          | destructive_git, sed_blocker, pip_break_system      |
| 25-35 | Code Quality    | qa_suppression, lint_on_edit, markdown_organization |
| 36-55 | Workflow        | lsp_enforcement, gh_issue_comments, npm_command     |
| 56-60 | Advisory        | british_english, dismissive_language_detector       |
| 100   | Logging/Cleanup | notification_logger, cleanup                        |

When two handlers have the same priority, they run in registration order.
