# Claude Code Hooks Daemon

![Version](https://img.shields.io/badge/version-3.55.0-blue)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-14000%2B%20passing-success)
![Coverage](https://img.shields.io/badge/coverage-95%25%20required-success)

*~80,000 lines of source, ~180,000 lines of tests — the test tree is 2.2× the size of the thing it tests.*

Maintained by [Edmonds Commerce](https://github.com/Edmonds-Commerce-Limited).

**Deterministic guardrails for coding agents — containment, policy enforcement and quality gates, evaluated on every tool call before it runs.**

A long-running Python daemon that Claude Code's hook events are forwarded to
over a Unix socket. Instead of one script per hook, you register one thin
forwarder per event once, and every rule after that is a Python handler class —
blocking, advisory or context-injecting — that the daemon dispatches by
priority. Handlers are hot-reloaded by restarting the daemon, not by restarting
your session, so you can write and test a hook with Claude Code while Claude
Code is using it.

Ships with a large set of built-in handlers (destructive-command blocking,
TDD enforcement, QA-suppression and security-antipattern detection across 11
languages, plan/journal workflow QA, status line), all opt-in via one YAML file.

---

## What this solves

A coding agent with shell access will eventually run the command nobody thought
to forbid. Not maliciously, and usually mid-way through doing exactly what was
asked: a `git reset --hard` to tidy the tree before committing, a `sed -i`
across a directory of files that mangles most of them, an API key pasted into
source because it was the shortest path to a green test.

Claude Code exposes hooks — points where an external program inspects a tool
call and allows, blocks or annotates it before it runs. That is the right
mechanism, and it is underused, because each hook is a separate program spawned
per event, and changing one usually means restarting your session. Most
projects wire up two or three and stop.

This daemon makes handlers cheap enough to write dozens of. Lightweight
forwarder scripts — one per event — pass events over a Unix socket to a
long-lived Python process holding every handler in memory. Adding another
handler costs almost nothing at runtime, and the daemon restarts in under a
second without touching your session.

**The enforcement is deterministic.** A handler is a function returning allow
or deny — not a prompt, and not a judgement the model makes about its own
behaviour. That distinction is the point. Instructions are a request: however
firmly you word them, they amount to *please don't*, and a model is free to
weigh them against everything else in its context. A handler is a *no*. It
cannot be negotiated with, talked around, or outweighed by a good reason, and
it decides the thousandth call exactly as it decided the first. For the failure
that actually matters — the one taken deliberately, for a reason that seemed
good at the time — that is the property you want.

That is the whole argument in one line: **when you have an agent that can go
off the rails, the thing enforcing the rails must not be another agent.**

---

## Where this came from

Approving every tool call one at a time gets old fast. The obvious escape is
YOLO mode — `--dangerously-skip-permissions` — and the name is accurate. Running
the agent in a container helps, because you control what it can reach, but it
does not close the gap: the agent still needs the repository and it still needs
git, and that is exactly where the damage happens.

Then, after days of work in YOLO mode, an agent decided it did not need a branch
any more and deleted it. `git branch -D` does not ask, and the branch was not
backed up anywhere else. Days of work were simply gone. Nothing about that was
malicious or even careless by the agent's own lights — it had finished with the
branch, and tidying up was the reasonable next step. That is the shape of the
problem: the destructive command issued confidently, in good faith, by something
that cannot know what it is about to cost you.

The speed is worth having, so the answer was never to give it up. Claude Code's
hooks are the right mechanism — but writing them was the problem. Each hook is a
separate program, and testing a one-character fix meant restarting Claude Code
from scratch: abandoning work in progress, stopping the container, starting
again. Iteration was expensive enough that hooks stayed hobbled — you wrote two
or three, and lived with them.

This daemon is what came out of that. Every handler lives in one long-running
process behind a Unix socket, so changing one costs a sub-second daemon restart
instead of a session. Python for the type system and the tooling, and because a
long-lived daemon is something it is genuinely good at.

---

## Why a daemon rather than plain hooks

Claude Code's native hook system is powerful but difficult to iterate on. Hooks are small programs registered in settings — to test a change you need to modify external files and often restart your session to pick up the changes.

**The daemon changes this fundamentally.**

When installed, your project registers one lightweight forwarder per event type — a thin shell script that does nothing but forward the event to the daemon over a Unix socket. Registration is a fixed, one-time cost that never grows with the number of handlers. The daemon is a separate Python process that **you can restart independently of Claude Code**.

This means you can use Claude Code itself to write and modify hook handlers, restart the daemon with a single command, and immediately test your changes — all without leaving your current session. The tool you're using to edit code becomes the tool you use to improve the hooks that govern how you edit code.

### What This Unlocks

**Develop hooks with Claude Code itself**

The daemon's handlers are just Python files in a directory. Claude Code can read, modify, and test them directly. Ask Claude to write a new blocking pattern, add a test case, or debug unexpected behaviour — then restart the daemon and verify. No external tooling or context switching required.

**Fast iteration without session restarts**

Restarting the daemon takes under a second. Your Claude Code session continues uninterrupted with all its context intact. Change a handler, restart, test — repeat until it's right.

**Test-Driven Development for hooks**

Because handlers are Python classes with proper type annotations, you can write real unit tests. This project ships with 14,000+ tests and a 95% coverage requirement — the same standard applies to handlers you write for your own project. Catch regressions before restarting, not after.

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
- **QA suppression blocker** (`qa_suppression`) — Blocks `# type: ignore`, `# noqa`, `eslint-disable`, `//nolint` across 11 language strategies (Python, JS/TS, PHP, Go, Rust, Java, Ruby, Kotlin, Swift, C#, Dart)

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

### Advisory

- **British English checker** (`british_english`) — Warns about American English spellings in content files; non-blocking
- **Daemon docs guard** (`daemon_docs_guard`) — Warns when reading from the hooks-daemon's internal `CLAUDE/` docs directory

### Session Management

- **Version checker** (`version_check`) — Alerts when the daemon is out of date
- **Git upstream checker** (`git_upstream_checker`) — Fetches on session start and advises when a branch is behind its upstream

---

## Deterministic vs Agent-Based Hooks

The daemon is designed for **fast, deterministic validation**. For reasoning-heavy evaluation, use Claude Code's native agent-based hooks.

| Use Daemon For                          | Use Agent Hooks For                       |
| --------------------------------------- | ----------------------------------------- |
| Pattern matching (regex, string checks) | Workflow compliance validation            |
| Fast synchronous validation             | Context analysis (transcripts, git state) |
| Reusable safety rules across sessions   | Multi-turn investigation                  |
| Deterministic, stateless logic          | Reasoning and judgement calls             |

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
from claude_code_hooks_daemon.core import GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision

class MyHandler(PreToolUseHandlerBase):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        return "pattern" in hook_input.get("tool_input", {}).get("command", "")

    def handle(self, hook_input: dict) -> GatingResult:
        return GatingResult(
            decision=Decision.DENY,
            reason="Blocked because...",
            context=["Additional context line"]
        )
```

Plain `Handler` still works too — subclassing the per-event base (`PreToolUseHandlerBase` here) is not required, it just lets a type-checker catch a decision your event can't actually deliver.

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

MIT License — Copyright (c) 2025 Edmonds Commerce Limited. `LICENSE` is authoritative.

**Issues:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
**Email:** hello@edmondscommerce.co.uk
