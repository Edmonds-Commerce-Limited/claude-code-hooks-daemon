# Claude Code Hooks Daemon

![Version](https://img.shields.io/badge/version-2.15.1-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-6255%20passing-success)
![Coverage](https://img.shields.io/badge/coverage-95%25%20required-success)

A better way to build and maintain Claude Code hooks.

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

## Why Use This?

Claude Code's native hook system is powerful but difficult to iterate on. Hooks are small programs registered in settings — to test a change you need to modify external files and often restart your session to pick up the changes.

**The daemon changes this fundamentally.**

When installed, your project has just five Claude Code hooks — one per event type. Each is a lightweight shell script that simply forwards events to the daemon over a Unix socket. The daemon is a separate Python process that **you can restart independently of Claude Code**.

This means you can use Claude Code itself to write and modify hook handlers, restart the daemon with a single command, and immediately test your changes — all without leaving your current session. The tool you're using to edit code becomes the tool you use to improve the hooks that govern how you edit code.

### What This Unlocks

**Develop hooks with Claude Code itself**

The daemon's handlers are just Python files in a directory. Claude Code can read, modify, and test them directly. Ask Claude to write a new blocking pattern, add a test case, or debug unexpected behaviour — then restart the daemon and verify. No external tooling or context switching required.

**Fast iteration without session restarts**

Restarting the daemon takes under a second. Your Claude Code session continues uninterrupted with all its context intact. Change a handler, restart, test — repeat until it's right.

**Test-Driven Development for hooks**

Because handlers are Python classes with proper type annotations, you can write real unit tests. This project ships with 6,255 tests and a 95% coverage requirement — the same standard applies to handlers you write for your own project. Catch regressions before restarting, not after.

**Run many handlers without overhead**

The daemon processes hook events in-process via Unix socket IPC, so adding more handlers has negligible cost. A project with 50 active handlers performs as well as one with 5. More rules means better guardrails.

**Real programming, not shell scripting**

Handlers are Python classes. Strategy patterns, type safety, dependency injection, shared utilities — the full toolkit. Complex enforcement logic that would be impossible to maintain as shell scripts becomes straightforward when you're working in a real language with proper abstractions.

---

## What's Built In

The daemon ships with 48 production handlers across 10 event types, covering the most common AI-assisted development guardrails:

### Safety (Priority 10–20)

- **Destructive git blocker** — Prevents `git push --force`, `git reset --hard`, `git clean -f`, `git branch -D`
- **Sed blocker** — Encourages the Edit tool over sed; avoids dangerous in-place edits
- **Absolute path enforcer** — Prevents absolute paths in tool calls
- **QA suppression blocker** — Blocks `# type: ignore`, `# noqa`, `eslint-disable`, `//nolint` across 11 languages (Python, JS, TS, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#)

### Code Quality (Priority 25–35)

- **TDD enforcement** — Requires test files alongside implementation; 11 language strategies
- **ESLint disable blocker** — Prevents `@ts-ignore`, `@ts-nocheck` without justification
- **Lock file protection** — Prevents editing generated lock files

### Workflow (Priority 36–55)

- **Planning enforcer** — Requires documented plans for non-trivial work
- **Daemon restart verifier** — Blocks commits if the daemon cannot restart cleanly
- **Pipe blocker** — Prevents expensive commands piped to `head`/`tail`
- **Web search year** — Ensures searches include the current year
- **Git context injector** — Adds git status to every prompt

### Session Management

- **YOLO container detection** — Identifies container environments with confidence scoring
- **Version checker** — Alerts when the daemon is out of date
- **Workflow state persistence** — Saves and restores workflow state across conversation compaction

---

## Status Line

The daemon can drive Claude Code's built-in status line, giving you a persistent at-a-glance view of your session:

```
📁 claude-code-hooks-daemon 👤 joseph | 🤖 Sonnet 4.6 ▌▌▌ | ◑ 45.0% | 🕐 15:15 | ⎇ main | 🪝 45.7s : 37MB : DEBUG : 🛡️
```

It shows the repo name, account, model and thinking mode, context usage, time, git branch, and daemon stats — updated automatically on every interaction.

**Setup** — add to `.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/status-line"
  }
}
```

If you haven't configured it yet, the daemon will suggest it on your next new session. If the daemon ever fails to start, the status line shows `⚠️ DAEMON FAILED` so the problem is immediately visible rather than silently degraded.

---

## Project-Level Handlers

Add your own handlers in `.claude/project-handlers/` — auto-discovered on daemon restart, co-located with tests, with full CLI support:

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Scaffold the directory with an example handler and tests
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers

# Validate handlers load correctly
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers

# Run project handler tests
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose
```

See [CLAUDE/PROJECT_HANDLERS.md](CLAUDE/PROJECT_HANDLERS.md) for the complete guide.

---

## Installation

### AI-Assisted (Recommended)

**Copy this into Claude Code:**

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md -o /tmp/LLM-INSTALL.md
Then read /tmp/LLM-INSTALL.md and follow the instructions exactly.
```

Installation takes around 30 seconds. The AI will clone the daemon, create a virtual environment, run the installer, and verify everything works.

### Manual

```bash
mkdir -p .claude && cd .claude
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon
git fetch --tags && git checkout "$(git describe --tags --abbrev=0)"
python3 -m venv untracked/venv
untracked/venv/bin/pip install -e .
untracked/venv/bin/python install.py
cd ../..
```

After installation, create `.claude/.gitignore` so generated files aren't committed:

```bash
cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore
```

The installer creates:
- `.claude/settings.json` — Hook registration for Claude Code
- `.claude/hooks/*` — Forwarder scripts (route events to the daemon)
- `.claude/init.sh` — Daemon lifecycle functions
- `.claude/hooks-daemon.yaml` — Handler configuration

---

## Updating

### AI-Assisted (Recommended)

**Copy this into Claude Code:**

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md -o /tmp/LLM-UPDATE.md
Then read /tmp/LLM-UPDATE.md and follow the instructions exactly.
```

### Manual

```bash
cd .claude/hooks-daemon
cp ../hooks-daemon.yaml ../hooks-daemon.yaml.backup
git fetch --tags && git checkout "$(git describe --tags --abbrev=0)"
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
cd ../..
```

Version-specific migration guides are in [CLAUDE/UPGRADES/](CLAUDE/UPGRADES/).

---

## Writing Custom Handlers

```python
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return "pattern" in hook_input.get("tool_input", {}).get("command", "")

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason="Blocked because...",
            context=["Additional context line"]
        )
```

Place handlers in `.claude/project-handlers/{event_type}/` — they're auto-discovered on daemon restart. Before writing a handler, capture real event data first:

```bash
./scripts/debug_hooks.sh start "Testing my scenario"
# ... trigger the action in Claude Code ...
./scripts/debug_hooks.sh stop
# Logs show exact event structure, timing, and data
```

**Priority ranges:**
- `10–20` — Safety (destructive operations)
- `25–35` — Code quality (linting, TDD)
- `36–55` — Workflow (planning, conventions)
- `56–79` — Advisory (non-blocking suggestions)
- `100+` — Logging and cleanup

See [CLAUDE/HANDLER_DEVELOPMENT.md](CLAUDE/HANDLER_DEVELOPMENT.md) for the complete guide.

---

## Daemon Management

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status   # Check if running
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart  # Restart after handler changes
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop     # Stop daemon
```

The daemon starts automatically on the first hook call and exits after 10 minutes of inactivity. Each project gets its own isolated daemon instance.

---

## Configuration

**File**: `.claude/hooks-daemon.yaml`

```yaml
version: "2.0"

daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git:
      enabled: true
      priority: 10
    sed_blocker:
      enabled: true
      priority: 10
    tdd_enforcement:
      enabled: true
      priority: 25
    british_english:
      enabled: true
      priority: 60
      mode: warn  # "warn" or "block"

project_handlers:
  enabled: true
  path: .claude/project-handlers
```

### Tag-Based Filtering

Enable only what's relevant to your tech stack:

```yaml
handlers:
  pre_tool_use:
    enable_tags: [python, typescript, safety, tdd]
    disable_tags: [ec-specific]
```

**Available tags:** `safety`, `tdd`, `qa-suppression-prevention`, `workflow`, `advisory`, `git`, `npm`, `python`, `typescript`, `javascript`, `php`, `go`

---

## Deterministic vs Agent-Based Hooks

The daemon is designed for **fast, deterministic validation**. For reasoning-heavy evaluation, use Claude Code's native agent-based hooks.

| Use Daemon For | Use Agent Hooks For |
|----------------|---------------------|
| Pattern matching (regex, string checks) | Workflow compliance validation |
| Fast synchronous validation | Context analysis (transcripts, git state) |
| Reusable safety rules across sessions | Multi-turn investigation |
| Deterministic, stateless logic | Reasoning and judgment calls |

---

## Git Integration

With `.claude/.gitignore` in place, your team shares hook configuration automatically:

```
.claude/
├── .gitignore           # ✅ Commit
├── settings.json        # ✅ Commit (hook registration)
├── hooks-daemon.yaml    # ✅ Commit (handler settings)
├── init.sh              # ✅ Commit (daemon lifecycle)
├── hooks/               # ✅ Commit (forwarder scripts)
└── hooks-daemon/        # ❌ Excluded (each dev installs their own)
```

New team members get the same hooks automatically on first use. If your root `.gitignore` excludes `.claude/`, remove that entry — the per-directory `.gitignore` handles it correctly.

---

## Documentation

- [Architecture](CLAUDE/ARCHITECTURE.md) — System design and components
- [Handler Development](CLAUDE/HANDLER_DEVELOPMENT.md) — Creating custom handlers
- [Project Handlers](CLAUDE/PROJECT_HANDLERS.md) — Per-project handler guide
- [Debugging Hooks](CLAUDE/DEBUGGING_HOOKS.md) — Event introspection tool
- [QA Pipeline](CLAUDE/development/QA.md) — Quality assurance automation
- [Upgrade Guides](CLAUDE/UPGRADES/) — Version migration guides
- [Bug Reporting](BUG_REPORTING.md) — Debug info generation

---

## Requirements

- Python 3.11, 3.12, or 3.13
- Linux or macOS (Windows has limited support — Unix sockets)
- Dependencies auto-installed: `pyyaml`, `pydantic`, `jsonschema`

---

## Troubleshooting

For comprehensive troubleshooting and bug reporting, see [BUG_REPORTING.md](BUG_REPORTING.md).

**Generate a debug report:**

```bash
# From the daemon project
./scripts/debug_info.py /tmp/debug_report.md

# From a client project
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

**Common fixes:**

```bash
# Daemon won't start — check logs
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs

# Force restart
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Verify hook forwarding works
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo test"}}' | \
  .claude/hooks/pre-tool-use
# Expected: JSON with decision="allow"
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch
3. Write failing tests first (TDD)
4. Implement the feature
5. Run `./scripts/qa/run_all.sh` — all 8 checks must pass
6. Submit a pull request

---

## License

MIT License — Copyright © 2024–2026 Edmonds Commerce

**Issues:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
**Email:** hello@edmondscommerce.co.uk
