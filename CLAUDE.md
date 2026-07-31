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
   - ALL 10 checks must pass (Magic Values, Format, Lint, Type Check, Tests, Security, Dependencies, Error Hiding, Skill References, Smoke Test)
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

## ⚠️ CRITICAL: Report Handling (NON-NEGOTIABLE)

**Reports never linger in `untracked/`.** Bug reports, audit reports, and
investigation write-ups dropped into `untracked/` are transient — leaving them
there lets stale analysis rot silently and pile up. Every report has exactly
two fates:

1. **Clean it up** — once the work it describes is done (fixed, committed,
   pushed), delete the report. Git history + regression tests + commit messages
   are the durable record.
2. **Track it properly** — if the report has lasting reference value, move it
   into the **relevant plan folder** (`CLAUDE/Plan/NNNNN-*/`) as a supporting
   doc and commit it, so it lives in tracked source, not scratch space.

Do NOT leave a report sitting in `untracked/` after acting on it. When in
doubt, prefer tracking it in a plan folder over deletion — but never leave it
in limbo.

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

### Batched Tool Calls Are Cancelled If One Is Blocked

**Footgun**: Claude Code runs a turn's tool calls together; if a hook **denies** one, it **cancels every sibling call** in that turn — batched `Edit`/`Write`/commits are silently lost, not retried. Never batch a mutating `Edit`/`Write`/`git commit` in the same turn as a `Bash` command a hook might block (`sed`, pipe to `head`/`tail`, etc.). Issue mutating calls one per turn and verify each landed; if a block warns that siblings were cancelled, re-issue them separately.

## Plans (Development Work Tracking)

**Purpose**: Track development work in numbered folders (`CLAUDE/Plan/00001-`, `00002-`, etc.)

**Documentation**: [docs/PLAN_SYSTEM.md](../docs/PLAN_SYSTEM.md)

**Structure**: Numbered folders with `PLAN.md` files containing tasks, goals, status

**Lifecycle**: Not Started → In Progress → Complete (moved to `Completed/`)

**Optional Handlers**:

- `markdown_organization` - Enforces CLAUDE/Plan/ structure
- `plan_completion_advisor` - Reminds to move completed plans to Completed/

**When to Use**: Work taking > 2 hours, multi-phase implementation, architectural decisions

---

## ⚠️ Self-Install Mode (CRITICAL)

**This project dogfoods itself** - it runs from workspace root, not `.claude/hooks-daemon/`.

### Key Paths (Different from Normal Installs)

```bash
# Python command (fingerprint-keyed venv from v3.7.0; project-path slug from v3.19.1)
# Resolve dynamically via init.sh / venv-include.bash — the venv dir is keyed by a
# project-path slug plus a fingerprint of the Python version, base_prefix, and arch.
PYTHON=/workspace/untracked/venv-{slug}-py{MM}-{fingerprint}/bin/python

# Legacy (pre-v3.7.0) — still works as fallback if present
PYTHON=/workspace/untracked/venv/bin/python

# Config
CONFIG=/workspace/.claude/hooks-daemon.yaml

# Source code runs from workspace
SRC=/workspace/src/claude_code_hooks_daemon/
```

### Why This Matters

- Venv is keyed by a project-path slug plus a fingerprint:
  `/workspace/untracked/venv-{slug}-py{MM}-{fingerprint}/`
  where `{fingerprint} = md5(sys.version | sys.base_prefix | platform.machine())[:8]`
  and `{slug}` is derived from the project root path. The fingerprint lets
  concurrent containers from the same image reuse one venv; the slug keeps a
  desktop host view (e.g. `/home/user/project`) and a container view
  (`/workspace`) of the SAME bind-mounted project on separate venvs — so two
  sessions sharing an `untracked/` directory never collide on one venv even
  when their Python fingerprints are identical (fixed in v3.19.1).
- Source at `/workspace/src/` (NOT installed package)
- Config has `self_install_mode: true`
- `.claude/hooks-daemon.env` sets `HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`
- Inspect/manage venvs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli list-venvs`
  and `prune-venvs --legacy | --all-except-current` (never deletes current fingerprint)

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

**How It Works**: Resolves a STABLE hostname in series — `HOSTNAME` env var, then the OS hostname (`socket.gethostname()` / the `hostname` command), then the constant `localhost` — and uses it directly as the suffix. The Python daemon (`daemon/paths.py:resolve_hostname`) and the bash forwarder (`init.sh:_get_hostname_suffix`) use the same series so they always agree on the socket/PID path.

**Why not the env var alone**: `HOSTNAME` is a bash-on-Linux convenience variable. It is unset on macOS (zsh) and many minimal containers / CI images. Falling back to the OS hostname (never a time-based hash) keeps the suffix deterministic so `start`, `status`, and `stop` all compute the same path.

**Path Pattern**:

- With hostname (env or OS): `.claude/hooks-daemon/untracked/daemon-{hostname}.{sock,pid,log}`
- No hostname at all (OS hostname empty): `…/daemon-localhost.{sock,pid,log}`

**Sanitization**: Hostname is lowercased and spaces replaced with hyphens for filesystem safety.

**Environment Overrides**: `CLAUDE_HOOKS_SOCKET_PATH`, `CLAUDE_HOOKS_PID_PATH`, `CLAUDE_HOOKS_LOG_PATH` take precedence.

**Examples**:

```bash
# Hostname used directly as suffix
HOSTNAME=laptop → daemon-laptop.sock
HOSTNAME=506355bfbc76 → daemon-506355bfbc76.sock
HOSTNAME=prod-server-01 → daemon-prod-server-01.sock
HOSTNAME="My Server" → daemon-my-server.sock (sanitized)

# No HOSTNAME (e.g. macOS): falls back to the OS hostname, deterministically
unset HOSTNAME → daemon-work.local.sock   # from socket.gethostname() / `hostname`
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

- **In containers** (YOLO mode, Docker, Podman, LXC/LXD): Kills other daemon processes **serving the same project root** on startup. Daemons serving a different project root are never touched — this is critical when PID namespaces are shared between a container and its host (or between containers sharing a bind-mounted `untracked/`), where a system-wide kill would otherwise terminate an unrelated project's daemon.
- **Outside containers**: Only cleans up stale PID files (safe for multi-project environments)
- **Auto-detection**: Configuration generation auto-enables this setting in container environments
- **Project scoping**: A candidate daemon's project root is derived from its `--project-root` flag or the venv path embedded in its interpreter. A daemon whose project root cannot be positively determined is left running (fail-safe against cross-project termination).

**Parallel sessions share one daemon (Plan 00127)**: Multiple Claude Code processes that resolve the same `(hostname, project root)` — e.g. several agents in a single container, or a host + a container sharing a bind-mounted `untracked/` — deliberately **share one daemon**. A second start that finds a live, healthy incumbent **reuses** it (exits 0, leaves the incumbent's socket and PID file untouched) rather than stealing the socket. The start sequence probes socket liveness before touching anything and holds an exclusive lock across the probe → bind critical section, so a live socket is never unlinked and two near-simultaneous starts cannot orphan each other. Enforcement (above) therefore only ever reaps genuinely stale/duplicate daemons — a healthy incumbent owning the current socket is always spared. To give a session its own isolated daemon instead, set `CLAUDE_HOOKS_SOCKET_PATH` / `CLAUDE_HOOKS_PID_PATH` / `CLAUDE_HOOKS_LOG_PATH`.

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

- Container: Terminates **stale/duplicate** `hooks-daemon` processes serving the same project root (SIGTERM → SIGKILL); spares a healthy incumbent that owns the current socket (reused, not killed); leaves other projects' daemons alone
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
- **CLAUDE/development/LESSONS.md** - Durable engineering & process lessons
- **examples/project-handlers/** - Example project handlers with tests
- **RELEASES/** - Version release notes
- **CONTRIBUTING.md** - Contribution guidelines

<hooksdaemon>
<!-- Auto-generated by hooks daemon on restart. Do not edit this section — changes will be overwritten. -->

## Hooks Daemon — Active Handler Guidance

The handlers listed below are active in this project. Read this section to avoid triggering unnecessary blocks.

**When a tool is blocked by a handler, do not stop working.** Read the block reason, modify your approach, and continue with your task.

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

## daemon_location_guard — do not cd into .claude/hooks-daemon/

Bash commands that change directory into `.claude/hooks-daemon/` (or `cd` into a daemon-internal subdirectory and then run something) are blocked. The daemon is an upstream dependency that must remain untouched in client repos.

**Run daemon CLI from the project root instead** — it always works regardless of cwd:

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

If you need to inspect daemon source for debugging, use `Read` from the project root with the absolute path — never `cd` in. Do NOT edit anything inside `.claude/hooks-daemon/`; changes will be overwritten on the next upgrade.

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

**Excluded paths**: vendor/, node_modules/, and test-fixture dirs (tests/fixtures/, tests/assets/, __fixtures__/) are skipped by default. Exempt more paths with glob patterns via `handlers.pre_tool_use.error_hiding_blocker.options.exclude_paths` or the project-wide `daemon.exclude_paths` — use these for fixtures of deliberately-broken code instead of disabling the handler.

## security_antipattern — OWASP security antipatterns are blocked

Writing code that contains security antipatterns is blocked across all supported languages. Fix the code to use safe patterns instead.

**Blocked categories**:

- SQL injection: building queries via string concatenation (use parameterised queries)
- Command injection: passing unvalidated input to subprocess (use argument lists)
- Hardcoded credentials: API keys, passwords, tokens embedded in source code
- Weak cryptography: MD5 or SHA1 for password hashing (use bcrypt/argon2)
- Path traversal: unvalidated user input used in file paths

**Supported languages**: Python, JavaScript/TypeScript, Go, PHP, Ruby, Java, Kotlin, C#, Rust, Swift, Dart.

**Excluded paths**: vendor/, node_modules/, and test fixtures are skipped by default. Exempt more paths with glob patterns via `handlers.pre_tool_use.security_antipattern.options.exclude_paths` or the project-wide `daemon.exclude_paths`.

## worktree_file_copy — do not copy files between worktrees and the main repo

`cp`, `mv`, and `rsync` operations that move files from a worktree directory (`untracked/worktrees/` or `.claude/worktrees/`) into the main repo (`src/`, `tests/`, `config/`) — or vice versa — are blocked.

Worktrees are isolated branches. Cross-copying corrupts that isolation and can silently overwrite in-progress work.

**Allowed**: operations within the same worktree branch. **To merge changes**: use `git merge` or `git cherry-pick` instead.

## root_recursion_guard — recursive scans rooted at / are blocked

A recursive scanner whose path argument resolves to a catastrophic root location is blocked, because it walks the entire filesystem and can pin every CPU core for hours.

**Blocked** (recursive scanner + dangerous root path):

- `grep -r`/`-R`/`-rl`, `ugrep -r`, `rgrep`, `find`, `fd`/`fdfind`, `rg`
- pointed at `/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`

**Allowed**: the same scanners scoped to the project — `rg -l "x" /workspace`, `grep -rl "x" "$CLAUDE_PROJECT_DIR"`, `grep -rl x src/`, `find . -name y`. Non-recursive `grep x /etc/hosts` is not affected.

**Note**: `... | head` does NOT bound a `-l`/`-rl` scan — a producer that matches nothing never writes, so it never receives SIGPIPE and runs to completion across the whole disk.

**Escape hatch** (rare legitimate whole-disk scan):

```
MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /
```

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

**Do NOT do the theatre** of capturing output to a file and then echoing the WHOLE file to stdout — that defeats the point and just bloats tokens.

**Preferred — `echd-capture`**: capture the FULL output, see only a preview. When the block fires it prints the exact invocation to use — an ABSOLUTE path to the deployed helper, not a bare name — so copy the path from the block message (the helper is not guaranteed to be on `PATH`). If no helper path can be resolved, the block recommends the temp-file redirect below instead.

```bash
# WRONG — blocked (and truncates):
pytest tests/ 2>&1 | tail -20

# RIGHT — full capture, bounded preview + path to the rest. Use the ABSOLUTE
# echd-capture path from the block message (shown here as /…/scripts/echd-capture):
set -o pipefail
pytest tests/ 2>&1 | /…/scripts/echd-capture 20
# prints the last 20 lines + '(full output: /…/command-output-….txt)'.
# Use --head N for the first N lines. pipefail keeps pytest's exit code visible.
```

**Always-works alternative** (no helper, no pipe): `pytest tests/ > /tmp/out.txt 2>&1` then read the file selectively.

**Allowed** (whitelisted): `grep`, `rg`, `awk`, `sed`, `jq`, `ls`, `cat`, `git log`, `git tag`, `git branch`, and other cheap filtering commands.

**Add to whitelist** (if safe to pipe): set `extra_whitelist` in `.claude/hooks-daemon.yaml` under `pipe_blocker`.

## dangerous_permissions — chmod 777 is blocked

`chmod 777` and other world-writable permission commands are blocked. Overly permissive file permissions are a security vulnerability.

**Blocked**: `chmod 777`, `chmod 666`, `chmod a+w`, `chmod o+w`

**Use least-privilege permissions instead**:

- Executable scripts: `chmod 755` (owner rwx, group/other rx)
- Regular files: `chmod 644` (owner rw, group/other r)
- Private files: `chmod 600` (owner rw only)

## git_stash — git stash is blocked by default

`git stash`, `git stash push`, and `git stash save` are blocked. `git stash pop`, `git stash apply`, `git stash list`, and `git stash show` are always allowed.

**Why**: stashes get forgotten, lost, and block `git pull`. Use `git commit -m 'WIP: ...'` instead — WIP commits are acceptable.

**Escape hatch** (when commit truly won't work):

```
MUST_STASH_BECAUSE="explain why"; git stash
```

Configure via `handlers.pre_tool_use.git_stash.options.mode: warn` for advisory-only mode.

## lock_file_edit_blocker — never directly edit lock files

Direct `Write` or `Edit` to package manager lock files is blocked. Lock files are generated artifacts; manual edits create checksum mismatches and broken dependency graphs.

**Blocked files**: `composer.lock`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Gemfile.lock`, `Cargo.lock`, `go.sum`, `Package.resolved`, `Pipfile.lock`, and others.

**Use package manager commands instead**:

- PHP: `composer install` / `composer require package`
- Node: `npm install` / `yarn add package`
- Ruby: `bundle install` / `bundle add gem`
- Rust: `cargo add crate`
- Go: `go get module`

## pip_break_system — --break-system-packages is blocked

`pip install --break-system-packages` (and the `pip3` / `python -m pip` / `python3 -m pip` variants) is blocked. The flag bypasses PEP 668 system-package protection and corrupts the system Python environment in containers and on modern Linux distros.

**Use a virtualenv or `--user` install instead**:

```
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <package>
# or
pip install --user <package>
```

If a tool's installer insists on `--break-system-packages` (some quick-start scripts do), download it first, inspect, and run it inside a venv — do not shortcut by adding the flag.

## sudo_pip — sudo pip install is blocked

`sudo pip install` (and the `sudo pip3` / `sudo python -m pip` / `sudo python3 -m pip` variants) is blocked. Installing as root corrupts the system Python managed by the OS package manager and creates permission/ownership issues that are painful to recover from.

**Use a virtualenv or `--user` install instead**:

```
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <package>
# or
pip install --user <package>
```

Even in a container running as root, `sudo` adds nothing — drop it and use a venv.

## ask_user_question_blocker — questions need `ASKING BECAUSE:` justification

AskUserQuestion calls are only allowed when every `question` string begins with `ASKING BECAUSE:` (case-sensitive, leading whitespace OK). The convention mirrors the Stop handler's `STOPPING BECAUSE:` pattern — explicit declared intent gates the privilege of pausing the session.

**Before asking, evaluate critically**:

- Tautological/rhetorical questions with one obvious answer ("Should I continue?", "Would you like me to proceed?") — do NOT ask. State the question and your assumed-correct answer in plain output text and proceed. The user is watching and will interrupt if the assumption is wrong.
- Questions whose options reduce to **good vs. bad** are tautological — the answer is always the good option. Examples: best practice vs. bodge, increasing vs. decreasing code quality, delivering the requirement vs. not delivering it, fixing the failing test vs. leaving it broken, following project conventions vs. inventing your own. Do NOT ask; pick the good option and proceed.
- Errors with a clear recovery path ("Should I fix the failing test?") — do NOT ask. Fix it.
- Genuine choice questions where you cannot resolve the answer from context — these are the legitimate use case. Prefix every question text with `ASKING BECAUSE: <one-line reason you cannot decide>` so the daemon allows the call through.

**Audit log pattern** (preferred for tautological questions):

```
I would normally ask: <question>.
Assumed answer: <your assumption>.
Proceeding on that basis; the user will interrupt if wrong.
```

**Escape hatch** (genuine ambiguity): prefix every question text with `ASKING BECAUSE: <reason>`. Mixing prefixed and non-prefixed questions in one call still triggers a block — prefix all or none.

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
- Rust: `allow(...)` attributes anywhere in the file (item-level `#[allow(...)]` and crate-level `#![allow(...)]`)

**Required action**: Fix the code so QA passes without suppression. If a suppression is genuinely necessary, ask the user to add it manually — this signals a conscious decision rather than a shortcut.

**Excluded paths**: per-language vendor/build/node_modules dirs are skipped by default. Exempt more paths with glob patterns via `handlers.pre_tool_use.qa_suppression.options.exclude_paths` or the project-wide `daemon.exclude_paths` — use these for fixtures that must contain suppression annotations.

## plan_number_helper — use `mkplan.bash` to create a plan

**To create a new plan, run the deployed scaffolding script:**

```
CLAUDE/Plan/mkplan.bash "descriptive-kebab-name"
```

(Use the project's configured plan directory if it is not `CLAUDE/Plan/`.) The script takes a lock, reads the same authoritative git counter (`hooksdaemon.latestPlanNumber`), assigns the next number atomically, creates the `NNNNN-name/` folder, scaffolds `PLAN.md`, and advances the counter — so concurrent runs can never collide on a number. It prints the new folder path on stdout. You still add the README index row yourself (the script reminds you).

**If you only need the *number* (not a folder)**, read the counter and add 1 — this is the fallback, not the primary path:

```
git config --local hooksdaemon.latestPlanNumber
```

Add 1 to that value (zero-pad to 5 digits, e.g. counter `117` → next plan `00118`). The git counter is the source of truth; the daemon keeps it correct across branches.

**Do NOT** scan `CLAUDE/Plan/` with `ls`/`find`/glob pipelines to discover the next number. Folder scans miss plans in `Completed/` and other subdirectories, and disagree across branches. The folder scan is only used to bootstrap the counter when the git key is unset (which `mkplan.bash` and the daemon both handle).

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

## gh_pr_comments — always include --comments on gh pr view

`gh pr view` without `--comments` is blocked. PR comments often contain review feedback, reviewer requests, and decisions not in the PR body.

**Blocked**: `gh pr view 123`, `gh pr view 123 --repo owner/repo`

**Allowed**: `gh pr view 123 --comments`, `gh pr view 123 --json title,body,comments`

If using `--json`, include `comments` in the field list instead of adding `--comments`.

## plan_qa_commit_gate — cross-file plan checks at git commit

Every `git commit` is checked against the STAGED tree's plan QA
invariants. In `commit_gate_mode: warn` (the rollout default)
violations appear as advisory context — read them and amend the
commit content BEFORE committing; in `block` mode they deny the
commit with a TODO list of what the commit must also contain.

**The invariants**:

- creating a plan folder ⇒ the SAME commit stages its README
  index row (`index-at-birth`) and the number must come from the
  git counter / mkplan.bash (`counter-sanity`, `no-new-collisions`)
- flipping a plan to Complete/Cancelled/Superseded ⇒ the SAME
  commit contains the `git mv` into the archive dir AND the README
  row + statistics update (`terminal-state-atomic`)
- every folder has a README row in the section matching its
  location, and every row's link resolves
  (`row-folder-bijection`, `stats-recount`)
- a commit claiming `Plan NNNNN` that stages src/tests/config
  changes should also update that plan's PLAN.md
  (`same-commit-plan-doc`); reference plans as `Plan NNNNN:`
  (`plan-ref-format`)
- (advise-only, Plan 00163) a commit that changes a plan's PLAN.md
  tasks should stage a `JOURNAL/` entry recording what changed
  (`journal-entry-with-progress`); a terminal-status flip should
  stage a closing journal entry when
  `plan_workflow.qa.journal.enforce_on_completion` is on
  (`journal-completion-entry`)

Check the staged tree any time without committing:
`$PYTHON -m claude_code_hooks_daemon.daemon.cli plan-qa --check-staged`.
Commits inside nested/vendor repos or foreign worktrees are exempt.

## plan_qa_edit — PLAN.md writes are linted in real time

Every Write/Edit of a `PLAN.md` under the plan directory is checked
against the plan QA edit-stage rules on the content the file WOULD
have. Block-level violations (in `edit_mode: block`) deny the tool
call with the exact remediation; fix the content and retry.

**Rules that block new plan material**:

- a parseable `**Status**:` line must exist (`status-line-present`)
- the status token must be one of: Not Started, In Progress,
  Complete, Blocked, Cancelled, Superseded, Dormant
  (`status-enum-and-date`)
- the header must not contradict the body — do not leave
  `Not Started`/`In Progress` above an all-ticked task list or
  "ALL DONE" prose; flip the status instead
  (`header-body-coherence`)
- use the template task grammar `- [ ] ⬜ **Task N.N**:` — not
  ad-hoc markers like `[✓]`/`[⏳]` (`task-grammar`)

**Advisory rules**: missing Created/Owner/Priority headers on new
plans; a terminal status set while the folder is still in the plan
root (the same commit must `git mv` it to the archive dir and
update the README row); edits to archived plans; backticked
`src/...` paths that no longer exist.

**Journal day-files** (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`) are also
linted (all ADVISE): the name must match the grammar and the
enclosing plan number with a today/yesterday date
(`journal-dayfile-naming`), and edits must APPEND — never rewrite or
remove earlier entries (`journal-append-only`). Corrections are new
dated entries at the bottom, not edits to old ones.

Grandfathered plans in `plan_workflow.qa.legacy_plan_allowlist`
only ever advise. Lint any file on demand:
`$PYTHON -m claude_code_hooks_daemon.daemon.cli plan-qa --lint <file>`.

## plan_time_estimates — plans describe WHAT, not WHEN

Writing time estimates into a plan document is blocked — that is any `CLAUDE/Plan/**/*.md` EXCEPT journal day-files. Plans capture the work to be done, not how long it will take.

**Journal day-files (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`) are exempt.** A journal records what actually happened, so an elapsed duration there is a historical fact, not a forward estimate.

**Blocked in plan documents:**

- Effort estimates — `**Estimated Effort**: 4 hours`, `Total Estimated Time: 2 days`
- Per-phase durations — `Phase 1: ... (3 days)`, `takes 8-12 hours`
- Target/completion dates — `**Target Completion**: 2026-06-30`, `Completion: 2026-06-30`
- `ETA:`, `timeline:`, `deadline:`, `due date:` lines

**Instead:** break work into concrete tasks and implementation steps, and let the user decide scheduling. Technical durations that describe a feature (cache TTL, session timeout, retention window) are allowed — only work/effort estimates are blocked.

## npm_command — use llm: prefixed npm commands

Direct `npm run` and `npx` commands are blocked or advised against. Projects with `llm:` prefixed scripts in `package.json` should use those instead.

**Why**: `llm:` commands are configured for LLM-friendly output (no spinners, no colour codes, structured results).

**Example**: Use `npm run llm:build` instead of `npm run build`.

If no `llm:` commands exist in `package.json`, the handler operates in advisory mode (warns but does not block).

## markdown_organization — tracked-docs policy (untracked Claude memory BLOCKED)

This project sets `allow_untracked_claude_memory: false`. Writing to Claude
auto-memory files (`~/.claude/projects/*/memory/*.md`) is **blocked** — via the
Write/Edit tools AND via bash redirect/`tee` side-doors. **Reading memory is
still allowed** so existing memory can be migrated out.

**Put durable knowledge in TRACKED project docs (progressive disclosure):**

- Always-relevant facts → `CLAUDE.md` (keep lean; resident every session)
- Path-specific guidance → `.claude/rules/*.md` with `paths:` glob frontmatter (loads on demand only when matching files are touched)
- Intent-triggered procedures → a thin skill under `.claude/skills/` pointing at a single-source-of-truth doc body
- Human-facing reference → `docs/`
- Link docs with plain markdown links (zero token cost until followed); **avoid `@`-imports** (they re-inline eagerly rather than defer)

Keep ONE source of truth per fact and link to it. Normal markdown-location rules (below) still apply to every other `.md` file.

**Allowed locations**: `CLAUDE/`, `docs/`, `RELEASES/`, `CLAUDE/Plan/`, root-level `README.md`, `.claude/rules/`, or any `extra_allowed_markdown_paths` pattern.

## validate_instruction_content — CLAUDE.md and README.md must have stable content

Writing ephemeral or session-specific content to `CLAUDE.md` or `README.md` is blocked. These files should contain only stable instructions, not implementation logs or session state.

**Blocked content types**:

- Timestamps and ISO dates
- Status emoji followed by completion words (e.g. checkmark + 'Done')
- Implementation log sentences ('created the file X', 'added the class Y')
- Test output counts ('3 tests passed')
- LLM summary section headings ('## Summary', '## Key Points')

Content inside markdown code blocks is exempt from validation.

## git_hooks_executable_fixer — auto-fixes non-executable git hooks

When a git command prints `hint: The '...' hook was ignored because it's not set as executable`, this handler automatically `chmod +x`s every non-`.sample` file in the repository's hooks directory (resolved via `git rev-parse --git-path hooks`, so worktrees and `core.hooksPath` are handled). Execute bits are added with least privilege (only where read is already granted). It never blocks the command and reports which hooks it fixed via advisory context. `.sample` files and already-executable hooks are left untouched.

## background_process_tracker — backgrounded processes are tracked

A PostToolUse advisory that fires when a Bash call backgrounds a process (`run_in_background: true`, or a `&`/`nohup`/`setsid`/`disown` command). It records the command to `background-processes.jsonl` and injects rate-limited guidance.

**The daemon never kills.** It surfaces runaways; you decide.

When you background a long-lived process:

- Create a non-durable recurring **watchdog cron** (CronCreate, durable:false) whose prompt runs `$PYTHON -m claude_code_hooks_daemon.daemon.cli harvest-background` and acts on any runaway — this covers the idle/compaction window a tool-call hook cannot. Do NOT wait for the cron; keep working.
- Check on demand: run `harvest-background` (exit 1 == runaways surfaced).
- Reap a runaway by its **process group**: `kill -- -<pgid>` (not just the pid).
- Keep a wanted long task: note `KEEP_RUNNING_BECAUSE="reason"`.
- Delete the watchdog cron (CronDelete) when no backgrounded work remains.

Advisory is rate-limited per session (default-on). Disable with `handlers.post_tool_use.background_process_tracker.enabled: false`.

## markdown_table_formatter — markdown tables are auto-aligned

After every `Write` or `Edit` of a `.md` or `.markdown` file, the content is re-formatted via `mdformat + mdformat-gfm` so that table pipes are aligned and column widths are consistent. The handler is non-terminal and advisory — it never blocks, it just rewrites the file on disk.

**What changes:**

- Table pipes are aligned vertically and delimiter rows widened to match cell widths.
- Ordered lists keep consecutive numbering (`1.` `2.` `3.`).
- `---` thematic breaks are preserved (mdformat's 70-underscore default is post-processed back).
- Asterisks in table cells are escaped (`*` → `\*`) as required by GFM.

**Exempt:** journal day-files (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`, Plan 00163) are NEVER reformatted — they are an append-only, byte-stable log and rewriting them would trip the `journal-append-only` check.

**Ad-hoc formatting of existing files:**

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>
```

## recovery_cron_advisor — failsafe recovery cron lifecycle advisory

An advisory PostToolUse handler that fires across a plan's lifecycle and
injects guidance telling the agent to manage a non-durable hourly failsafe
recovery cron.

### What it does

Three lifecycle phases are detected from Write/Edit to `CLAUDE/Plan/<digits>-<name>/PLAN.md`
(never from files inside `Completed/`) and from `mkplan.bash` Bash invocations:

| Phase          | Trigger                                               | Guidance injected                                                                                                                                                                                                                                         |
| -------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Creation**   | New PLAN.md written, or `mkplan.bash` invoked         | Create a non-durable hourly cron now (CronCreate, durable:false); record the ID in the plan's `JOURNAL/` day-file (NOT in PLAN.md); do NOT wait for the cron.                                                                                             |
| **Progress**   | Edit to PLAN.md touching task-status icons (⬜/🔄/✅) | Confirm the recovery cron is still running (CronList); recreate if missing; keep working.                                                                                                                                                                 |
| **Completion** | `**Status**: Complete[d]` written/edited              | Plan complete — **warns first**: deleting now leaves the still-live session with no recovery coverage. Keep the cron if any further work may happen (it is non-durable and dies on session exit); `CronDelete` only when certain the session is finished. |

Progress reminders are rate-limited per plan: the handler advises on the first
progress edit and then once every few progress edits for that plan, so it does
not spam context on every edit. Completion always advises (bypasses the interval).

### CRITICAL: recovery cron is NOT a heartbeat

The recovery cron is a **failsafe safety net**, not a pacing mechanism:

- The agent **must never** wait for the cron between units of work.
- Work proceeds at **full speed** until an external factor (Claude API error,
  rate limit, 5-hour usage limit, network failure) actually stalls it.
- The cron fires only while the REPL is idle; it cannot interrupt active work.
- Treating the cron as a heartbeat is an **own goal** — it would convert a
  safety net into an artificial hourly throttle.

### Canonical recovery-cron prompt

Use this verbatim as the CronCreate prompt:

```
**FAILSAFE RECOVERY CHECK (automated hourly safety net — NOT a heartbeat).**
If your most recent work on the active plan/task was interrupted by an
*external* factor (Claude API error/overload, rate limit, 5-hour usage limit,
network failure) and is now resumable, resume it immediately and carry it to
completion. If you are blocked **only** on human input, do nothing and keep
waiting. If work is already proceeding normally, this is a **no-op** — do not
interrupt, restart, or duplicate anything in flight. Never treat this as a
heartbeat or pacing signal: between checks, continue at full speed until an
external factor actually stops you — waiting for the cron is an own goal. Do
NOT delete this cron merely because a tick finds nothing to resume: it is
non-durable and ends automatically when the session exits, and a still-live
session stays exposed to the next rate limit without it. Remove it (CronDelete)
only once the session is genuinely finished with no further work.
```

### Configuration

This handler is **on by default** (opt-out). Disable with:

```yaml
handlers:
  post_tool_use:
    recovery_cron_advisor:
      enabled: false
```

## project_handler_load_checker — project protection degraded alert

At session start this handler reports any **project handlers** (`.claude/project-handlers/`) that FAILED to load in the running daemon. A skipped handler is a silently-disabled protection — the alert exists so you never assume a guardrail is active when it is not.

### When you see `🚨 PROJECT PROTECTION DEGRADED 🚨`

1. **Do not assume normal guardrails are in force.** The listed handlers are OFF for this session.
2. **Diagnose** each failure: `$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers` names the file, the missing method, and the daemon version that introduced it.
3. **Fix** the handler(s) — usually adding a required method stub (e.g. `get_claude_md`) that a daemon upgrade made mandatory.
4. **Restart the daemon** (`$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`). The alert reflects the *running* daemon, so it clears only after a restart reloads the fixed handlers — fixing the file alone is not enough.

The handler is silent when every project handler loads, so seeing this alert always means real action is required.

## plan_qa_sweep — plan-tree drift report at session start

At the start of each new session the plan directory is swept with the
plan QA check catalogue (index/folder bijection, number collisions,
statistics recount, archive structure, status-vs-location coherence,
staleness). Findings are injected once as advisory context — the
sweep never blocks.

**When a drift report appears**: fix the listed findings (each names
its exact remediation) as part of your plan housekeeping, then
re-check with:

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli plan-qa --sweep
```

The CLI exits 1 while findings remain (CI-able). Single-file lint:
`plan-qa --lint <PLAN.md>`; staged-commit check: `plan-qa --check-staged`.
Policy lives under `plan_workflow.qa` in `.claude/hooks-daemon.yaml`
(archive dir names, staleness window, legacy/collision allowlists).

## ccy_supervisor_integrity — keep the ccy supervisor properly set up

At session start this handler checks a ccy project (`.claude/ccy/`) whose supervisor is **armed** (`ccy.env` exports `CCY_CLAUDE_WRAPPER` referencing `claude-supervise.py`). It warns — never blocks — when the setup is brick-risky:

- **`claude-supervise.py` missing** → the launcher's `exec` fails. Redeploy via a daemon upgrade or restore from git.
- **not executable** → `chmod +x .claude/ccy/claude-supervise.py`.
- **git-ignored** → it won't be committed; teammates get a broken supervisor. Add a `!claude-supervise.py` / `!ccy.env` whitelist line to `.claude/ccy/.gitignore` and commit the files.
- **`ccy.deploy_supervisor: false` while armed+present** → the installer skips deploy on `false`, so upgrades never refresh `claude-supervise.py` and the project runs an increasingly stale supervisor. Set it to `true` (or disarm `CCY_CLAUDE_WRAPPER` if you truly want it off).

It also detects a **stale running supervisor** (Plan 00164): when a daemon upgrade has put a NEWER `claude-supervise.py` on disk than the live process (compared by source fingerprint, not just version), it advises restarting ccy so the wrapper re-execs the updated supervisor. Nothing is broken meanwhile — the old supervisor keeps working until the session is relaunched.

When you see this alert, fix the listed item(s) and commit the ccy files so the supervisor works for everyone.

## git_upstream_checker — additive fetch + pull/cleanup advice on session start

On each new session the daemon runs an **additive** `git fetch --all` (never `--prune` — it never removes anything automatically) and then:

**If your branch is behind its upstream**, acts on the configured `mode`:

- `warn` (default): strongly advises you to run `git pull`.
- `agent-pull`: instructs you to run `git pull` as your first action.
- `auto-pull`: the daemon runs `git pull --ff-only` for you on a clean, non-diverged tree; if it cannot fast-forward (dirty tree or diverged history) it degrades to a warning and you pull manually.

**If local branches track a remote branch that was deleted**, it lists them (marked merged = safe vs not-merged = has unique commits) and asks you to clean up AFTER checking: `git branch -d <name>` for merged branches, ask the human for the rest, and optionally `git fetch --prune` the stale remote-tracking refs. The daemon never prunes or deletes a branch itself; never use `git branch -D`.

It is silent when up to date with no gone branches, not in a git repo, on a detached HEAD, or without an upstream. Configure via `handlers.session_start.git_upstream_checker.options.mode`.

## hook_registration_checker — hooks configuration policy

On every new session this handler audits hook configuration across `.claude/settings.json` and `.claude/settings.local.json`. When it reports issues, fix them — do not ignore the warning.

### Policy

1. **All hooks live in `settings.json`.** That file is tracked in version control, visible to teammates, and is the single source of truth for the daemon.
2. **`settings.local.json` must contain ZERO `hooks` entries.** It exists for per-developer `permissions` and IDE state only. A `hooks` block there is either (a) invisible to the rest of the team, or (b) duplicated with `settings.json` — in which case the hook fires twice per event.
3. **Hook commands must invoke the daemon wrapper.** Every registered command must end with `/.claude/hooks/{event}`. Anything else (inline Python, custom shell scripts, bespoke paths) is a legacy setup that bypasses the daemon entirely.

### Remediation

- **Hooks in `settings.local.json`**: move each `hooks` entry to `settings.json`, then delete the `hooks` key from `settings.local.json`. Confirm no duplicates remain.
- **Legacy-style commands**: replace them with a project-level handler. Run `$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers` to scaffold `.claude/project-handlers/`, port the logic into a handler class, then restore the daemon wrapper in `settings.json`. The daemon will auto-discover the new handler on restart.
- **Missing hooks**: by default this handler SELF-HEALS — it merges the full wired registration set into `settings.json` on session start (additive; preserves `permissions`/`env`/`statusLine` and any custom hooks; one-shot backup to `settings.json.bak.pre-registration-repair`), so the flood stops without a reinstall. Opt out with `handlers.session_start.hook_registration_checker.options.auto_repair_registrations: false`, then re-run the installer or add the missing `{event_name}` entry manually.
- **Duplicate hooks**: a hook registered in both files fires twice. Keep the `settings.json` entry, delete from `settings.local.json`.

## plan_workflow_asset_checker — plan tooling provisioning alert

At session start, when the plan workflow is enabled but the daemon-owned `mkplan.bash` is missing from the plan directory, this advisory fires (it never blocks). A missing `mkplan.bash` means `CLAUDE.md` and `plan_number_helper` reference a scaffolder that does not exist and journalling is inert.

**Fix**: (re)deploy the assets on demand —

```
$PYTHON -m claude_code_hooks_daemon.daemon.cli deploy-plan-workflow
```

The deploy is idempotent (fills gaps only, never overwrites client-owned files). Silent when `mkplan.bash` is present or the workflow is disabled.

## idle_housekeeping_advisory — report-first idle housekeeping (beta, opt-in)

When the session is idle and caught up (repeated no-op failsafe-recovery ticks), this advisory suggests a bounded HOUSEKEEPING MODE: dispatch specialist housekeeping sub-agents that run read-only audits and write shareable **markdown report files** (default `untracked/reports/`). It is REPORT-ONLY — never auto-fix or auto-commit — and strictly lower priority than real work (a real user prompt aborts it). Off by default; enable via `handlers.user_prompt_submit.idle_housekeeping_advisory.enabled: true`. A project can point it at its own doc via the `custom_guidance_doc` option (`custom_guidance_mode: additive` appends it to the default, `replace` uses only the project doc). See docs/guides/CREATING_REPORTS.md.

## auto_approve_reads — gated on bypassPermissions mode

Read-only tool permission requests (`Read`, `Glob`, `Grep`) are auto-approved **only** when Claude Code reports `permission_mode == "bypassPermissions"` (YOLO mode).

In every other mode (`default`, `plan`, `acceptEdits`, `dontAsk`) the handler defers and Claude Code's normal approval prompt is shown — the user has not opted out of per-tool approvals, so the daemon must not silently approve on their behalf.

If a permission prompt for `Read` appears in `default` mode, that is correct behaviour — approve it via Claude Code's UI.

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
- Smuggle a rhetorical continue question inside a `STOPPING BECAUSE:` message ('STOPPING BECAUSE: slice 1 done. Want me to build slice 2?') — this is HARD-BLOCKED; the prefix does not exempt tautological questions. Just continue with the next unit of work
- Use `AUTO-CONTINUE` unless you intend to keep working indefinitely

**Before asking a question, evaluate it critically**:

- Tautological/rhetorical questions with obvious answers ("Should I continue?", "Would you like me to proceed?") — do NOT ask, just do it
- Errors with a clear next step ("The test failed, should I fix it?") — do NOT ask, just fix it
- Genuine choice questions where all options are valid ("Which of A, B, or C should we use?") — these deserve a response. Use `STOPPING BECAUSE: need user input` and ask your question

**Recovering from a `tool_use_error` — do NOT stop silently**:

Some tool errors require an explicit recovery action, not a halt. The most common shape:

- You call `Edit` or `Write` on a file you have not yet read.
- Claude Code returns a `tool_use_error` (e.g. "File has not been read yet").
- The correct recovery is **Read the file, then retry Edit/Write** — **do not stop**. Stopping silently after a tool error triggers a Stop-hook re-entry loop and wastes a turn.

**Rule: Read before Edit/Write.** If you must edit a file you have not read, Read it first in the same turn. The daemon's Stop handler will detect a `tool_use_error` followed by a silent stop and re-fire to force recovery.

**On Stop hook re-entry (the hook fires again after a prior block)**: your next response is treated like any other — it must either prefix with `STOPPING BECAUSE:` or continue the work. Re-entry does not exempt you from the explanation rule.

## dismissive_language_detector — do not deflect or prematurely halt

Stop-time advisory that fires on language patterns signalling avoidance of work. The handler does NOT block the stop, but injects context for the next turn so the agent self-corrects. Identical advisories (same session, same phrase set) are emitted once, not repeated on every subsequent stop.

**Avoid**:

- Dismissing issues as `pre-existing`, `out of scope`, `not our problem`, or `not relevant` to deflect work that is in fact yours.
- Premature-halt phrasing like `natural checkpoint`, `ready to continue on your   cue`, `pausing here` mid-plan when there is more to do — finish the task rather than dressing up a halt.
- Speculative `should be fine` or `probably works` when verification is cheap (run the test, read the file).

**Do**: acknowledge the issue, fix it, or — if it genuinely is out of scope — say so once with the specific reason and continue with the in-scope work.

## worktree_create — semantic worktree naming

When Claude Code creates a worktree (an `isolation: "worktree"` agent or `--worktree` session), the daemon creates it at a human-friendly path `.claude/worktrees/<slug-of-name>-<shorthash>/` and echoes that path. Name an agent semantically (the Agent tool's `name:`) to get a readable worktree directory (e.g. `refactor-auth-4f2a1c9b`) instead of an opaque `wf_<hash>`. The short hash suffix keeps identically-named agents from colliding.

</hooksdaemon>
