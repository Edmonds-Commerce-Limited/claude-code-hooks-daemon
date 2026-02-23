# Handler Reference

Complete reference for all built-in handlers in the Claude Code Hooks Daemon. Each handler intercepts specific Claude Code events and either blocks dangerous operations or provides advisory context.

## How Handlers Work

Handlers run in **priority order** (lower number runs first). Each handler has two key methods:

- **matches()** -- Decides whether this handler should activate for the current event
- **handle()** -- Executes the handler logic and returns a decision (allow, deny, or context)

Handlers are either **blocking** (terminal) or **advisory** (non-terminal):

- **Blocking handlers** stop the dispatch chain and return immediately (deny or allow)
- **Advisory handlers** add context or guidance but allow the chain to continue

---

## PreToolUse Handlers

These handlers run **before** Claude Code executes a tool call. They can block dangerous operations or inject advisory context.

### Safety Handlers (Priority 10-23)

Safety handlers protect against destructive or dangerous operations. Most are blocking.

#### destructive_git

| Property | Value |
|----------|-------|
| **Config key** | `destructive_git` |
| **Priority** | 10 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks git commands that permanently destroy data with no recovery possible. Protects against accidental data loss from force pushes, hard resets, and other destructive operations.

**Blocked commands:**
- `git reset --hard` -- destroys all uncommitted changes
- `git clean -f` -- permanently deletes untracked files
- `git checkout .` -- discards all working tree changes
- `git checkout -- <file>` -- discards local changes to specific files
- `git restore <file>` -- discards working tree changes (allows `--staged`)
- `git stash drop` / `git stash clear` -- permanently destroys stashed changes
- `git push --force` -- overwrites remote history

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

| Property | Value |
|----------|-------|
| **Config key** | `sed_blocker` |
| **Priority** | 10 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks `sed` command usage. Claude frequently gets sed syntax wrong, which can cause large-scale file corruption, especially with `find -exec sed`. The Edit tool is the safe alternative for file modifications.

**What it blocks (strict mode, default):**
- Bash commands containing `sed` (direct execution)
- Shell scripts (.sh/.bash) being written that contain `sed`

**What it allows:**
- Markdown files mentioning sed (documentation)
- Git commit messages mentioning sed
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
      priority: 11
```

**Options:**

| Option | Values | Default | Description |
|--------|--------|---------|-------------|
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

| Property | Value |
|----------|-------|
| **Config key** | `absolute_path` |
| **Priority** | 12 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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

#### worktree_file_copy

| Property | Value |
|----------|-------|
| **Config key** | `worktree_file_copy` |
| **Priority** | 15 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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

| Property | Value |
|----------|-------|
| **Config key** | `curl_pipe_shell` |
| **Priority** | 16 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 16
```

---

#### pipe_blocker

| Property | Value |
|----------|-------|
| **Config key** | `pipe_blocker` |
| **Priority** | 17 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 17
```

---

#### dangerous_permissions

| Property | Value |
|----------|-------|
| **Config key** | `dangerous_permissions` |
| **Priority** | 18 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 18
```

---

#### git_stash

| Property | Value |
|----------|-------|
| **Config key** | `git_stash` |
| **Priority** | 19 |
| **Type** | Blocking (deny mode) or Advisory (warn mode) |
| **Event** | PreToolUse |

**Description:** Warns about or blocks git stash creation commands. Stashes can be lost, forgotten, or accidentally dropped. Supports two modes configurable via handler options.

**Modes:**
- `warn` (default) -- Allows with advisory warning suggesting alternatives
- `deny` -- Hard blocks with no exceptions

**Allows:** `git stash pop`, `git stash apply`, `git stash list`, `git stash show` (recovery/query operations)

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
      priority: 19
      options:
        mode: "warn"  # or "deny"
```

---

#### lock_file_edit_blocker

| Property | Value |
|----------|-------|
| **Config key** | `lock_file_edit_blocker` |
| **Priority** | 20 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 20
```

---

#### pip_break_system

| Property | Value |
|----------|-------|
| **Config key** | `pip_break_system` |
| **Priority** | 21 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 21
```

---

#### sudo_pip

| Property | Value |
|----------|-------|
| **Config key** | `sudo_pip` |
| **Priority** | 22 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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
      priority: 22
```

---

#### daemon_restart_verifier

| Property | Value |
|----------|-------|
| **Config key** | `daemon_restart_verifier` |
| **Priority** | 23 |
| **Type** | Advisory |
| **Event** | PreToolUse |

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
      priority: 23
```

---

### Code Quality Handlers (Priority 26-35)

Code quality handlers prevent QA suppression comments and enforce development practices.

#### python_qa_suppression_blocker

| Property | Value |
|----------|-------|
| **Config key** | `python_qa_suppression_blocker` |
| **Priority** | 26 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks QA suppression comments in Python code written via Write or Edit tools. Prevents adding comments like `# noqa`, `# type: ignore`, `# pragma: no cover`, and `# pylint: disable` that hide code quality issues instead of fixing them.

**Example trigger:**
```python
x = some_func()  # type: ignore
```

**Config example:**
```yaml
handlers:
  pre_tool_use:
    python_qa_suppression_blocker:
      enabled: true
      priority: 26
```

---

#### php_qa_suppression_blocker

| Property | Value |
|----------|-------|
| **Config key** | `php_qa_suppression_blocker` |
| **Priority** | 27 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks QA suppression comments in PHP code. Prevents adding comments like `@phpstan-ignore`, `@codeCoverageIgnore`, `@SuppressWarnings`, and similar annotations that hide code quality issues.

**Example trigger:**
```php
/** @phpstan-ignore-next-line */
```

**Config example:**
```yaml
handlers:
  pre_tool_use:
    php_qa_suppression_blocker:
      enabled: true
      priority: 27
```

---

#### go_qa_suppression_blocker

| Property | Value |
|----------|-------|
| **Config key** | `go_qa_suppression_blocker` |
| **Priority** | 28 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks QA suppression comments in Go code. Prevents adding comments like `//nolint`, `//go:nosplit`, and similar directives that bypass linting and static analysis.

**Example trigger:**
```go
//nolint:errcheck
```

**Config example:**
```yaml
handlers:
  pre_tool_use:
    go_qa_suppression_blocker:
      enabled: true
      priority: 28
```

---

#### eslint_disable

| Property | Value |
|----------|-------|
| **Config key** | `eslint_disable` |
| **Priority** | 30 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks ESLint and TypeScript suppression comments in JavaScript/TypeScript files written via Write or Edit tools. Prevents `eslint-disable`, `@ts-ignore`, `@ts-nocheck`, and `@ts-expect-error` comments.

**Checked file extensions:** `.ts`, `.tsx`, `.js`, `.jsx`

**Example trigger:**
```typescript
// eslint-disable-next-line no-unused-vars
```

**Config example:**
```yaml
handlers:
  pre_tool_use:
    eslint_disable:
      enabled: true
      priority: 30
```

---

#### tdd_enforcement

| Property | Value |
|----------|-------|
| **Config key** | `tdd_enforcement` |
| **Priority** | 35 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Enforces test-driven development by blocking Write operations to production Python files (in `src/` or `handlers/` directories) when no corresponding test file exists. Ensures tests are written before implementation code.

**Excludes:** `__init__.py` files, test files, files in `tests/` directories.

**Example trigger:**
```
Write tool creating src/handlers/pre_tool_use/new_handler.py
(when tests/handlers/pre_tool_use/test_new_handler.py does not exist)
```

**Config example:**
```yaml
handlers:
  pre_tool_use:
    tdd_enforcement:
      enabled: true
      priority: 35
```

---

### Workflow Handlers (Priority 33-55)

Workflow handlers enforce development practices, provide guidance, and manage project structure.

#### plan_number_helper

| Property | Value |
|----------|-------|
| **Config key** | `plan_number_helper` |
| **Priority** | 33 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Detects bash commands that attempt to discover plan numbers (e.g., `ls -d CLAUDE/Plan/0*`) and blocks them, injecting the correct next plan number instead. Prevents broken bash glob patterns from returning incorrect plan numbers.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    plan_number_helper:
      enabled: true
      priority: 33
      options:
        track_plans_in_project: "CLAUDE/Plan"
```

---

#### task_tdd_advisor

| Property | Value |
|----------|-------|
| **Config key** | `task_tdd_advisor` |
| **Priority** | 36 |
| **Type** | Advisory |
| **Event** | PreToolUse |

**Description:** Advises on TDD workflow when the Task tool is used to spawn agents for implementation work. Detects keywords like "implement", "create handler", "add feature" and reminds about the Red/Green/Refactor cycle.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    task_tdd_advisor:
      enabled: true
      priority: 36
```

---

#### gh_issue_comments

| Property | Value |
|----------|-------|
| **Config key** | `gh_issue_comments` |
| **Priority** | 40 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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

#### validate_plan_number

| Property | Value |
|----------|-------|
| **Config key** | `validate_plan_number` |
| **Priority** | 41 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Validates plan folder numbering before directory creation to ensure sequential plan numbers. Prevents gaps or duplicates in the `CLAUDE/Plan/` numbering scheme.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    validate_plan_number:
      enabled: true
      priority: 41
```

---

#### global_npm_advisor

| Property | Value |
|----------|-------|
| **Config key** | `global_npm_advisor` |
| **Priority** | 42 |
| **Type** | Advisory |
| **Event** | PreToolUse |

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
      priority: 42
```

---

#### plan_time_estimates

| Property | Value |
|----------|-------|
| **Config key** | `plan_time_estimates` |
| **Priority** | 45 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Blocks time estimates in plan documents. Detects patterns like "Estimated Effort: 2 hours", "Target Completion: 2026-01-15" and prevents them from being written to plan files. Time estimates from LLMs are unreliable.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    plan_time_estimates:
      enabled: true
      priority: 45
```

---

#### plan_workflow

| Property | Value |
|----------|-------|
| **Config key** | `plan_workflow` |
| **Priority** | 46 |
| **Type** | Advisory |
| **Event** | PreToolUse |

**Description:** Provides guidance when creating plan files in the `CLAUDE/Plan/` directory. Reminds about plan structure, templates, and workflow standards.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    plan_workflow:
      enabled: true
      priority: 46
```

---

#### plan_completion_advisor

| Property | Value |
|----------|-------|
| **Config key** | `plan_completion_advisor` |
| **Priority** | 48 |
| **Type** | Advisory |
| **Event** | PreToolUse |

**Description:** Detects when a plan's PLAN.md status is being changed to "Complete" and reminds to follow the plan completion checklist: move to `Completed/` folder, update `README.md` index, and update plan statistics.

**Config example:**
```yaml
handlers:
  pre_tool_use:
    plan_completion_advisor:
      enabled: true
      priority: 48
```

---

#### npm_command

| Property | Value |
|----------|-------|
| **Config key** | `npm_command` |
| **Priority** | 49 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Description:** Enforces the use of `llm:` prefixed npm script commands and blocks direct `npx` tool usage. Maps common npm commands to their `llm:` equivalents (e.g., `npm run build` should be `npm run llm:build`).

**Config example:**
```yaml
handlers:
  pre_tool_use:
    npm_command:
      enabled: true
      priority: 49
```

---

#### markdown_organization

| Property | Value |
|----------|-------|
| **Config key** | `markdown_organization` |
| **Priority** | 50 |
| **Type** | Blocking |
| **Event** | PreToolUse |

**Full documentation:** [`docs/guides/handlers/markdown_organization.md`](handlers/markdown_organization.md)

Enforces markdown file organization rules, plan tracking, custom allowed paths, and monorepo support. See per-handler docs for all options, monorepo interaction, and examples.

---

#### validate_instruction_content

| Property | Value |
|----------|-------|
| **Config key** | `validate_instruction_content` |
| **Priority** | 50 |
| **Type** | Blocking |
| **Event** | PreToolUse |

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

| Property | Value |
|----------|-------|
| **Config key** | `web_search_year` |
| **Priority** | 55 |
| **Type** | Advisory |
| **Event** | PreToolUse |

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

| Property | Value |
|----------|-------|
| **Config key** | `british_english` |
| **Priority** | 60 |
| **Type** | Advisory |
| **Event** | PreToolUse |

**Description:** Warns about American English spellings in content files (.md, .ejs, .html, .txt). Checks for common American spellings and suggests British equivalents (e.g., "color" to "colour", "organize" to "organise"). Non-blocking -- allows the operation but adds a warning.

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

| Property | Value |
|----------|-------|
| **Config key** | `bash_error_detector` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | PostToolUse |

**Description:** Detects errors and warnings in Bash command output. Provides feedback context when commands exit with errors or when output contains error/warning keywords. Non-terminal to allow execution to proceed while providing awareness.

**Config example:**
```yaml
handlers:
  post_tool_use:
    bash_error_detector:
      enabled: true
      priority: 10
```

---

#### validate_eslint_on_write

| Property | Value |
|----------|-------|
| **Config key** | `validate_eslint_on_write` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | PostToolUse |

**Description:** Runs ESLint validation on TypeScript/TSX files after they are written. Automatically checks for lint errors after file writes and reports issues. Skips files in `node_modules`, `dist`, `.build`, `coverage`, and `test-results` directories.

**Checked extensions:** `.ts`, `.tsx`

**Config example:**
```yaml
handlers:
  post_tool_use:
    validate_eslint_on_write:
      enabled: true
      priority: 20
```

---

## SessionStart Handlers

These handlers run when a new Claude Code session begins. They provide environment information and configuration checks.

#### yolo_container_detection

| Property | Value |
|----------|-------|
| **Config key** | `yolo_container_detection` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | SessionStart |

**Description:** Detects YOLO container environments (Docker, CI, etc.) using a multi-tier confidence scoring system. Provides informational context about the runtime environment to help Claude adapt its behaviour (e.g., relaxing safety checks in isolated containers).

**Config example:**
```yaml
handlers:
  session_start:
    yolo_container_detection:
      enabled: true
      priority: 10
```

---

#### optimal_config_checker

| Property | Value |
|----------|-------|
| **Config key** | `optimal_config_checker` |
| **Priority** | 52 |
| **Type** | Advisory |
| **Event** | SessionStart |

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

#### suggest_status_line

| Property | Value |
|----------|-------|
| **Config key** | `suggest_status_line` |
| **Priority** | 55 |
| **Type** | Advisory |
| **Event** | SessionStart |

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

| Property | Value |
|----------|-------|
| **Config key** | `version_check` |
| **Priority** | 56 |
| **Type** | Advisory |
| **Event** | SessionStart |

**Description:** Checks if the daemon is up-to-date with the latest GitHub release on new sessions. Uses a 24-hour cache to avoid excessive git operations. Only runs on new sessions (not resumes).

**Config example:**
```yaml
handlers:
  session_start:
    version_check:
      enabled: true
      priority: 56
```

---

#### workflow_state_restoration

| Property | Value |
|----------|-------|
| **Config key** | `workflow_state_restoration` |
| **Priority** | 60 |
| **Type** | Advisory |
| **Event** | SessionStart |

**Description:** Restores workflow state after conversation compaction. Reads saved workflow state from timestamped files and provides guidance to force re-reading of workflow documentation, ensuring continuity across compacted sessions.

**Config example:**
```yaml
handlers:
  session_start:
    workflow_state_restoration:
      enabled: true
      priority: 60
```

---

## PreCompact Handlers

These handlers run before Claude Code compacts (summarises) the conversation to save context window space.

#### transcript_archiver

| Property | Value |
|----------|-------|
| **Config key** | `transcript_archiver` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | PreCompact |

**Description:** Archives the full conversation transcript to a timestamped file before compaction. Provides a historical record for debugging and audit purposes.

**Config example:**
```yaml
handlers:
  pre_compact:
    transcript_archiver:
      enabled: true
      priority: 10
```

---

#### workflow_state_pre_compact

| Property | Value |
|----------|-------|
| **Config key** | `workflow_state_pre_compact` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | PreCompact |

**Description:** Detects active formal workflows and saves their state to a timestamped file before compaction. Works with `workflow_state_restoration` to maintain workflow continuity across compacted sessions.

**Config example:**
```yaml
handlers:
  pre_compact:
    workflow_state_pre_compact:
      enabled: true
      priority: 20
```

---

## SessionEnd Handlers

#### cleanup

| Property | Value |
|----------|-------|
| **Config key** | `cleanup` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | SessionEnd |

**Description:** Cleans up temporary hook-related files from the `untracked/temp` directory when a session ends.

**Config example:**
```yaml
handlers:
  session_end:
    cleanup:
      enabled: true
      priority: 10
```

---

## Stop Handlers

These handlers run when Claude stops generating a response.

#### auto_continue_stop

| Property | Value |
|----------|-------|
| **Config key** | `auto_continue_stop` |
| **Priority** | 10 |
| **Type** | Blocking |
| **Event** | Stop |

**Description:** Enables true auto-continue without user input. Reads the conversation transcript to detect if Claude's last message was a confirmation question ("Would you like me to continue?", "Should I proceed?", etc.) and blocks the stop with an auto-continue instruction. Includes loop prevention via `stop_hook_active` check.

**Config example:**
```yaml
handlers:
  stop:
    auto_continue_stop:
      enabled: true
      priority: 10
```

---

#### task_completion_checker

| Property | Value |
|----------|-------|
| **Config key** | `task_completion_checker` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | Stop |

**Description:** Reminds the agent to verify task completion before stopping. Provides a context reminder on all stop events to ensure tasks are properly completed.

**Config example:**
```yaml
handlers:
  stop:
    task_completion_checker:
      enabled: true
      priority: 20
```

---

#### hedging_language_detector

| Property | Value |
|----------|-------|
| **Config key** | `hedging_language_detector` |
| **Priority** | 30 |
| **Type** | Advisory |
| **Event** | Stop |

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

| Property | Value |
|----------|-------|
| **Config key** | `subagent_completion_logger` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | SubagentStop |

**Description:** Logs subagent completion events to a JSONL file with timestamps for debugging and tracking.

**Config example:**
```yaml
handlers:
  subagent_stop:
    subagent_completion_logger:
      enabled: true
      priority: 10
```

---

#### remind_prompt_library

| Property | Value |
|----------|-------|
| **Config key** | `remind_prompt_library` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | SubagentStop |

**Description:** Reminds to capture successful prompts to a prompt library after every subagent completion. Helps build a library of effective prompts for reuse.

**Config example:**
```yaml
handlers:
  subagent_stop:
    remind_prompt_library:
      enabled: true
      priority: 20
```

---

## UserPromptSubmit Handlers

These handlers run when the user submits a prompt.

#### git_context_injector

| Property | Value |
|----------|-------|
| **Config key** | `git_context_injector` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | UserPromptSubmit |

**Description:** Injects current git status (branch, uncommitted changes) as context when the user submits a prompt. Helps Claude make better decisions by being aware of the repository state.

**Config example:**
```yaml
handlers:
  user_prompt_submit:
    git_context_injector:
      enabled: true
      priority: 10
```

---

## Notification Handlers

#### notification_logger

| Property | Value |
|----------|-------|
| **Config key** | `notification_logger` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | Notification |

**Description:** Logs all notification events to a JSONL file with timestamps for debugging and audit purposes.

**Config example:**
```yaml
handlers:
  notification:
    notification_logger:
      enabled: true
      priority: 10
```

---

## PermissionRequest Handlers

#### auto_approve_reads

| Property | Value |
|----------|-------|
| **Config key** | `auto_approve_reads` |
| **Priority** | 10 |
| **Type** | Blocking |
| **Event** | PermissionRequest |

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

| Property | Value |
|----------|-------|
| **Config key** | `git_repo_name` |
| **Priority** | 3 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Shows the git repository name at the start of the status line. Cached for performance.

---

#### account_display

| Property | Value |
|----------|-------|
| **Config key** | `account_display` |
| **Priority** | 5 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Reads and displays the Claude account username from `~/.claude/.last-launch.conf`.

---

#### model_context

| Property | Value |
|----------|-------|
| **Config key** | `model_context` |
| **Priority** | 10 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Formats a colour-coded model name (blue for Haiku, green for Sonnet, orange for Opus) with effort level, plus a colour-coded context window usage percentage using quarter-circle icons.

---

#### usage_tracking

| Property | Value |
|----------|-------|
| **Config key** | `usage_tracking` |
| **Priority** | 15 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Tracks and displays daily/weekly token usage percentages.

---

#### git_branch

| Property | Value |
|----------|-------|
| **Config key** | `git_branch` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Shows the current git branch name in the status line.

---

#### thinking_mode

| Property | Value |
|----------|-------|
| **Config key** | `thinking_mode` |
| **Priority** | 25 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Shows the current thinking mode (On/Off) and effort level from `~/.claude/settings.json`.

---

#### daemon_stats

| Property | Value |
|----------|-------|
| **Config key** | `daemon_stats` |
| **Priority** | 30 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Shows daemon uptime, memory usage, log level, and error count in the status line.

---

#### stats_cache_reader

| Property | Value |
|----------|-------|
| **Config key** | `stats_cache_reader` |
| **Priority** | 20 |
| **Type** | Advisory |
| **Event** | StatusLine |

**Description:** Utility handler for reading `~/.claude/stats-cache.json`, used by the `usage_tracking` handler.

---

## Quick Reference Table

### All Blocking Handlers

| Config Key | Event | Priority | What It Blocks |
|------------|-------|----------|----------------|
| `destructive_git` | PreToolUse | 10 | git reset --hard, clean -f, push --force, etc. |
| `sed_blocker` | PreToolUse | 10 | All sed commands |
| `absolute_path` | PreToolUse | 12 | Relative paths in Read/Write/Edit |
| `worktree_file_copy` | PreToolUse | 15 | cp/mv/rsync between worktrees |
| `curl_pipe_shell` | PreToolUse | 16 | curl/wget piped to bash/sh |
| `pipe_blocker` | PreToolUse | 17 | Expensive commands piped to tail/head |
| `dangerous_permissions` | PreToolUse | 18 | chmod 777, chmod a+rwx |
| `git_stash` | PreToolUse | 19 | git stash creation (configurable) |
| `lock_file_edit_blocker` | PreToolUse | 20 | Direct editing of lock files |
| `pip_break_system` | PreToolUse | 21 | pip --break-system-packages |
| `sudo_pip` | PreToolUse | 22 | sudo pip install |
| `python_qa_suppression_blocker` | PreToolUse | 26 | # noqa, # type: ignore, etc. |
| `php_qa_suppression_blocker` | PreToolUse | 27 | @phpstan-ignore, etc. |
| `go_qa_suppression_blocker` | PreToolUse | 28 | //nolint, etc. |
| `eslint_disable` | PreToolUse | 30 | eslint-disable, @ts-ignore, etc. |
| `plan_number_helper` | PreToolUse | 33 | Broken plan number discovery commands |
| `tdd_enforcement` | PreToolUse | 35 | Production code without tests |
| `gh_issue_comments` | PreToolUse | 40 | gh issue view without --comments |
| `validate_plan_number` | PreToolUse | 41 | Invalid plan numbering |
| `plan_time_estimates` | PreToolUse | 45 | Time estimates in plan docs |
| `npm_command` | PreToolUse | 49 | Non-llm: npm commands |
| `markdown_organization` | PreToolUse | 50 | Disorganised markdown files |
| `validate_instruction_content` | PreToolUse | 50 | Ephemeral content in CLAUDE.md |
| `auto_continue_stop` | Stop | 10 | Stops after confirmation questions |
| `auto_approve_reads` | PermissionRequest | 10 | (Approves) file read permissions |

### All Advisory Handlers

| Config Key | Event | Priority | What It Does |
|------------|-------|----------|--------------|
| `daemon_restart_verifier` | PreToolUse | 23 | Suggests daemon restart before commits |
| `task_tdd_advisor` | PreToolUse | 36 | Reminds about TDD workflow |
| `global_npm_advisor` | PreToolUse | 42 | Suggests npx over global installs |
| `plan_workflow` | PreToolUse | 46 | Guidance for plan creation |
| `plan_completion_advisor` | PreToolUse | 48 | Reminds about plan completion steps |
| `web_search_year` | PreToolUse | 55 | Warns about outdated search years |
| `british_english` | PreToolUse | 60 | Warns about American spellings |
| `bash_error_detector` | PostToolUse | 10 | Detects errors in bash output |
| `validate_eslint_on_write` | PostToolUse | 20 | Runs ESLint after .ts/.tsx writes |
| `yolo_container_detection` | SessionStart | 10 | Detects container environments |
| `optimal_config_checker` | SessionStart | 52 | Audits Claude Code settings |
| `suggest_status_line` | SessionStart | 55 | Suggests status line setup |
| `version_check` | SessionStart | 56 | Checks for daemon updates |
| `workflow_state_restoration` | SessionStart | 60 | Restores workflow state |
| `transcript_archiver` | PreCompact | 10 | Archives transcripts |
| `workflow_state_pre_compact` | PreCompact | 20 | Saves workflow state |
| `cleanup` | SessionEnd | 10 | Cleans up temp files |
| `task_completion_checker` | Stop | 20 | Reminds about task completion |
| `hedging_language_detector` | Stop | 30 | Detects guessing language |
| `subagent_completion_logger` | SubagentStop | 10 | Logs subagent completions |
| `remind_prompt_library` | SubagentStop | 20 | Reminds about prompt library |
| `git_context_injector` | UserPromptSubmit | 10 | Injects git status context |
| `notification_logger` | Notification | 10 | Logs notifications |

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

| Range | Category | Examples |
|-------|----------|----------|
| 5 | Test | hello_world (disabled by default) |
| 10-23 | Safety | destructive_git, sed_blocker, pip_break_system |
| 25-35 | Code Quality | eslint_disable, tdd_enforcement |
| 36-55 | Workflow | gh_issue_comments, npm_command, markdown_organization |
| 56-60 | Advisory | british_english |
| 100 | Logging/Cleanup | notification_logger, cleanup |

When two handlers have the same priority, they run in registration order.
