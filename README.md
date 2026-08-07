# Claude Code Hooks Daemon

![Version](https://img.shields.io/badge/version-3.51.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-10800%2B%20passing-success)
![Coverage](https://img.shields.io/badge/coverage-95%25%20required-success)

A better way to build and maintain Claude Code hooks.

---

## Installation & Updates

> **For humans:** See [Installation](#installation) and [Updating](#updating) sections below for manual and AI-assisted instructions.

**LLM Quick Reference** — paste these into Claude Code to install or update:

<details>
<summary>Install (copy into Claude Code)</summary>

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md -o /tmp/LLM-INSTALL.md
Then read /tmp/LLM-INSTALL.md and follow the instructions exactly.
```

</details>

<details>
<summary>Update (copy into Claude Code)</summary>

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md -o /tmp/LLM-UPDATE.md
Then read /tmp/LLM-UPDATE.md and follow the instructions exactly.
```

</details>

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

Because handlers are Python classes with proper type annotations, you can write real unit tests. This project ships with 10,800+ tests and a 95% coverage requirement — the same standard applies to handlers you write for your own project. Catch regressions before restarting, not after.

**Run many handlers without overhead**

The daemon processes hook events in-process via Unix socket IPC, so adding more handlers has negligible cost. A project with 50 active handlers performs as well as one with 5. More rules means better guardrails.

**Real programming, not shell scripting**

Handlers are Python classes. Strategy patterns, type safety, dependency injection, shared utilities — the full toolkit. Complex enforcement logic that would be impossible to maintain as shell scripts becomes straightforward when you're working in a real language with proper abstractions.

---

## What's Built In

The daemon ships with a large library of production handlers spanning every hook event Claude Code emits, covering the most common AI-assisted development guardrails. For the exact set active in a given project, see that project's generated `.claude/HOOKS-DAEMON.md`:

### Safety (Priority 10–20)

- **Destructive git blocker** (`destructive_git`) — Prevents `git push --force`, `git reset --hard`, `git clean -f`, `git branch -D`
- **Sed blocker** (`sed_blocker`) — Blocks `sed` used to modify files in place; the Edit tool is the safe alternative
- **Security antipattern blocker** (`security_antipattern`) — Blocks hardcoded secrets (OWASP A02) and injection patterns (OWASP A03) across 12 language strategies (Secrets, Python, JS/TS, PHP, Go, Ruby, Java, Kotlin, C#, Rust, Swift, Dart)
- **Absolute path enforcer** (`absolute_path`) — Requires absolute paths for `Read`/`Write`/`Edit`; blocks relative ones
- **QA suppression blocker** (`qa_suppression`) — Blocks `# type: ignore`, `# noqa`, `eslint-disable`, `//nolint` across 11 languages (Python, JS, TS, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#)

### Code Quality (Priority 25–35)

- **TDD enforcement** (`tdd_enforcement`) — Blocks creating a production file before its test exists; 11 language strategies
- **ESLint on write** (`validate_eslint_on_write`) — Warns on ESLint findings in TypeScript/TSX files after a write
- **Lock file protection** (`lock_file_edit_blocker`) — Prevents editing generated lock files

### Workflow (Priority 36–55)

- **Plan workflow guidance** (`plan_workflow`) — Advises on plan structure and conventions when plan files are written
- **Daemon restart verifier** (`daemon_restart_verifier`) — Recommends verifying a clean daemon restart before committing
- **Pipe blocker** (`pipe_blocker`) — Prevents expensive commands piped to `head`/`tail`
- **Web search year** (`web_search_year`) — Warns when a search query carries an outdated year
- **Git context injector** (`git_context_injector`) — Injects current git status as context on each prompt

### Session Management

- **YOLO container detection** (`yolo_container_detection`) — Identifies container environments from OS-level markers
- **Version checker** (`version_check`) — Alerts when the daemon is out of date

---

## Status Line

The daemon can drive Claude Code's built-in status line, giving you a persistent at-a-glance view of your session:

```
📁 claude-code-hooks-daemon 👤 joseph | 🤖 Sonnet 4.6 ▌▌▌ | ◑ 45.0% | 🕐 15:15 | ⎇ main | 🪝 45.7s : 37MB : DEBUG : 🛡️
```

It shows the repo name, account, model and effort level, context usage, time, git branch, and daemon stats — updated automatically on every interaction.

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
# Scaffold the directory with an example handler and tests
.claude/hooks-daemon/bin/hooks-daemon init-project-handlers

# Validate handlers load correctly
.claude/hooks-daemon/bin/hooks-daemon validate-project-handlers

# Run project handler tests
.claude/hooks-daemon/bin/hooks-daemon test-project-handlers --verbose
```

See [CLAUDE/PROJECT_HANDLERS.md](CLAUDE/PROJECT_HANDLERS.md) for the complete guide.

---

## Installation

### AI-Assisted (Recommended)

**Paste this into Claude Code** — the LLM will fetch the install guide and follow it:

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md -o /tmp/LLM-INSTALL.md
Then read /tmp/LLM-INSTALL.md and follow the instructions exactly.
```

Installation takes around 30 seconds. Claude will clone the daemon, create a virtual environment, run the installer, and verify everything works.

### Manual

```bash
mkdir -p .claude
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git .claude/hooks-daemon
git -C .claude/hooks-daemon fetch --tags
git -C .claude/hooks-daemon checkout "$(git -C .claude/hooks-daemon describe --tags --abbrev=0)"

# The installer builds the venv, installs the package and starts the daemon.
# Never hand-build the venv: it is fingerprint-keyed, and a hand-made
# untracked/venv/ is the retired pre-v3.7.0 layout the resolver refuses.
bash .claude/hooks-daemon/scripts/install_version.sh "$PWD" "$PWD/.claude/hooks-daemon"
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

**Paste this into Claude Code** — the LLM will fetch the update guide and follow it:

```
Use curl to fetch and save this file:
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md -o /tmp/LLM-UPDATE.md
Then read /tmp/LLM-UPDATE.md and follow the instructions exactly.
```

### Manual

```bash
cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
git -C .claude/hooks-daemon fetch --tags
TARGET="$(git -C .claude/hooks-daemon describe --tags --abbrev=0)"

# Rebuilds the venv and reinstalls the package for the target version.
bash .claude/hooks-daemon/scripts/upgrade_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon" "$TARGET"

.claude/hooks-daemon/bin/hooks-daemon restart
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
.claude/hooks-daemon/bin/hooks-daemon status   # Check if running
.claude/hooks-daemon/bin/hooks-daemon restart  # Restart after handler changes
.claude/hooks-daemon/bin/hooks-daemon stop     # Stop daemon
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

| Use Daemon For                          | Use Agent Hooks For                       |
| --------------------------------------- | ----------------------------------------- |
| Pattern matching (regex, string checks) | Workflow compliance validation            |
| Fast synchronous validation             | Context analysis (transcripts, git state) |
| Reusable safety rules across sessions   | Multi-turn investigation                  |
| Deterministic, stateless logic          | Reasoning and judgment calls              |

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
.claude/hooks-daemon/bin/hooks-daemon logs

# Force restart
.claude/hooks-daemon/bin/hooks-daemon restart

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
5. Run `./scripts/qa/run_all.sh` — every check must pass
6. Submit a pull request

---

## License

MIT License — Copyright © 2024–2026 Edmonds Commerce

**Issues:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
**Email:** hello@edmondscommerce.co.uk
