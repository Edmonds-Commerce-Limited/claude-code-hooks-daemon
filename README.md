# Claude Code Hooks Daemon

![Version](https://img.shields.io/badge/version-2.13.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-5663%20passing-success)
![Coverage](https://img.shields.io/badge/coverage-95%25%20required-success)

High-performance daemon for Claude Code hooks using Unix socket IPC and front controller architecture.

---

## Installation & Updates

**IMPORTANT: If you are installing or updating this daemon, read these docs first:**

- **INSTALL**: https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md
- **UPDATE**: https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md

**Quick Install (AI-Assisted - Recommended):**
```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md -o /tmp/LLM-INSTALL.md
Then read /tmp/LLM-INSTALL.md and follow the instructions exactly.
```

**Quick Update (AI-Assisted - Recommended):**
```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md -o /tmp/LLM-UPDATE.md
Then read /tmp/LLM-UPDATE.md and follow the instructions exactly.
```

---

## Overview

A daemon-based hooks system that eliminates process spawn overhead (~21ms) with sub-millisecond response times after warmup.

**Key Features:**
- **Sub-millisecond response times** after warmup (20x faster than process spawn)
- **Lazy startup** - Daemon starts on first hook call
- **Auto-shutdown** - Exits after 10 minutes of inactivity
- **Multi-project support** - Unique daemon per project directory
- **48 production handlers** across 10 event types (11 language strategies)
- **5285 tests** with 95% coverage requirement
- **Type-safe** - Full MyPy strict mode compliance
- **Project-level handlers** - First-class support for per-project custom handlers with auto-discovery
- **Deterministic validation** - Fast pattern matching and rule enforcement

### Architectural Principle: Deterministic vs Agent-Based Hooks

**The hooks daemon is designed for deterministic validation only.** Complex evaluation requiring reasoning should use Claude Code's native agent-based hooks.

| Use Hooks Daemon For | Use Claude Code Agent Hooks For |
|---------------------|--------------------------------|
| ✅ Pattern matching (regex, string checks) | ✅ Workflow compliance validation |
| ✅ Fast synchronous validation | ✅ Context analysis (transcripts, git state) |
| ✅ Reusable safety rules | ✅ Multi-turn investigation |
| ✅ Deterministic logic | ✅ Reasoning and judgment calls |

**Examples:**
- **Daemon**: Block `sed -i`, validate absolute paths, detect QA suppressions
- **Agent Hooks**: Verify release workflow, check architectural compliance, validate planning process

**Configuration:**
- Daemon handlers: `.claude/hooks-daemon.yaml`
- Agent hooks: `.claude/hooks.json` (project-level)

**See [ARCHITECTURE.md](./CLAUDE/ARCHITECTURE.md) for complete guidance.**

---

## Installation

### Quick Start - AI-Assisted (Recommended)

**Copy this into Claude Code:**

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md -o /tmp/LLM-INSTALL.md
Then read /tmp/LLM-INSTALL.md and follow the instructions exactly.
```

**Installation time:** ~30 seconds with AI assistance

The AI-assisted installation will:
1. Clone the daemon to `.claude/hooks-daemon/`
2. Create a self-contained virtual environment
3. Install all dependencies
4. Run the automated installer
5. Verify the installation with tests

### Manual Installation

From your project root:

```bash
# Clone daemon to .claude/hooks-daemon/
mkdir -p .claude
cd .claude
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon

# Checkout latest stable release (recommended)
git fetch --tags
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
git checkout "$LATEST_TAG"
echo "Using version: $LATEST_TAG"

# Create self-contained virtual environment
python3 -m venv untracked/venv

# Install daemon dependencies into venv
untracked/venv/bin/pip install -e .

# Run automated installer
untracked/venv/bin/python install.py

# Return to project root
cd ../..
```

The installer creates:
1. `.claude/init.sh` - Daemon lifecycle functions (start/stop/ensure_daemon)
2. `.claude/hooks/*` - Forwarder scripts (route hook calls to daemon)
3. `.claude/settings.json` - Hook registration for Claude Code
4. `.claude/hooks-daemon.yaml` - Handler and daemon configuration

**⚠️ CRITICAL:** You MUST create `.claude/.gitignore` after installation (see Git Integration section below). The installer will display the required content.

---

## Updating

### Quick Update - AI-Assisted (Recommended)

**Copy this into Claude Code:**

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md -o /tmp/LLM-UPDATE.md
Then read /tmp/LLM-UPDATE.md and follow the instructions exactly.
```

**Update time:** ~15 seconds with AI assistance

The AI-assisted update will:
1. Check your current version
2. Fetch and checkout the latest release
3. Update dependencies
4. Check for required config changes
5. Verify the update

### Manual Update

From your project root:

```bash
cd .claude/hooks-daemon

# Backup config
cp ../hooks-daemon.yaml ../hooks-daemon.yaml.backup

# Fetch and checkout latest
git fetch --tags
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
git checkout "$LATEST_TAG"
echo "Updated to: $LATEST_TAG"

# Update dependencies
untracked/venv/bin/pip install -e .

# Restart daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart

cd ../..
```

### Version-Specific Documentation

- **Release Notes**: See `RELEASES/` directory for version-specific changelogs
- **Upgrade Guides**: See `CLAUDE/UPGRADES/` directory for migration instructions

---

## Documentation

### Core Concepts
- [Plan Workflow](docs/PLAN_WORKFLOW.md) - Structured planning system with handler support
- [Handler Development](CLAUDE/HANDLER_DEVELOPMENT.md) - Creating custom handlers
- [Architecture](CLAUDE/ARCHITECTURE.md) - System design and components

### Installation & Updates
- [Installation Guide (AI-Optimized)](CLAUDE/LLM-INSTALL.md) - Complete installation instructions
- [Update Guide (AI-Optimized)](CLAUDE/LLM-UPDATE.md) - Upgrade instructions with breaking changes
- [Configuration Guide](CLAUDE/ARCHITECTURE.md#configuration-system) - Handler and daemon configuration

### Development
- [Contributing](CONTRIBUTING.md) - Contribution guidelines and QA requirements
- [Releasing](CLAUDE/development/RELEASING.md) - Release process using `/release` skill
- [Debugging Hooks](CLAUDE/DEBUGGING_HOOKS.md) - Hook debugging workflow
- [QA Pipeline](CLAUDE/development/QA.md) - Quality assurance automation

### Troubleshooting
- [Bug Reporting](BUG_REPORTING.md) - Debug info generation and issue reporting

---

## Git Integration

**⚠️ CRITICAL:** You MUST create `.claude/.gitignore` to prevent committing generated files.

### Required: Create `.claude/.gitignore`

**The installer will display this content** - copy it to `.claude/.gitignore`:

**Template source (single source of truth):**
https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/blob/main/.claude/.gitignore

Or copy directly:
```bash
cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore
```

### What Gets Tracked

With `.claude/.gitignore` in place, these files are tracked in git:

```
.claude/
├── .gitignore           # ✅ COMMIT (you create this)
├── settings.json        # ✅ COMMIT (project-wide hook configuration)
├── hooks-daemon.yaml    # ✅ COMMIT (handler settings)
├── init.sh              # ✅ COMMIT (daemon lifecycle functions)
└── hooks/               # ✅ COMMIT (hook forwarder scripts)
```

**Benefits:**
- ✅ Team shares same hook configuration
- ✅ Consistent code quality standards
- ✅ New team members get hooks automatically

### What Gets Excluded

The `.gitignore` automatically excludes:
- `hooks-daemon/` - Daemon installation (users install it themselves)
- `*.bak*` - Backup files
- `*.sock`, `*.pid` - Runtime files

### Root .gitignore Setup

**If your root `.gitignore` contains `.claude/`, remove it:**

```diff
# .gitignore (root)
- .claude/
```

The installer will warn if it detects this pattern.

---

## Current Version: 2.9.0

**Latest Changes (v2.9.0):**
- ✅ **Strategy Pattern Architecture** - Unified language-aware handlers with 11 language strategies (Plan 00045)
- ✅ **Massive Code Deduplication** - 4 per-language handlers replaced by 1 strategy-based handler
- ✅ **11 Language Support** - Python, JavaScript, TypeScript, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart
- ✅ **Automated Acceptance Testing** - `/acceptance-test` skill with parallel execution (4-6 min vs 30+ min)
- ✅ **Protocol-Based Design** - Structural typing with QaSuppressionStrategy and TddStrategy protocols
- ✅ **5285 Passing** - 472 new for strategy pattern (up from 4813)
- ✅ **Hook Path Robustness** - Hooks immune to CWD changes using `$CLAUDE_PROJECT_DIR`

---

## Implementation Status

### Implemented Event Types (48 Production Handlers + 11 Language Strategies)

**PreToolUse** (28 handlers):
- `destructive_git` - Blocks dangerous git operations (force push, hard reset, etc.)
- `sed_blocker` - Blocks sed commands (encourages Edit tool usage)
- `absolute_path` - Enforces relative paths in tool calls
- `git_stash` - Discourages git stash with escape hatch
- `tdd_enforcement` - Enforces test-driven development workflow (uses TDD strategy registry)
- `task_tdd_advisor` - Provides TDD workflow guidance with task-based enforcement
- `qa_suppression` - **NEW v2.9**: Unified QA suppression blocker with 11 language strategies (Python, JS, TS, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart)
- `lock_file_edit_blocker` - Prevents editing package lock files (package-lock.json, yarn.lock, etc.)
- `pip_break_system` - Blocks pip --break-system-packages flag
- `sudo_pip` - Blocks sudo pip install commands
- `curl_pipe_shell` - Blocks curl/wget piped to shell
- `dangerous_permissions` - Blocks chmod 777 and similar unsafe permissions
- `global_npm_advisor` - Advises against npm install -g (advisory)
- `orchestrator_only` - Opt-in mode for orchestrator-only handlers
- `plan_completion_advisor` - Guides moving completed plans to archive
- `pipe_blocker` - Blocks expensive commands piped to tail/head
- `daemon_restart_verifier` - Prevents commits if daemon cannot restart
- `gh_issue_comments` - Ensures gh issue view includes --comments
- `plan_number_helper` - Injects correct next plan number into context
- `validate_instruction_content` - Validates CLAUDE.md/README.md content quality
- `web_search_year` - Ensures web searches include current year (2026)
- `british_english` - Warns on American English spellings
- `worktree_file_copy` - Prevents accidental worktree file copies
- `npm_command` - Validates npm command usage
- `plan_workflow` - Enforces planning workflow steps
- `validate_plan_number` - Validates plan numbering consistency
- `plan_time_estimates` - Prevents time estimates in plans
- `markdown_organization` - Enforces markdown organization rules

**PostToolUse** (2 handlers):
- `bash_error_detector` - Detects and reports bash command errors
- `validate_eslint_on_write` - Validates ESLint compliance after file writes

**SessionStart** (5 handlers):
- `yolo_container_detection` - Detects YOLO container environments with confidence scoring
- `workflow_state_restoration` - Restores workflow state after conversation compaction
- `optimal_config_checker` - Checks Claude Code config for optimal settings (env vars, settings.json)
- `suggest_statusline` - Suggests daemon-based status line setup
- `version_check` - Checks if daemon is up-to-date with latest GitHub release

**PreCompact** (2 handlers):
- `transcript_archiver` - Archives conversation transcripts before compaction
- `workflow_state_pre_compact` - Saves workflow state before compaction

**SubagentStop** (2 handlers):
- `remind_prompt_library` - Reminds about prompt library after subagent work
- `subagent_completion_logger` - Logs subagent completion events

**UserPromptSubmit** (1 handler):
- `git_context_injector` - Injects git context into prompts

**SessionEnd** (1 handler):
- `cleanup_handler` - Performs cleanup tasks at session end

**Notification** (1 handler):
- `notification_logger` - Logs notification events

**PermissionRequest** (1 handler):
- `auto_approve_reads` - Auto-approves read-only operations

**Stop** (3 handlers):
- `task_completion_checker` - Checks task completion status
- `auto_continue_stop` - Auto-continues when Claude asks confirmation questions
- `hedging_language_detector` - Detects guessing language in agent output

---

## Configuration

### Basic Configuration

**File**: `.claude/hooks-daemon.yaml`

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes idle
  log_level: INFO            # DEBUG, INFO, WARNING, ERROR

  # Input validation (v2.2.0+) - Catch malformed events
  input_validation:
    enabled: true            # Validate hook inputs (recommended)
    strict_mode: false       # Fail-closed on errors (default: fail-open)
    log_validation_errors: true

handlers:
  # PreToolUse handlers - Run before tool execution
  pre_tool_use:
    destructive_git:        # Block dangerous git operations
      enabled: true
      priority: 10

    sed_blocker:            # Block sed commands
      enabled: true
      priority: 10

    absolute_path:          # Enforce relative paths
      enabled: true
      priority: 12
      blocked_prefixes:
        - /container-mount/
        - /tmp/claude-code/

    worktree_file_copy:     # Prevent accidental worktree file copies
      enabled: true
      priority: 12

    git_stash:              # Discourage git stash with escape hatch
      enabled: true
      priority: 20
      escape_hatch: "YOLO"  # Use "YOLO" in commit message to bypass

    tdd_enforcement:        # Enforce TDD workflow
      enabled: true
      priority: 25

    eslint_disable:         # Prevent ESLint rule disabling
      enabled: true
      priority: 30

    markdown_organization:  # Enforce markdown organization rules
      enabled: true
      priority: 40

    npm_command:            # Validate npm command usage
      enabled: true
      priority: 45

    validate_plan_number:   # Validate plan numbering consistency
      enabled: true
      priority: 45

    plan_workflow:          # Enforce planning workflow steps
      enabled: true
      priority: 50

    plan_time_estimates:    # Prevent time estimates in plans
      enabled: true
      priority: 50

    web_search_year:        # Ensure current year in searches
      enabled: true
      priority: 55

    british_english:        # Warn on American spellings
      enabled: true
      priority: 60
      mode: warn            # "warn" or "block"
      excluded_dirs:
        - node_modules/
        - dist/

  # PostToolUse handlers - Run after tool execution
  post_tool_use:
    bash_error_detector:    # Detect bash command errors
      enabled: false        # Optional - enable for error detection
      priority: 10

  # SessionStart handlers - Run at session start
  session_start:
    yolo_container_detection:  # NEW in v2.1 - Detect YOLO containers
      enabled: true              # Set to false to disable detection
      priority: 40
      min_confidence_score: 3    # Threshold for detection (0-12 range)
      show_detailed_indicators: true   # Show detected indicators
      show_workflow_tips: true   # Show container workflow tips

    workflow_state_restoration:  # Restore workflow state
      enabled: false               # Optional - enable for workflow persistence
      priority: 10

  # PreCompact handlers - Run before conversation compaction
  pre_compact:
    workflow_state_pre_compact:  # Save workflow state before compaction
      enabled: false               # Optional - pairs with workflow_state_restoration
      priority: 10

  # SessionEnd, SubagentStop, UserPromptSubmit handlers
  session_end: {}
  subagent_stop: {}
  user_prompt_submit: {}
```

### Plugin System - Project-Specific Handlers

Add custom handlers in `.claude/hooks/handlers/` and register them:

```yaml
# .claude/hooks-daemon.yaml
plugins:
  paths: []  # Optional: additional Python module search paths
  plugins:
    # Load single handler from file
    - path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
      handlers: ["MyHandler"]  # Optional: specific class names (null = all)
      enabled: true

    # Load all handlers from directory
    - path: ".claude/hooks/handlers/post_tool_use/"
      handlers: null  # Load all Handler classes found
      enabled: true
```

### How Custom Handlers Attach to Events

**CRITICAL:** The plugin system loads ALL plugins for ALL event types. The directory path (e.g., `/pre_tool_use/`) is **convention only**, not enforcement.

Your handler MUST check `hook_event_name` in its `matches()` method:

```python
def matches(self, hook_input: dict) -> bool:
    # REQUIRED: Filter by event type
    event_name = hook_input.get("hook_event_name")
    if event_name != "PreToolUse":  # Change to your event type
        return False

    # Your custom matching logic
    return "my_pattern" in hook_input.get("tool_input", {}).get("command", "")
```

**Event Type Values:**
- `"PreToolUse"` - Before tool execution
- `"PostToolUse"` - After tool execution
- `"SessionStart"` - Session initialization
- `"SessionEnd"` - Session termination
- `"PreCompact"` - Before conversation compaction
- `"SubagentStop"` - Subagent completion
- `"UserPromptSubmit"` - User prompt submission
- `"Notification"` - Notification events
- `"PermissionRequest"` - Permission requests
- `"Stop"` - Stop events

**Directory Convention:**
- Place handlers in `.claude/hooks/handlers/{event_type}/` (convention)
- Example: `.claude/hooks/handlers/pre_tool_use/my_handler.py`
- The directory name does NOT enforce event filtering
- Your `matches()` method is responsible for event filtering

### Tag-Based Handler Selection

Handlers can be filtered using tags, allowing you to enable only specific categories of handlers or disable project-specific functionality.

#### Using enable_tags

Enable only handlers with specific tags:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, typescript, safety, tdd]
    # Only handlers with at least one of these tags will run
```

This configuration would enable:
- All Python-related handlers (`python` tag)
- All TypeScript/JavaScript handlers (`typescript` tag)
- All safety handlers (`safety` tag)
- TDD enforcement handlers (`tdd` tag)

#### Using disable_tags

Disable handlers with specific tags:

```yaml
handlers:
  pre_tool_use:
    disable_tags: [ec-specific, project-specific]
    # Handlers with these tags will NOT run
```

This configuration would disable:
- All Edmonds Commerce-specific handlers
- All project-specific validation handlers

#### Tag Taxonomy

**Language Tags:**
- `python` - Python-specific handlers
- `php` - PHP-specific handlers
- `typescript` - TypeScript-specific handlers
- `javascript` - JavaScript-specific handlers
- `go` - Go-specific handlers

**Function Tags:**
- `safety` - Critical safety handlers (prevent destructive operations)
- `tdd` - Test-driven development enforcement
- `qa-enforcement` - Code quality/linting enforcement
- `qa-suppression-prevention` - Blocks lazy QA suppression comments
- `workflow` - Workflow guidance and automation
- `advisory` - Non-blocking suggestions
- `validation` - Validates code/files
- `logging` - Logs events
- `cleanup` - Cleanup operations

**Tool Tags:**
- `git` - Git-related operations
- `npm` - NPM-related operations
- `bash` - Bash command handling

**Project Specificity Tags:**
- `ec-specific` - Edmonds Commerce-specific functionality
- `project-specific` - Tied to specific project structures

#### Combining Filters

You can combine `enable_tags` with `disable_tags`:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, typescript, javascript]  # Only these languages
    disable_tags: [ec-specific]                     # But exclude EC-specific handlers
```

Individual handler `enabled: false` settings override tag filtering:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python]

    # This handler would normally be enabled by the python tag,
    # but we explicitly disable it
    python_qa_suppression_blocker:
      enabled: false
```

### Language-Specific Handlers

The daemon includes language-specific handlers for common development tasks:

#### Python (`python` tag)
- **TDD Enforcement**: Requires test files for new Python modules
- **QA Suppression Blocker**: Prevents `# type: ignore`, `# noqa`, `# pylint: disable` without justification

#### TypeScript/JavaScript (`typescript`, `javascript` tags)
- **ESLint Disable Blocker**: Prevents `eslint-disable`, `@ts-ignore`, `@ts-nocheck` without justification
- **ESLint Validation**: Validates ESLint compliance after Write operations
- **NPM Command Advisor**: Provides guidance on npm commands

#### PHP (`php` tag)
- **PHP QA Suppression Blocker**: Prevents `@phpstan-ignore`, `@psalm-suppress`, `phpcs:ignore` without justification

#### Go (`go` tag)
- **Go QA Suppression Blocker**: Prevents `//nolint`, `//lint:ignore` without justification

#### Git (`git` tag)
- **Destructive Git Blocker**: Prevents destructive git commands (`push --force`, `reset --hard`, etc.)
- **Git Stash Blocker**: Warns about git stash operations
- **Worktree File Copy Blocker**: Prevents copying files from other git worktrees
- **Git Context Injector**: Adds git context to user prompts

### QA Suppression Prevention

The daemon includes handlers that prevent lazy QA tool suppression comments across multiple languages. These handlers block comments that silence static analysis tools without proper justification.

#### Why Block QA Suppressions?

QA suppression comments (`# type: ignore`, `@ts-ignore`, `phpcs:ignore`, etc.) hide real code quality issues. They:
- Create technical debt
- Mask bugs that could reach production
- Reduce code maintainability
- Bypass important safety checks

#### What Gets Blocked

**Python:**
- `# type: ignore` (MyPy)
- `# noqa` (Ruff/Flake8)
- `# pylint: disable` (Pylint)
- `# pyright: ignore` (Pyright)
- `# mypy: ignore-errors` (MyPy module-level)

**TypeScript/JavaScript:**
- `// eslint-disable`
- `/* eslint-disable */`
- `// @ts-ignore`
- `// @ts-nocheck`
- `// @ts-expect-error` (without explanation)

**PHP:**
- `@phpstan-ignore-next-line` (PHPStan)
- `@phpstan-ignore-line` (PHPStan)
- `@psalm-suppress` (Psalm)
- `phpcs:ignore` (PHP_CodeSniffer)
- `@codingStandardsIgnoreLine` (PHPCS)

**Go:**
- `//nolint` (golangci-lint)
- `//lint:ignore` (golint)

#### Correct Approach

When blocked, you should:

1. **Fix the underlying issue** - Add type hints, improve code structure, fix the actual problem
2. **Add detailed justification** - If it's a legitimate edge case:
   ```python
   # type: ignore[import]  # Justification: third-party library has no type stubs
   ```
3. **Test-specific code** - Ensure test fixtures are in `tests/fixtures/` or `testdata/` directories
4. **Legacy code** - Document WHY in a comment and create a ticket to fix it

#### Disabling QA Suppression Prevention

If you need to disable these handlers:

```yaml
handlers:
  pre_tool_use:
    # Disable all QA suppression prevention handlers
    disable_tags: [qa-suppression-prevention]

    # Or disable individual handlers
    python_qa_suppression_blocker:
      enabled: false
```

### Project-Specific Handlers

Some handlers in this repository are specific to Edmonds Commerce projects and may not be applicable to other codebases.

#### EC-Specific Handlers

The following handlers have the `ec-specific` or `project-specific` tags:

**ValidateSitemap** (`post_tool_use`)
- Validates EC sitemap architecture
- Highly specific to EC project structure
- **Recommendation**: Disable for non-EC projects

**MarkdownOrganization** (`pre_tool_use`)
- Enforces EC markdown file organization
- Checks for hardcoded paths specific to EC projects
- **Recommendation**: Disable or customize for your project

**RemindValidator** (`subagent_stop`)
- Orchestrates EC-specific validation subagents
- References EC-specific tools and workflows
- **Recommendation**: Disable for non-EC projects

**AutoContinue** (`user_prompt_submit`)
- EC-specific workflow automation
- Continues execution based on EC conventions
- **Recommendation**: Disable or customize for your workflow

**BritishEnglish** (`pre_tool_use`)
- EC organizational preference for British English spelling
- Not project-specific but organization-specific
- **Recommendation**: Disable if not using British English

#### Disabling Project-Specific Handlers

To disable all EC-specific and project-specific handlers:

```yaml
handlers:
  pre_tool_use:
    disable_tags: [ec-specific, project-specific]
  post_tool_use:
    disable_tags: [ec-specific, project-specific]
  subagent_stop:
    disable_tags: [ec-specific, project-specific]
  user_prompt_submit:
    disable_tags: [ec-specific, project-specific]
```

Or use a more concise approach:

```yaml
handlers:
  "*":  # Apply to all event types (if supported in future versions)
    disable_tags: [ec-specific, project-specific]
```

#### Creating Your Own Project-Specific Handlers

Projects can define their own handlers in `.claude/project-handlers/`. These are auto-discovered by convention, co-located with tests, and use the same Handler ABC as built-in handlers.

```bash
# Scaffold project-handlers directory with example handler and tests
$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers

# Validate handlers load correctly
$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers

# Run project handler tests
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose
```

**Directory structure**: Event-type subdirectories (`pre_tool_use/`, `post_tool_use/`, etc.) with handler `.py` files and co-located `test_` files.

```yaml
# .claude/hooks-daemon.yaml
project_handlers:
  enabled: true
  path: .claude/project-handlers  # Default location
```

See `CLAUDE/PROJECT_HANDLERS.md` for the complete developer guide and examples.

> **Migrating from plugins?** Project-level handlers replace the legacy plugin system for per-project customisation. Key differences: auto-discovery (no config per handler), event-type directories (no manual `hook_event_name` checks in `matches()`), co-located tests, and CLI tooling. The legacy plugin system still works for backward compatibility.

---

## Architecture

**Forwarder Pattern:**
```
Claude Code → Hook Script → Unix Socket → Daemon → FrontController → Handlers
```

**Components:**
- **Hook Scripts** (`.claude/hooks/*`) - Lightweight bash forwarders
- **Daemon** - Long-running Python process with Unix socket server
- **FrontController** - Dispatches events to registered handlers
- **Handlers** - Pattern matching and execution logic

**Handler Priority Ranges:**
- **0-19**: Critical safety (destructive operations, dangerous commands)
- **20-39**: Code quality (ESLint, TDD, validation)
- **40-59**: Workflow (planning, npm conventions, state management)
- **60-79**: Advisory (British English, style hints)
- **80-99**: Logging/metrics (analytics, audit trails)

**Performance:**
- Cold start: ~21ms (process spawn + Python startup)
- Warm: <1ms (Unix socket IPC)
- 20x faster after first hook call

For detailed architecture documentation, see `CLAUDE/ARCHITECTURE.md`.

---

## Handler Categories

### Safety Handlers (Priority 0-19)

**Critical Operations Prevention:**
- `destructive_git` (Priority 10) - Blocks `git push --force`, `git reset --hard`, `git clean -f`, `git branch -D`
- `sed_blocker` (Priority 10) - Blocks sed commands, encourages Edit tool
- `absolute_path` (Priority 12) - Prevents absolute path usage (enforces relative paths)

### Code Quality Handlers (Priority 20-39)

**Development Standards:**
- `tdd_enforcement` (Priority 25) - Requires tests before code changes
- `eslint_disable` (Priority 30) - Prevents `eslint-disable` comments

### Workflow Handlers (Priority 40-59)

**Process Automation:**
- `yolo_container_detection` (Priority 40) - **NEW in v2.1** Detects container environments
- `npm_command` (Priority 45) - Validates npm command patterns
- `plan_workflow` (Priority 50) - Enforces planning steps
- `web_search_year` (Priority 55) - Adds current year (2026) to web searches

### Advisory Handlers (Priority 60-79)

**Style & Conventions:**
- `british_english` (Priority 60) - Warns on American English spellings (configurable: warn/block)

### State Management Handlers

**Workflow Persistence:**
- `workflow_state_pre_compact` (PreCompact, Priority 10) - Saves workflow state before compaction
- `workflow_state_restoration` (SessionStart, Priority 10) - Restores workflow state after compaction

### Validation Handlers (PostToolUse)

**Post-Execution Checks:**
- `bash_error_detector` (Priority 10) - Detects bash command failures
- `validate_eslint_on_write` (Priority 30) - Validates ESLint compliance

---

## Daemon Management

All commands use the venv Python (NOT system Python).

**Working Directory**: Commands can be run from project root or any subdirectory. The CLI walks up the directory tree to find `.claude`. If you get an error about .claude not found, you are outside the project directory.

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Start daemon manually (usually not needed - lazy startup)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start

# Stop daemon
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# Check daemon status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Restart daemon (stop + start)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

**Lazy Startup:**
- Daemon starts automatically on first hook call
- No need to manually start
- Exits after 10 minutes of inactivity (configurable)

**Multi-Project Support:**
- Each project gets its own daemon instance
- Daemons identified by project directory path
- No conflicts between projects

---

## Development

### Handler Development

See `CLAUDE/HANDLER_DEVELOPMENT.md` for complete guide.

**Before Writing Handlers:**

Debug event flows first to understand which events fire and what data is available:

```bash
./scripts/debug_hooks.sh start "Testing scenario X"
# ... perform actions in Claude Code ...
./scripts/debug_hooks.sh stop
# Logs show exact events, timing, and data
```

See `CLAUDE/DEBUGGING_HOOKS.md` for complete introspection guide.

**Quick Start:**

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,      # Workflow range
            terminal=True     # Stop dispatch after this handler
        )

    def matches(self, hook_input: dict) -> bool:
        """Return True if handler should run."""
        return "pattern" in hook_input.get("tool_input", {}).get("command", "")

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic."""
        return HookResult(
            decision=Decision.DENY,
            reason="Blocked because...",
            context=["Additional context line 1", "Line 2"]
        )
```

**Examples:**
- **Environment Detection**: `handlers/session_start/yolo_container_detection.py` - Confidence scoring, fail-open error handling
- **Simple Blocking**: `handlers/pre_tool_use/destructive_git.py` - Pattern matching, terminal handler
- **Complex Matching**: `handlers/pre_tool_use/sed_blocker.py` - Regex patterns, command parsing
- **Advisory**: `handlers/pre_tool_use/british_english.py` - Non-terminal warnings, configurable modes

### Testing

**Run QA Suite:**
```bash
./scripts/qa/run_all.sh  # All checks (format, lint, type, tests)
```

**Individual Checks:**
```bash
./scripts/qa/run_format_check.sh  # Black formatter (auto-fixes)
./scripts/qa/run_lint.sh           # Ruff linter (auto-fixes)
./scripts/qa/run_type_check.sh    # MyPy type checker
./scripts/qa/run_tests.sh         # Pytest + coverage
```

**QA Standards:**
- **Black** - Code formatting (line length 100)
- **Ruff** - Python linting (auto-fixes violations)
- **MyPy** - Strict type checking (all functions typed)
- **Pytest** - 95% minimum coverage, 4693 tests
- **Bandit** - Security vulnerability scanning

All checks auto-fix by default (except MyPy and tests).

**Current Test Stats:**
- **5285 tests** across 202 test files
- **95% coverage requirement**
- All tests passing

### Type Annotations

**Python 3.11+ syntax supported:**

```python
# Modern syntax (preferred)
def example(data: dict[str, Any]) -> list[str] | None:
    pass

# typing module (also acceptable)
from typing import Dict, List, Optional, Any

def example(data: Dict[str, Any]) -> Optional[List[str]]:
    pass
```

---

## Upgrading

### Version Detection

**Programmatic:**
```python
from claude_code_hooks_daemon.version import __version__
print(__version__)  # "2.5.0"
```

**Git-based:**
```bash
cd .claude/hooks-daemon
git describe --tags  # v2.2.0
```

### Upgrade Guides

**Location**: `CLAUDE/UPGRADES/`

The upgrade system provides LLM-optimized migration guides with:
- Step-by-step instructions
- Configuration examples (before/after/additions)
- Verification scripts
- Rollback procedures
- Example outputs

**Available Upgrades:**
- `v2/v2.0-to-v2.1/` - Adds YOLO Container Detection handler

**How to Upgrade:**

1. **Find your current version:**
   ```bash
   cd .claude/hooks-daemon
   cat src/claude_code_hooks_daemon/version.py
   ```

2. **Read upgrade guide:**
   ```bash
   # Example: Upgrading from v2.0 to v2.1
   cat CLAUDE/UPGRADES/v2/v2.0-to-v2.1/v2.0-to-v2.1.md
   ```

3. **Follow instructions** in the guide

4. **Run verification:**
   ```bash
   bash CLAUDE/UPGRADES/v2/v2.0-to-v2.1/verification.sh
   ```

For complete documentation, see `CLAUDE/UPGRADES/README.md`.

---

## Documentation

**Core Documentation** (`CLAUDE/` directory):
- `ARCHITECTURE.md` - System architecture and design decisions
- `DEBUGGING_HOOKS.md` - **Hook event introspection tool** (critical for handler development)
- `HANDLER_DEVELOPMENT.md` - Handler creation guide with examples
- `LLM-INSTALL.md` - LLM-optimized installation guide
- `UPGRADES/` - Version migration guides

**Examples:**
- `examples/basic_setup/hooks-daemon.yaml` - Basic configuration example
- Handler source code in `src/claude_code_hooks_daemon/handlers/` (self-documenting)

**Project Files:**
- `README.md` - This file (overview and usage)
- `CONTRIBUTING.md` - Contribution guidelines
- `pyproject.toml` - Package configuration and dependencies

---

## Project Structure

```
claude-code-hooks-daemon/
├── src/claude_code_hooks_daemon/
│   ├── core/              # Front controller, Handler base, HookResult
│   ├── daemon/            # Server, CLI, DaemonController, paths
│   ├── handlers/          # All handler implementations (by event type)
│   │   ├── pre_tool_use/      # 31 production handlers
│   │   ├── post_tool_use/     # 3 production handlers
│   │   ├── session_start/     # 5 production handlers
│   │   ├── session_end/       # 1 production handler
│   │   ├── pre_compact/       # 2 production handlers
│   │   ├── subagent_stop/     # 3 production handlers
│   │   ├── user_prompt_submit/  # 1 production handler
│   │   ├── notification/      # 1 production handler
│   │   ├── permission_request/  # 1 production handler
│   │   └── stop/              # 3 production handlers
│   ├── config/            # YAML/JSON config loading
│   ├── hooks/             # Entry point modules (one per event type)
│   ├── plugins/           # Plugin system for custom handlers
│   ├── qa/                # QA runner utilities
│   └── version.py         # Version tracking
├── tests/                 # 172 test files, 4693 tests, 95% coverage
│   ├── unit/              # Unit tests for all components
│   ├── integration/       # Integration tests
│   └── config/            # Configuration validation tests
├── scripts/
│   ├── qa/                # QA automation scripts
│   └── debug_hooks.sh     # Hook event introspection tool
├── CLAUDE/                # LLM-optimized documentation
│   ├── ARCHITECTURE.md
│   ├── DEBUGGING_HOOKS.md
│   ├── HANDLER_DEVELOPMENT.md
│   ├── LLM-INSTALL.md
│   └── UPGRADES/          # Version migration guides
├── examples/              # Configuration examples
├── install.py             # Automated installer
└── pyproject.toml         # Package configuration
```

---

## Requirements

**Python:**
- Python 3.11, 3.12, or 3.13
- Virtual environment support (venv)

**Dependencies** (auto-installed):
- `pyyaml>=6.0` - YAML configuration parsing
- `pydantic>=2.5` - Type-safe data validation
- `jsonschema>=4.0` - JSON schema validation

**Development Dependencies:**
- `pytest>=7.0` - Testing framework
- `pytest-cov>=4.0` - Coverage reporting
- `pytest-mock>=3.0` - Mocking utilities
- `pytest-anyio>=0.0.0` - Async testing
- `black>=23.0` - Code formatter
- `ruff>=0.0.290` - Fast Python linter
- `mypy>=1.5` - Static type checker

**Platform:**
- Linux (primary)
- macOS (supported)
- Windows (limited support - Unix sockets may have issues)

---

## Performance

**Benchmark Results:**

| Metric | Cold Start | Warm (After First Call) |
|--------|------------|-------------------------|
| Response Time | ~21ms | <1ms |
| Overhead | Process spawn + Python startup | Unix socket IPC only |
| Improvement | Baseline | **20x faster** |

**Optimizations:**
- Unix socket IPC eliminates process spawn overhead
- Front controller caching reduces handler lookup time
- Lazy startup minimizes resource usage
- Auto-shutdown after idle timeout reduces memory footprint

---

## Troubleshooting

**For comprehensive troubleshooting and bug reporting, see [BUG_REPORTING.md](BUG_REPORTING.md)**

### Quick Debug Report

Generate a complete diagnostic report for troubleshooting or bug reports:

```bash
# In daemon project (this repository)
./scripts/debug_info.py /tmp/debug_report.md

# In client project (where daemon is installed)
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

The report includes:
- System information and daemon status
- Configuration files and handler registration
- Hook tests (simple + destructive git command)
- Recent daemon logs
- Complete health summary

### Daemon Won't Start

```bash
# Check if socket file is stuck
ls -la .claude/hooks-daemon/untracked/venv/socket

# Remove stuck socket
rm .claude/hooks-daemon/untracked/venv/socket

# Try starting manually
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli start
```

### Check Daemon Logs

```bash
# View recent logs
tail -f .claude/hooks-daemon/untracked/venv/daemon.log

# Full logs
cat .claude/hooks-daemon/untracked/venv/daemon.log
```

### Force Stop Daemon

```bash
# If daemon won't stop gracefully
pkill -f claude_code_hooks_daemon

# Remove socket file
rm .claude/hooks-daemon/untracked/venv/socket
```

### Verify Installation

```bash
# Check hook scripts exist
ls -la .claude/hooks/

# Test hook execution
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo test"}}' | \
  .claude/hooks/pre-tool-use

# Should output valid JSON with decision="allow"
```

---

## Contributing

See `CONTRIBUTING.md` for guidelines.

**Quick Start:**

1. Fork the repository
2. Create feature branch: `git checkout -b feature/your-feature`
3. Write tests first (TDD)
4. Implement feature
5. Run QA suite: `./scripts/qa/run_all.sh`
6. Commit with descriptive message
7. Push and create pull request

**Standards:**
- All code must pass QA checks (format, lint, type, tests, security)
- 95% minimum test coverage
- Type annotations on all functions
- Docstrings on all public classes/methods

---

## License

MIT License - see LICENSE file for details.

**Copyright © 2024-2026 Edmonds Commerce**

---

## Support

**Issues & Bugs:**
- GitHub Issues: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
- Bug Reporting: See [BUG_REPORTING.md](BUG_REPORTING.md) for debug script usage

**Documentation:**
- Architecture: `CLAUDE/ARCHITECTURE.md`
- Handler Development: `CLAUDE/HANDLER_DEVELOPMENT.md`
- Upgrade Guides: `CLAUDE/UPGRADES/`
- Troubleshooting: [BUG_REPORTING.md](BUG_REPORTING.md)

**Contact:**
- Email: hello@edmondscommerce.co.uk

---

## Changelog

### v2.9.0 (Current)

**Strategy Pattern Architecture:**
- Unified QA suppression handler with 11 language strategies (Python, JS, TS, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart)
- TDD enforcement refactored to use strategy registry
- 4 per-language handlers replaced by 1 strategy-based handler
- Protocol-based design with structural typing
- Extension-to-strategy registry for automatic language detection
- 5285 total validations (472 new for strategy pattern)

**Automated Acceptance Testing:**
- `/acceptance-test` skill with parallel Haiku agent execution
- Reduces testing time from 30+ minutes to 4-6 minutes (80% improvement)
- Structured JSON results for automated release gates

**Fixes:**
- Hook paths now robust against CWD changes using `$CLAUDE_PROJECT_DIR`

### v2.8.0

**Project-Level Handlers:**
- First-class support for per-project custom handlers
- Auto-discovery and loading from `.claude/project_handlers/`
- CLI commands: scaffold, list, validate handlers
- Complete integration with library handlers

### v2.7.0

**New Handlers & Features:**
- Optimal Config Checker - SessionStart handler auditing env/settings for optimal Claude Code config
- Hedging Language Detector - Stop handler detecting guessing language in agent output
- PHP QA CI Integration - Enhanced PHP QA suppression handler with CI awareness
- Library/Plugin Separation - Clean separation of library and plugin concerns (Plan 00034)
- Robust Upgrade Detection - Handles broken installations gracefully (Plan 00043)

**Quality & Testing:**
- Coverage boost from 94.40% to 96.33%
- Significant test expansion across all handler types
- Curl-to-file install/update instructions

**Fixes:**
- Restored dogfooding_reminder plugin
- PR #20 post-merge QA fixes

### v2.5.0

**Plugin System & Multi-Environment:**
- ✅ **Complete Plugin System Overhaul** - Event-type aware loading with acceptance testing (Plan 00024)
- ✅ **9 New Handlers** - Lock file protection, system package safety, orchestrator mode, TDD advisor
- ✅ **Hostname-Based Isolation** - Multi-environment daemon support with isolated runtime files
- ✅ **Worktree Support** - CLI flags for git worktree isolation (--pid-file, --socket)

**Testing & Quality:**
- ✅ **Programmatic Acceptance Testing** - Ephemeral playbook generation for all 59+ handlers (Plan 00025)
- ✅ **Config Validation** - Startup validation with strict mode fail-fast behavior (Plan 00020)
- ✅ **Dependency Checking** - Integrated deptry into QA suite
- ✅ **4261 Tests Passing** - 1089 new tests, 95%+ coverage maintained

**Architecture:**
- ✅ **LanguageConfig Foundation** - Centralized language-specific QA suppression patterns (Plan 00021)
- ✅ **Agent Team Workflow** - Multi-role verification with honesty checking
- ✅ **Code Lifecycle Documentation** - Complete Definition of Done checklists

### v2.4.0

**Security & Quality:**
- ✅ **ZERO security violations** - Complete audit eliminating all B108, B602, B603, B607, B404 issues
- ✅ Acceptance Testing Playbook with 15+ critical handler tests
- ✅ FAIL-FAST cycle for release validation
- ✅ Security Standards Documentation with ZERO TOLERANCE policy

**Architecture:**
- ✅ ProjectContext Architecture - Eliminated CWD dependencies (Plan 00014)
- ✅ Handler Status Reporting - Post-install verification system
- ✅ Plan Lifecycle System - Archival with hard links

**Documentation:**
- ✅ Release Process Documentation - Single source of truth
- ✅ Comprehensive Hooks Documentation
- ✅ Planning Workflow Guidance

### v2.3.0

**New Features:**
- ✅ Installation Safety - Pre-installation checks
- ✅ Repo Name in Status Line - With model color coding
- ✅ Triple-Layer Safety - Enhanced blocker system

**Fixes:**
- ✅ Critical Protocol Bug - Handlers not blocking correctly
- ✅ TDD Enforcement - Fixed directory detection
- ✅ Sed Blocker - Improved pattern matching

### v2.2.0

**New Features:**
- ✅ Custom sub-agents for QA and development workflow automation
- ✅ Automated release management system with `/release` skill
- ✅ Hook event debugging tool for handler development
- ✅ Self-install mode support in CLI and configuration
- ✅ 95% test coverage with 2472 passing tests

### v2.1.0

**New Features:**
- ✅ YOLO Container Detection handler with confidence scoring system
- ✅ Upgrade system with LLM-optimized migration guides
- ✅ Version tracking via `claude_code_hooks_daemon.version`

**Improvements:**
- Enhanced HANDLER_DEVELOPMENT.md with comprehensive examples
- Automated verification scripts for upgrades
- Configuration examples for all handler types

**Handler Additions:**
- `yolo_container_detection` (SessionStart, Priority 40)

### v2.0.0

**Initial Release:**
- 30 production handlers across 10 event types
- Daemon architecture with Unix socket IPC
- Front controller dispatch pattern
- Plugin system for custom handlers
- Comprehensive test suite (1168 tests, 95% coverage)
- Full type safety with MyPy strict mode
- Automated QA pipeline

---

**End of README** | Version 2.7.0 | Last Updated: 2026-02-09
