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
   - ALL 8 checks must pass (Magic Values, Format, Lint, Type Check, Tests, Security, Dependencies, Shell Check)
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

## ⚠️ CRITICAL: Checkpoint Commits (NON-NEGOTIABLE)

**Make regular checkpoint commits throughout your work.** Do NOT accumulate large batches of changes.

### Rules

1. **Commit after each logical unit of work** - a completed phase, a passing TDD cycle, a bug fix
2. **Commit before switching context** - before starting a new phase, before spawning agents, before research
3. **Commit before risky operations** - before refactoring, before changing shared code
4. **Never accumulate more than ~300 lines of uncommitted changes** - if you're approaching this, stop and commit

### Why This Matters

- Large uncommitted changesets are **impossible to roll back partially**
- Context window compaction can lose track of what changed
- Agent teams working in parallel need stable baselines
- If something breaks, you lose ALL uncommitted work

### Commit Message Format

```bash
# Checkpoint commits use descriptive prefixes
git commit -m "Fix: Description of fix"
git commit -m "Add: Description of addition"
git commit -m "Refactor: Description of refactoring"
git commit -m "Plan NNNNN: Phase N - Description"
```

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

### Blocking Handler False Positives in Commit Messages

Blocking handlers match patterns in the full Bash command string, including git commit messages. If you put a literal dangerous command in a commit message (e.g., describing a fix for "force branch delete"), the handler will block the commit.

**This is intentional and must NOT be "fixed"**. The same false-positive matching is what enables safe acceptance testing - we test blocking handlers by embedding dangerous commands in strings (e.g., `echo "git reset --hard"`) and verifying the handler blocks them. Removing string matching would break acceptance tests.

**Solution**: Simply avoid putting literal blocked patterns in commit messages. Describe the fix in different words (e.g., "force branch delete blocker" instead of the literal command). This is trivial to work around.

## Plans vs Workflows (CRITICAL DISTINCTION)

**These are TWO COMPLETELY SEPARATE concepts:**

### Plans (Development Work Tracking)

**Purpose**: Track development work in numbered folders (`CLAUDE/Plan/00001-`, `00002-`, etc.)

**Documentation**: [docs/PLAN_SYSTEM.md](../docs/PLAN_SYSTEM.md)

**Structure**: Numbered folders with `PLAN.md` files containing tasks, goals, status

**Lifecycle**: Not Started → In Progress → Complete (moved to `Completed/`)

**Optional Handlers**:
- `markdown_organization` - Enforces CLAUDE/Plan/ structure
- `plan_completion_advisor` - Reminds to move completed plans to Completed/

**When to Use**: Work taking > 2 hours, multi-phase implementation, architectural decisions

### Workflows (Repeatable Processes)

**Purpose**: Repeatable processes that survive conversation compaction (release, QA, etc.)

**Documentation**: [docs/WORKFLOWS.md](../docs/WORKFLOWS.md)

**Structure**: State files in `./untracked/workflow-state/{workflow-name}/` with phase tracking

**Lifecycle**: Start → Phase transitions → Complete (delete state file)

**Required Handlers**:
- `workflow_state_pre_compact` - Preserves workflow state before compaction
- `workflow_state_restoration` - Restores workflow state after compaction with required reading

**When to Use**: Formal multi-phase processes that need to survive compaction (releases, complex orchestrations)

**Key Difference**: Plans are for tracking development work. Workflows are for repeatable processes like releases that must survive compaction.

---

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
./scripts/qa/llm_qa.py all       # QA before commits (LLM-optimized, ~16 lines)
./scripts/qa/run_all.sh          # QA before commits (verbose, human-readable)
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

**CRITICAL: Follow these for ALL code changes.**

### SOLID Principles

1. **Single Responsibility** - Each class/module has ONE reason to change. Config is config. Strategy is strategy. Handler is handler. Never mix data and behavior in the same class.
2. **Open/Closed** - Open for extension, closed for modification. Use Strategy Pattern for language-aware handlers — add new languages by adding new strategy implementations, not by modifying existing if/elif chains.
3. **Liskov Substitution** - Any strategy implementation must be substitutable for another through the shared Protocol interface. No special-casing by type name.
4. **Interface Segregation** - Keep Protocol interfaces focused. `TddStrategy` only has TDD methods, not QA suppression methods. Clients should never depend on methods they don't use.
5. **Dependency Inversion** - Depend on abstractions (Protocols), not concretions. Handlers depend on `TddStrategy` Protocol, never on `PythonTddStrategy` directly.

### Core Standards

6. **FAIL FAST** - Detect errors early, validate at boundaries, explicit error handling. If something is wrong, crash immediately with a clear message — never silently continue.
7. **DRY** - Single source of truth for all logic. If you see the same pattern repeated, extract it. Common test directories, directory matching — shared utilities, not copy-paste.
8. **YAGNI** - Don't build for hypothetical futures. Implement what's needed now, design for extensibility through patterns (Strategy, Protocol), not through premature abstraction.
9. **NO MAGIC** - Zero magic strings or numbers. Every string literal and numeric value must be a named constant. `"/src/"` in an if-statement is magic — `_SOURCE_DIRECTORIES` tuple is not. Use constants modules, class constants, or module-level named tuples.
10. **SINGLE SOURCE OF TRUTH** - Config is truth, code reads config, never hardcode. Language configurations define language properties. Strategies define language behavior. Handlers orchestrate.
11. **PROPER NOT QUICK** - No workarounds, fix root causes. Three similar lines of code is better than a wrong abstraction, but six identical blocks means you need a proper pattern.
12. **TYPE SAFETY** - Full type annotations, strict mypy, no `Any` without justification. Use `Protocol` for interfaces, not `ABC` (structural typing over nominal).
13. **TEST COVERAGE** - 95% minimum, integration tests for all flows. Each strategy independently TDD-able with its own test file.
14. **SCHEMA VALIDATION** - Validate all external data at system boundaries.

### Design Patterns

- **Strategy Pattern** - Use for ALL language-aware handlers. Define a Protocol interface, implement per-language strategies, register in a registry. Handler delegates to strategies — zero language-specific logic in handlers.
- **Registry Pattern** - Map file extensions to strategies. Support config-filtered loading (only active project languages) with fallback to all strategies.
- **Test-Driven Development** - RED (failing test) → GREEN (minimal pass) → REFACTOR. Each strategy gets its own test file for independent TDD.

### When in Doubt

- Read the config, don't guess
- Fix the root cause, don't work around it
- Add tests first, then implement
- Validate with schemas, don't assume
- If you see an if/elif chain on type/language names, use Strategy Pattern instead
- If a handler has language-specific logic, it belongs in a strategy not the handler

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
  enforce_single_daemon_process: true  # Auto-enabled in containers
handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
project_handlers:
  enabled: true
  path: .claude/project-handlers
```

### Single Daemon Process Enforcement

**Purpose**: Prevents multiple daemon instances from running simultaneously.

**How it works**:
- **In containers** (YOLO mode, Docker, Podman): Kills ALL other daemon processes system-wide on startup
- **Outside containers**: Only cleans up stale PID files (safe for multi-project environments)
- **Auto-detection**: Configuration generation auto-enables this setting in container environments

**Configuration**:
```yaml
daemon:
  enforce_single_daemon_process: true  # Auto-enabled if container detected during init
```

**When to enable**:
- ✅ Container environments (auto-enabled)
- ✅ Single-user development machines
- ❌ Shared servers with multiple users/projects

**Behavior**:
- Container: Terminates all other `hooks-daemon` processes (SIGTERM → SIGKILL)
- Non-container: Only removes stale PID files for current project
- 2-second timeout for graceful shutdown before force kill

## QA Requirements

**MUST pass before commits:**
- Black (format), Ruff (lint), MyPy (types), Pytest (95% coverage), Bandit (security), shellcheck (shell scripts)
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
