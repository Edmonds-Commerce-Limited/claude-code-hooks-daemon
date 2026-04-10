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

| Operation              | Status                         |
| ---------------------- | ------------------------------ |
| `/release`             | ✅ ONLY CORRECT WAY            |
| `git tag v*`           | ❌ FORBIDDEN                   |
| `git push origin v*`   | ❌ FORBIDDEN                   |
| `git push origin tags` | ❌ FORBIDDEN                   |
| Edit CHANGELOG.md      | ❌ FORBIDDEN (outside release) |
| Edit RELEASES/\*.md    | ❌ FORBIDDEN (outside release) |

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

## ⚠️ CRITICAL: Dogfooding Bug Fixes (NON-NEGOTIABLE)

**This project dogfoods itself.** When you encounter ANY bug while using the daemon's own handlers, tools, or features during normal development work — **you MUST fix it immediately.**

### Rules

1. **Never ignore a dogfooding bug** — if a handler misfires, blocks the wrong thing, runs in the wrong directory, or produces incorrect output, that is a real bug affecting all users
2. **Fix before continuing** — stop your current task, fix the bug with TDD, run QA, commit, then resume your original work
3. **All handler behaviour is in scope** — blocking handlers, advisory handlers, context injection, status line — everything
4. **The daemon is not "someone else's problem"** — you ARE the upstream. There is no one else to report to
5. **Restart the daemon after every handler code change** — the daemon loads Python modules at startup; file edits are invisible until restarted. A handler that "passes unit tests" but never gets restarted is NOT dogfooded.

### Daemon Restart is Mandatory Dogfooding

**After every change to handler code, restart immediately:**

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: RUNNING
```

**When a handler doesn't fire as expected:**

1. Check the daemon is running the new code (restart if in doubt)
2. Use `nc` to probe the live daemon directly: `echo '{"hook_event_name":"Stop","stop_hook_active":false}' | /workspace/.claude/hooks/stop`
3. Check daemon logs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | tail -20`

**The "daemon running old code" failure mode is silent and common.** Unit tests pass, QA passes, but production behaviour is wrong because the daemon was never restarted. This is the #1 dogfooding failure mode.

### Why This Matters

- Every bug you encounter, users encounter too
- Handlers that misfire erode trust in the entire system
- Unfixed dogfooding bugs compound — one wrong cwd breaks three handlers
- The daemon running stale code creates phantom bugs that are invisible in tests

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

06. **FAIL FAST** - Detect errors early, validate at boundaries, explicit error handling. If something is wrong, crash immediately with a clear message — never silently continue.
07. **DRY** - Single source of truth for all logic. If you see the same pattern repeated, extract it. Common test directories, directory matching — shared utilities, not copy-paste.
08. **YAGNI** - Don't build for hypothetical futures. Implement what's needed now, design for extensibility through patterns (Strategy, Protocol), not through premature abstraction.
09. **NO MAGIC** - Zero magic strings or numbers. Every string literal and numeric value must be a named constant. `"/src/"` in an if-statement is magic — `_SOURCE_DIRECTORIES` tuple is not. Use constants modules, class constants, or module-level named tuples.
10. **SINGLE SOURCE OF TRUTH** - Config is truth, code reads config, never hardcode. Language configurations define language properties. Strategies define language behavior. Handlers orchestrate.
11. **PROPER NOT QUICK** - No workarounds, fix root causes. Three similar lines of code is better than a wrong abstraction, but six identical blocks means you need a proper pattern.
12. **TYPE SAFETY** - Full type annotations, strict mypy, no `Any` without justification. Use `Protocol` for interfaces, not `ABC` (structural typing over nominal).
13. **TEST COVERAGE** - 95% minimum, integration tests for all flows. Each strategy independently TDD-able with its own test file.
14. **SCHEMA VALIDATION** - Validate all external data at system boundaries.

### Design Patterns

- **Strategy Pattern** - Use for ALL language-aware handlers. Define a Protocol interface, implement per-language strategies, register in a registry. Handler delegates to strategies — zero language-specific logic in handlers.
- **Registry Pattern** - Map file extensions to strategies. Support config-filtered loading (only active project languages) with fallback to all strategies.
- **Test-Driven Development** - RED (failing test) → GREEN (minimal pass) → REFACTOR. Each strategy gets its own test file for independent TDD.

### Supported Languages

The following languages have strategy implementations across handler domains (QA suppression, security antipatterns, TDD, pipe blocker, lint-on-edit):

| Language              | Extensions                   | Strategy Domains                                  |
| --------------------- | ---------------------------- | ------------------------------------------------- |
| Python                | `.py`                        | QA suppression, Security, TDD, Pipe blocker, Lint |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx` | QA suppression, Security, TDD, Pipe blocker, Lint |
| PHP                   | `.php`                       | QA suppression, Security, TDD, Lint               |
| Go                    | `.go`                        | QA suppression, Security, TDD, Pipe blocker, Lint |
| Ruby                  | `.rb`                        | QA suppression, Security, TDD, Pipe blocker, Lint |
| Java                  | `.java`                      | QA suppression, Security, TDD, Pipe blocker, Lint |
| Kotlin                | `.kt`, `.kts`                | QA suppression, Security, TDD, Lint               |
| C#                    | `.cs`                        | QA suppression, Security, TDD, Lint               |
| Rust                  | `.rs`                        | QA suppression, Security, TDD, Pipe blocker, Lint |
| Swift                 | `.swift`                     | QA suppression, Security, TDD, Lint               |
| Dart                  | `.dart`                      | QA suppression, Security, TDD, Lint               |

Adding a new language: create a strategy class per domain, register in the domain's registry, add tests. Zero handler modifications needed.

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

- **0-9**: Test handlers (hello_world)
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

## Active Configuration

See @.claude/HOOKS-DAEMON.md for the current active handler summary, generated from live config.

**Regenerate**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`

**Config file**: `.claude/hooks-daemon.yaml`

Handler options (e.g. `blocking_mode`, `mode`): See **[docs/guides/HANDLER_REFERENCE.md](docs/guides/HANDLER_REFERENCE.md)** for the full per-handler options reference.

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

<hooksdaemon>
<!-- Auto-generated by hooks daemon on restart. Do not edit this section — changes will be overwritten. -->

## Hooks Daemon — Active Handler Guidance

The handlers listed below are active in this project. Read this section to avoid triggering unnecessary blocks.

## destructive_git — blocked git commands

The following git commands are permanently blocked and will always be denied:

| Command                  | Reason                                                                   |
| ------------------------ | ------------------------------------------------------------------------ |
| `git reset --hard`       | Permanently destroys all uncommitted changes                             |
| `git clean -f`           | Permanently deletes untracked files                                      |
| `git checkout -- <file>` | Discards all local changes to that file                                  |
| `git restore <file>`     | Discards local changes (`--staged` is allowed)                           |
| `git stash drop`         | Permanently destroys stashed changes                                     |
| `git stash clear`        | Permanently destroys all stashes                                         |
| `git push --force`       | Can overwrite remote history and destroy teammates' work                 |
| `git branch -D`          | Force-deletes branch without checking if merged (lowercase `-d` is safe) |
| `git commit --amend`     | Rewrites the previous commit — create a new commit instead               |

If the user needs to run one of these, ask them to do it manually. Do not attempt to work around the block.

**Safe alternatives**: `git stash` (recoverable), `git diff` / `git status` (inspect first), `git commit` (save changes permanently first).

## sed_blocker — sed is forbidden for file modification

`sed` is blocked because Claude gets sed syntax wrong and a single error can silently destroy hundreds of files with no recovery possible.

**Blocked**:

- `sed -i` / `sed -e` (in-place file editing via Bash tool)
- `grep -rl X | xargs sed -i` (mass file modification)
- Shell scripts (`.sh`/`.bash`) written via Write tool that contain `sed`

**Allowed** (read-only, no file modification):

- `cat file | sed 's/x/y/' | grep z` (pipeline transforming stdout only)
- `sed` mentioned in commit messages, PR bodies, or `.md` documentation files

**Use instead**:

- `Edit` tool — safe, atomic, verifiable
- Parallel Haiku agents with `Edit` tool for bulk changes across many files:
  1. Identify all files to update
  2. Dispatch one Haiku agent per file
  3. Each agent uses the `Edit` tool (never `sed`)

## absolute_path — always use absolute paths

The `Read`, `Write`, and `Edit` tools require absolute paths. Relative paths are blocked.

- **Correct**: `/workspace/src/main.py`, `/workspace/tests/test_utils.py`
- **Blocked**: `src/main.py`, `./config.yaml`, `../other/file.txt`

The working directory is `/workspace`. Prepend `/workspace/` to any relative path before calling these tools.

## error_hiding_blocker — error-suppression patterns are blocked

Writing code that silently swallows errors is blocked. All errors must be handled explicitly.

**Blocked patterns (examples)**:

- Python: bare `except` clauses with an empty body, catching and discarding all exceptions
- Shell: redirecting stderr to `/dev/null` to silence failures, `|| true` to suppress non-zero exit codes
- JavaScript/TypeScript: empty `catch` blocks that swallow exceptions
- Go: `_ = err` (discarding error return values without handling)

**Required action**: Handle errors explicitly — log them, return them to the caller, or propagate them. Silent error suppression masks bugs and makes debugging impossible.

## security_antipattern — OWASP security antipatterns are blocked

Writing code that contains security antipatterns is blocked across all supported languages. Fix the code to use safe patterns instead.

**Blocked categories**:

- SQL injection: building queries via string concatenation (use parameterised queries)
- Command injection: passing unvalidated input to subprocess (use argument lists)
- Hardcoded credentials: API keys, passwords, tokens embedded in source code
- Weak cryptography: MD5 or SHA1 for password hashing (use bcrypt/argon2)
- Path traversal: unvalidated user input used in file paths

**Supported languages**: Python, JavaScript/TypeScript, Go, PHP, Ruby, Java, Kotlin, C#, Rust, Swift, Dart.

## worktree_file_copy — do not copy files between worktrees and the main repo

`cp`, `mv`, and `rsync` operations that move files from a worktree directory (`untracked/worktrees/` or `.claude/worktrees/`) into the main repo (`src/`, `tests/`, `config/`) — or vice versa — are blocked.

Worktrees are isolated branches. Cross-copying corrupts that isolation and can silently overwrite in-progress work.

**Allowed**: operations within the same worktree branch. **To merge changes**: use `git merge` or `git cherry-pick` instead.

## curl_pipe_shell — never pipe curl/wget to bash/sh

Piping network content directly to a shell is blocked. It executes untrusted remote code without any inspection.

**Blocked**: `curl URL | bash`, `curl URL | sh`, `wget URL | bash`, `curl URL | sudo bash`

**Safe alternative**: download first, inspect, then execute:

```
curl -o /tmp/script.sh URL
cat /tmp/script.sh          # inspect
bash /tmp/script.sh         # execute if safe
```

### Pipe Blocker

Commands piped to `tail` or `head` are **blocked** — piping truncates output and causes information loss.

**Use a temp file instead:**

```bash
# WRONG — blocked:
pytest tests/ 2>&1 | tail -20

# RIGHT — redirect to temp file:
pytest tests/ > /tmp/pytest_out.txt 2>&1
# Then read selectively if needed
```

**Allowed** (whitelisted): `grep`, `rg`, `awk`, `sed`, `jq`, `ls`, `cat`, `git log`, `git tag`, `git branch`, and other cheap filtering commands.

**Add to whitelist** (if safe to pipe): set `extra_whitelist` in `.claude/hooks-daemon.yaml` under `pipe_blocker`.

## dangerous_permissions — chmod 777 is blocked

`chmod 777` and other world-writable permission commands are blocked. Overly permissive file permissions are a security vulnerability.

**Blocked**: `chmod 777`, `chmod 666`, `chmod a+w`, `chmod o+w`

**Use least-privilege permissions instead**:

- Executable scripts: `chmod 755` (owner rwx, group/other rx)
- Regular files: `chmod 644` (owner rw, group/other r)
- Private files: `chmod 600` (owner rw only)

## git_stash — git stash is advisory by default

`git stash`, `git stash push`, and `git stash save` trigger this handler. `git stash pop`, `git stash apply`, `git stash list`, and `git stash show` are always allowed.

**Default mode** (`warn`): stash is allowed but an advisory message explains risks.
**Deny mode** (`deny`): stash is blocked — use `git commit` to checkpoint work instead.

Configure via `handlers.pre_tool_use.git_stash.options.mode: deny` to enforce the stricter policy.

## lock_file_edit_blocker — never directly edit lock files

Direct `Write` or `Edit` to package manager lock files is blocked. Lock files are generated artifacts; manual edits create checksum mismatches and broken dependency graphs.

**Blocked files**: `composer.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Gemfile.lock`, `Cargo.lock`, `go.sum`, `Package.resolved`, `Pipfile.lock`, and others.

**Use package manager commands instead**:

- PHP: `composer install` / `composer require package`
- Node: `npm install` / `yarn add package`
- Ruby: `bundle install` / `bundle add gem`
- Rust: `cargo add crate`
- Go: `go get module`

## daemon_restart_verifier — restart the daemon before committing

Before making a `git commit` in the hooks daemon repository, this handler advises verifying that the daemon can restart successfully with the current code changes. This is advisory — it adds context but does not block the commit.

**Why**: Unit tests alone don't catch import errors. A handler that fails to import silently disables protection without any test-time error. Daemon restart is the definitive check.

**Run before committing** (in this repo only):
`$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` then verify status shows RUNNING.

## qa_suppression — QA suppression annotations are blocked

Writing QA suppression directives into source files is blocked across all supported languages. Fix the underlying code issue instead.

**Blocked annotation types (by language)**:

- Python: `noqa` directives, `type: ignore` annotations
- JavaScript/TypeScript: `eslint-disable` inline directives
- Go: `nolint` directives (golangci-lint)
- PHP: `phpstan-ignore`, `psalm-suppress` annotations
- Java/Kotlin: `@SuppressWarnings`, `@Suppress` annotations
- C#: `pragma warning disable` directives
- Rust: `allow(clippy::...)` attributes on type-level items

**Required action**: Fix the code so QA passes without suppression. If a suppression is genuinely necessary, ask the user to add it manually — this signals a conscious decision rather than a shortcut.

## tdd_enforcement — test file must exist before source file

Creating a production source file is blocked until a corresponding test file exists.

**TDD workflow (required)**:

1. Create the **test file first** (e.g. `tests/unit/handlers/test_my_handler.py`)
2. Write failing tests — RED phase
3. Create the source file and implement until tests pass — GREEN phase
4. Refactor — REFACTOR phase

**Supported languages**: Python, Go, JavaScript/TypeScript, PHP, Rust, Java, C#, Kotlin, Ruby, Swift, Dart

**Test file locations checked** (any satisfies the block):

- Separate mirror: `tests/unit/{subdir}/test_{module}.py`
- Collocated: `{source_dir}/{module}.test.ts` (JS/TS projects)
- Test subdirectory: `{source_dir}/__tests__/{module}.test.ts`

**Allowed through without blocking**: vendor dirs, node_modules, build outputs, generated files, and file extensions not in the supported language list.

## lsp_enforcement — use LSP tools for code symbol lookups

Using `Grep` or `Bash` (grep/rg) to find class definitions, function signatures, or symbol references is blocked or redirected to LSP tools, which are faster and semantically accurate.

**Prefer LSP tools for**:

- Finding where a class or function is defined → `goToDefinition`
- Finding all usages of a symbol → `findReferences`
- Getting type information or documentation → `hover`
- Listing all symbols in a file → `documentSymbol`
- Searching symbols across the project → `workspaceSymbol`

**Grep/Bash grep is still appropriate for**: text patterns in content, log searching, finding strings in config files.

Default mode (`block_once`): the first symbol-lookup grep in a session is denied with guidance; subsequent retries are allowed.

## gh_issue_comments — always include --comments on gh issue view

`gh issue view` without `--comments` is blocked. Issue comments often contain critical context, clarifications, and updates not in the issue body.

**Blocked**: `gh issue view 123`, `gh issue view 123 --repo owner/repo`

**Allowed**: `gh issue view 123 --comments`, `gh issue view 123 --json title,body,comments`

If using `--json`, include `comments` in the field list instead of adding `--comments`.

## npm_command — use llm: prefixed npm commands

Direct `npm run` and `npx` commands are blocked or advised against. Projects with `llm:` prefixed scripts in `package.json` should use those instead.

**Why**: `llm:` commands are configured for LLM-friendly output (no spinners, no colour codes, structured results).

**Example**: Use `npm run llm:build` instead of `npm run build`.

If no `llm:` commands exist in `package.json`, the handler operates in advisory mode (warns but does not block).

## markdown_organization — markdown files must go in allowed locations

Writing a new `.md` file to an unrecognised location is blocked. Markdown files must be placed in project-configured allowed paths.

**Common allowed locations**: `CLAUDE/`, `docs/`, `RELEASES/`, `CLAUDE/Plan/`, root-level `README.md`, or any path matching the `allowed_markdown_paths` config.

**Plan file redirection**: when `track_plans_in_project` is enabled, Claude Code planning mode writes are automatically redirected to the project's `CLAUDE/Plan/` directory. Plan folders must follow the `NNNN-description/` naming convention.

If you need a markdown file in a new location, add a pattern to `allowed_markdown_paths` in `.claude/hooks-daemon.yaml`.

## validate_instruction_content — CLAUDE.md and README.md must have stable content

Writing ephemeral or session-specific content to `CLAUDE.md` or `README.md` is blocked. These files should contain only stable instructions, not implementation logs or session state.

**Blocked content types**:

- Timestamps and ISO dates
- Status emoji followed by completion words (e.g. checkmark + 'Done')
- Implementation log sentences ('created the file X', 'added the class Y')
- Test output counts ('3 tests passed')
- LLM summary section headings ('## Summary', '## Key Points')

Content inside markdown code blocks is exempt from validation.

## markdown_table_formatter — markdown tables are auto-aligned

After every `Write` or `Edit` of a `.md` or `.markdown` file, the content is re-formatted via `mdformat + mdformat-gfm` so that table pipes are aligned and column widths are consistent. The handler is non-terminal and advisory — it never blocks, it just rewrites the file on disk.

**What changes:**

- Table pipes are aligned vertically and delimiter rows widened to match cell widths.
- Ordered lists keep consecutive numbering (`1.` `2.` `3.`).
- `---` thematic breaks are preserved (mdformat's 70-underscore default is post-processed back).
- Asterisks in table cells are escaped (`*` → `\*`) as required by GFM.

**Ad-hoc formatting of existing files:**

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>
```

### Stop Explanation Required

Before stopping, **prefix your final message** with `STOPPING BECAUSE:` followed by a clear reason:

```
STOPPING BECAUSE: all tasks complete, QA passes, daemon restart verified.
```

**Why**: The stop hook enforces intentional stops. Stopping without an explanation triggers an auto-block that asks you to explain or continue.

**Alternatives**:

- `STOPPING BECAUSE: <reason>` — stops cleanly with explanation
- Continue working — no need to stop unless all work is genuinely complete

**Do NOT**:

- Stop mid-task without explanation
- Ask confirmation questions and then stop (the hook auto-continues those)
- Use `AUTO-CONTINUE` unless you intend to keep working indefinitely

**Before asking a question, evaluate it critically**:

- Tautological/rhetorical questions with obvious answers ("Should I continue?", "Would you like me to proceed?") — do NOT ask, just do it
- Errors with a clear next step ("The test failed, should I fix it?") — do NOT ask, just fix it
- Genuine choice questions where all options are valid ("Which of A, B, or C should we use?") — these deserve a response. Use `STOPPING BECAUSE: need user input` and ask your question

</hooksdaemon>
