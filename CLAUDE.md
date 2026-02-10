# Claude Code Hooks Daemon - LLM Context

## What This Is

A high-performance daemon for Claude Code hooks using Unix socket IPC. Eliminates process spawn overhead (20x faster after warmup).

## 🚨 CRITICAL: RELEASE WORKFLOW (ABSOLUTE REQUIREMENT)

**NEVER RELEASE MANUALLY. ALWAYS FOLLOW STRICT RELEASE DOCUMENTATION.**

### The Release Rule (NON-NEGOTIABLE)

**ALL releases MUST use the `/release` skill or follow @CLAUDE/development/RELEASING.md exactly.**

```bash
# CORRECT - Use the release skill
/release

# WRONG - Manual operations bypass validation
git tag v2.7.0          # ❌ NEVER DO THIS
git push origin v2.7.0  # ❌ NEVER DO THIS
Edit CHANGELOG.md       # ❌ NEVER DO THIS
Edit RELEASES/*.md      # ❌ NEVER DO THIS
```

**Why this matters**: Manual release operations bypass:
- Pre-release validation (QA, git state, GitHub CLI)
- Version consistency checks across all files
- Changelog generation from commits
- Opus documentation review
- **🚨 QA VERIFICATION GATE** - Full QA suite must pass before commit
- **🚨 ACCEPTANCE TESTING GATE** - All acceptance tests must pass before commit
- Proper git tagging and GitHub release creation

**If you bypass the release workflow, you WILL create inconsistent releases with missing documentation, wrong versions, broken upgrade paths, and untested code.**

### Critical Blocking Gates (NON-NEGOTIABLE)

The `/release` skill includes TWO mandatory blocking gates that MUST pass before any git operations:

1. **QA Verification Gate** (after Opus review):
   - Main Claude manually runs: `./scripts/qa/run_all.sh`
   - ALL 6 checks must pass (Magic Values, Format, Lint, Type Check, Tests, Security)
   - If ANY check fails → ABORT release immediately

2. **Acceptance Testing Gate** (after QA passes):
   - Main Claude generates and executes full acceptance test playbook
   - ALL 15+ tests must pass in real Claude Code session
   - If ANY test fails → ABORT release, enter FAIL-FAST cycle
   - Time investment: Minimum 30 minutes

**These gates are BLOCKING. Release CANNOT proceed if they fail. No exceptions.**

### Release Commands

| Operation | Status |
|-----------|--------|
| `/release` | ✅ ONLY CORRECT WAY |
| `git tag v*` | ❌ FORBIDDEN |
| `git push origin v*` | ❌ FORBIDDEN |
| `git push origin tags` | ❌ FORBIDDEN |
| Edit CHANGELOG.md | ❌ FORBIDDEN (outside release) |
| Edit RELEASES/*.md | ❌ FORBIDDEN (outside release) |

**See @CLAUDE/development/RELEASING.md for complete release workflow documentation.**

---

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

## Hostname-Based Isolation

**Multi-Environment Support**: Each unique hostname gets isolated daemon runtime files, preventing conflicts when running multiple instances (containers, machines, etc.).

**How It Works**: Uses `HOSTNAME` environment variable directly as suffix - simple, transparent, debuggable.

**Path Pattern**:
- With hostname: `.claude/hooks-daemon/untracked/daemon-{hostname}.{sock,pid,log}`
- No hostname: `.claude/hooks-daemon/untracked/daemon-{time-hash}.{sock,pid,log}`

**Sanitization**: Hostname is lowercased and spaces replaced with hyphens for filesystem safety.

**Environment Overrides**: `CLAUDE_HOOKS_SOCKET_PATH`, `CLAUDE_HOOKS_PID_PATH`, `CLAUDE_HOOKS_LOG_PATH` take precedence.

**Examples**:
```bash
# Hostname used directly as suffix
HOSTNAME=laptop → daemon-laptop.sock
HOSTNAME=506355bfbc76 → daemon-506355bfbc76.sock
HOSTNAME=prod-server-01 → daemon-prod-server-01.sock
HOSTNAME="My Server" → daemon-my-server.sock (sanitized)

# No hostname = MD5(timestamp) for uniqueness
unset HOSTNAME → daemon-a1b2c3d4.sock
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
├── constants/      # Handler IDs, priorities, tags, tool names
├── hooks/          # Entry point modules (one per event)
├── install/        # Installer logic
├── plugins/        # Plugin system for custom handlers
├── qa/             # QA runner utilities
└── utils/          # Shared utilities
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

- **0-9**: Test handlers (hello_world), orchestrator-only
- **10-20**: Safety (destructive git, sed blocker, auto-approve)
- **25-35**: Code quality (ESLint, TDD, QA suppression)
- **36-55**: Workflow (planning, npm, config checker)
- **56-60**: Advisory (British English)
- **100+**: Logging/cleanup (notification logger, session cleanup)

### Terminal vs Non-Terminal

- `terminal=True`: Stops dispatch chain, returns immediately
- `terminal=False`: Continues dispatch, accumulates context

## Project-Level Handlers

Projects can define their own handlers in `.claude/project-handlers/`. These are auto-discovered by convention, co-located with tests, and use the same Handler ABC as built-in handlers.

```bash
# Scaffold project-handlers directory
$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers

# Validate handlers load correctly
$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers

# Run project handler tests
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose
```

**Directory structure**: Event-type subdirectories (`pre_tool_use/`, `post_tool_use/`, `session_start/`, etc.) with handler `.py` files and co-located `test_` files.

**See CLAUDE/PROJECT_HANDLERS.md for complete developer guide and examples.**

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
project_handlers:
  enabled: true
  path: .claude/project-handlers
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
- **CLAUDE/PROJECT_HANDLERS.md** - Project-level handler developer guide
- **CLAUDE/SELF_INSTALL.md** - Self-install mode details
- **CLAUDE/LLM-INSTALL.md** - Installation guide
- **CLAUDE/LLM-UPDATE.md** - Update guide
- **@CLAUDE/PlanWorkflow.md** - Planning workflow and standards
- **CLAUDE/Plan/** - Implementation plans directory
- **examples/project-handlers/** - Example project handlers with tests
- **RELEASES/** - Version release notes
- **CONTRIBUTING.md** - Contribution guidelines
