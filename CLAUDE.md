# Claude Code Hooks Daemon - LLM Context

## What This Is

A high-performance daemon for Claude Code hooks using Unix socket IPC. Eliminates process spawn overhead (20x faster after warmup).

## ⚠️ CRITICAL: Code Lifecycle (READ BEFORE MAKING CHANGES)

**MANDATORY**: Read these documents BEFORE implementing changes:

- **Before implementing features**: @CLAUDE/CodeLifecycle/Features.md
- **Before fixing bugs**: @CLAUDE/CodeLifecycle/Bugs.md
- **For all code changes**: @CLAUDE/CodeLifecycle/General.md

### The Non-Negotiable Rule

**EVERY change MUST pass daemon restart verification**:

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING
```

**If daemon fails to start, your change is NOT done** - fix it before committing.

**Why this matters**: Unit tests alone don't catch import errors. The 5-handler failure (wrong import path) would have been caught by daemon restart.

## Claude Code Hooks System

**Claude Code is the source of truth for hook formats.** This daemon intercepts hook events from Claude Code CLI and processes them through handler chains.

Hook events fire at key moments (PreToolUse, PostToolUse, SessionStart, etc.) and allow custom logic to:
- Block destructive operations (git reset --hard, sed -i, etc.)
- Inject context (git status, plan numbers)
- Enforce workflows (TDD, planning)
- Validate code quality

**CRITICAL**: When testing hooks, use `./scripts/debug_hooks.sh` to capture REAL event formats from Claude Code. Test expectations are documentation - Claude Code itself defines the contract.

**See [CLAUDE/Code/HooksSystem.md](CLAUDE/Code/HooksSystem.md) for complete hook system documentation.**

## ⚠️ Self-Install Mode (CRITICAL)

**This project dogfoods itself** - it runs from workspace root, not `.claude/hooks-daemon/`.

### Key Paths (Different from Normal Installs)

```bash
# Python command (ALWAYS use this)
PYTHON=/workspace/untracked/venv/bin/python

# Config
CONFIG=/workspace/.claude/hooks-daemon.yaml

# Source code runs from workspace
SRC=/workspace/src/claude_code_hooks_daemon/
```

### Why This Matters

- Venv at `/workspace/untracked/venv/` (NOT `.claude/hooks-daemon/untracked/venv/`)
- Source at `/workspace/src/` (NOT installed package)
- Config has `self_install_mode: true`
- `.claude/hooks-daemon.env` sets `HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`

**See CLAUDE/SELF_INSTALL.md for complete details**

### Quick Commands

```bash
# Daemon lifecycle
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Development
./scripts/qa/run_all.sh          # QA before commits
./scripts/debug_hooks.sh start   # Debug hook events
```

## Engineering Principles

**CRITICAL: Follow these for ALL code changes:**

1. **FAIL FAST** - Detect errors early, validate at boundaries, explicit error handling
2. **YAGNI** - Don't build for hypothetical futures
3. **DRY** - Single source of truth for all logic
4. **SINGLE SOURCE OF TRUTH** - Config is truth, code reads config, never hardcode
5. **PROPER NOT QUICK** - No workarounds, fix root causes
6. **TYPE SAFETY** - Full type annotations, strict mypy, no `Any` without justification
7. **TEST COVERAGE** - 95% minimum, integration tests for all flows
8. **SCHEMA VALIDATION** - Validate all external data

**When in doubt:**
- Read the config, don't guess
- Fix the root cause, don't work around it
- Add tests first, then implement
- Validate with schemas, don't assume

## Security Standards

**ZERO TOLERANCE POLICY - All security issues must be fixed immediately**

### Security Principles

1. **ALL SECURITY LEVELS MATTER** - HIGH, MEDIUM, and LOW severity issues are all unacceptable
2. **FAIL FAST ON SECURITY** - Never silently suppress security errors or exceptions
3. **NO SHORTCUTS** - Fix root causes, never work around security issues
4. **ABSOLUTE HIGHEST STANDARDS** - Security is non-negotiable

### Required Security Practices

**Subprocess Security (B602, B603, B607, B404):**
- **NEVER use `shell=True`** in subprocess calls - it enables command injection attacks
- Always pass commands as lists: `["git", "status"]` not `"git status"`
- Replace shell operators (`||`, `&&`) with explicit Python logic (try/except)
- Only trusted system tools (git, ruff, mypy, black, pytest, bandit) may use subprocess
- Document all subprocess usage with SECURITY comments

**File Security (B108):**
- **NEVER use `/tmp`** for runtime files (sockets, PID files, logs)
- Always use daemon's untracked directory via `ProjectContext.daemon_untracked_dir()`
- Normal mode: `{project}/.claude/hooks-daemon/untracked/`
- Self-install mode: `{project}/untracked/`

**Cryptographic Security (B324):**
- When using MD5 for non-security purposes, **MUST** specify `usedforsecurity=False`
- Document why MD5 is acceptable (e.g., "hash for path identifier, not cryptographic")

**Error Handling (B110):**
- **NEVER silently suppress exceptions** with bare try/except/pass
- FAIL FAST - if something can't import or initialize, crash immediately
- No silent error hiding - all failures must be visible

### QA Security Check

Security check **MUST pass with ZERO issues** before any commit:

```bash
./scripts/qa/run_security_check.sh
# Expected: 0 issues (HIGH, MEDIUM, LOW all count)
# Only B101 (assert statements) is filtered
```

**See scripts/qa/run_security_check.sh for enforcement details**

## Planning Workflow

**CRITICAL: Plan before implementing**

All non-trivial work must follow the planning workflow:

1. **Create a plan** in `CLAUDE/Plan/NNNNN-description/`
2. **Document approach** in `PLAN.md` with tasks, goals, and success criteria
3. **Get approval** before implementation (for human developers)
4. **Execute plan** following TDD principles
5. **Update plan** as work progresses
6. **Complete plan** with summary and results

**See @CLAUDE/PlanWorkflow.md for complete workflow and templates**

**Current plans**: See `CLAUDE/Plan/README.md` for active/completed plans

## Architecture

```
src/claude_code_hooks_daemon/
├── core/           # Front controller, Handler base, HookResult
├── daemon/         # Server, CLI, DaemonController, paths
├── handlers/       # All handler implementations (by event type)
├── config/         # YAML/JSON config loading
├── hooks/          # Entry point modules (one per event)
└── plugins/        # Plugin system for custom handlers
```

**Pattern**: Bash scripts → Unix socket → Daemon → FrontController → Handlers

**See CLAUDE/ARCHITECTURE.md for design deep-dive**

## Handler Development

**Before writing handlers**: Debug event flow first
```bash
./scripts/debug_hooks.sh start "Testing scenario"
# ... perform actions in Claude Code ...
./scripts/debug_hooks.sh stop
# Logs saved to /tmp/hook_debug_TIMESTAMP.log
```

**See CLAUDE/DEBUGGING_HOOKS.md for complete workflow**

### Handler Skeleton

```python
from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return "pattern" in hook_input.get("tool_input", {})

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Blocked")
```

**See CLAUDE/HANDLER_DEVELOPMENT.md for complete guide**

### Priority Ranges

- **5**: Test handlers
- **10-20**: Safety (destructive git, sed blocker)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English)

### Terminal vs Non-Terminal

- `terminal=True`: Stops dispatch chain, returns immediately
- `terminal=False`: Continues dispatch, accumulates context

## Configuration

Config file: `.claude/hooks-daemon.yaml`

```yaml
version: 1.0
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: true  # For this project only
handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
```

## QA Requirements

**MUST pass before commits:**
- Black (format), Ruff (lint), MyPy (types), Pytest (95% coverage), Bandit (security)
- Run: `./scripts/qa/run_all.sh`

**See CONTRIBUTING.md for QA standards and CI/CD details**

## Documentation

- **CLAUDE/ARCHITECTURE.md** - Design documentation
- **CLAUDE/DEBUGGING_HOOKS.md** - Hook debugging workflow
- **CLAUDE/HANDLER_DEVELOPMENT.md** - Handler creation guide
- **CLAUDE/SELF_INSTALL.md** - Self-install mode details
- **CLAUDE/LLM-INSTALL.md** - Installation guide
- **CLAUDE/LLM-UPDATE.md** - Update guide
- **@CLAUDE/PlanWorkflow.md** - Planning workflow and standards
- **CLAUDE/Plan/** - Implementation plans directory
- **RELEASES/** - Version release notes
- **CONTRIBUTING.md** - Contribution guidelines
