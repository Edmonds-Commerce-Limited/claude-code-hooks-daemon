# Claude Code Hooks Daemon - LLM Context

## What This Is

A high-performance daemon for Claude Code hooks using Unix socket IPC. Eliminates process spawn overhead (20x faster after warmup).

## Quick Reference

### Key Directories

```
src/claude_code_hooks_daemon/
├── core/           # Front controller, Handler base, HookResult
├── daemon/         # Server, CLI, DaemonController, paths
├── handlers/       # All handler implementations (by event type)
├── config/         # YAML/JSON config loading
├── hooks/          # Entry point modules (one per event)
└── plugins/        # Plugin system for custom handlers
```

### Architecture

1. **Forwarder Pattern**: Bash scripts → Unix socket → Daemon → FrontController → Handlers
2. **Multi-Event Support**: DaemonController manages one FrontController per event type
3. **Lazy Startup**: Daemon starts on first hook call, auto-shuts down after idle timeout

### Handler Development

Create handlers in `handlers/{event_type}/`:

```python
from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        # Return True if this handler should run
        return "pattern" in hook_input.get("tool_input", {}).get("command", "")

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Blocked because...")
```

### Priority Ranges

- **5**: Test handlers
- **10-20**: Safety (destructive git, sed blocker)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English)

### Terminal vs Non-Terminal

- `terminal=True`: Stops dispatch chain, returns result immediately
- `terminal=False`: Continues dispatch, accumulates context

### Configuration

Config file: `.claude/hooks-daemon.yaml`

```yaml
version: 1.0
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
```

### CLI Commands

```bash
python3 -m claude_code_hooks_daemon.daemon.cli start
python3 -m claude_code_hooks_daemon.daemon.cli stop
python3 -m claude_code_hooks_daemon.daemon.cli status
python3 -m claude_code_hooks_daemon.daemon.cli restart
```

### Testing & QA

**CRITICAL: ALWAYS run QA before committing code changes**

#### Quick QA Commands

```bash
# Run ALL QA checks (recommended before commits)
# NOTE: Format and lint checks AUTO-FIX issues by default
./scripts/qa/run_all.sh

# Individual checks (auto-fix enabled by default)
./scripts/qa/run_lint.sh          # Ruff linter (auto-fixes violations)
./scripts/qa/run_format_check.sh  # Black formatter (auto-formats files)
./scripts/qa/run_type_check.sh    # MyPy type checker (check only)
./scripts/qa/run_tests.sh         # Pytest with 95% coverage requirement

# Manual auto-fix (runs Black + Ruff --fix)
./scripts/qa/run_autofix.sh
```

#### QA Standards

All code MUST pass:
- **Ruff** - Python linting (enforces code quality, imports, simplifications)
- **MyPy** - Strict type checking (all functions must be typed)
- **Black** - Code formatting (line length 100)
- **Pytest** - 95% minimum coverage with all tests passing
- **Bandit** - Security checks (no vulnerabilities)

#### Type Annotations

**Python 3.8+ Compatible Types Required:**

```python
# ✅ CORRECT - Use typing module imports for compatibility
from typing import Dict, List, Optional, Any, Union

def example(data: Dict[str, Any]) -> Optional[List[str]]:
    pass

# ❌ WRONG - Do NOT use Python 3.9+ built-in generic types
def example(data: dict[str, Any]) -> list[str] | None:  # Breaks Python 3.8
    pass
```

**Why:** This codebase supports Python 3.8-3.12. Built-in generic types (`dict[str, Any]`, `list[str]`, `X | Y`) require Python 3.9+.

**Type Checking:**
- MyPy configured for strict mode
- All functions must have type annotations
- No `Any` types without justification
- Use Protocol for duck typing

#### Output Files

QA scripts write JSON results to `untracked/qa/`:
- `lint.json` - Ruff violations
- `type_check.json` - MyPy errors
- `format.json` - Black formatting issues
- `tests.json` - Test results and coverage
- `coverage.json` - Detailed coverage data

#### Auto-Fix Behavior

**Auto-fix is ENABLED BY DEFAULT** in QA scripts:
- `run_format_check.sh` - Automatically formats files with Black
- `run_lint.sh` - Automatically fixes violations with `ruff check --fix`

Manual auto-fix (if needed):
```bash
# Run both Black and Ruff auto-fix
./scripts/qa/run_autofix.sh

# Or individually
black src/ tests/
ruff check --fix src/ tests/
```

#### CI/CD Integration

All QA checks run in GitHub Actions. PRs blocked if:
- Any QA check fails
- Coverage drops below 95%
- Type errors present
- Security issues found

### Key Files

- `daemon/controller.py` - Multi-event DaemonController
- `daemon/server.py` - Asyncio Unix socket server
- `core/front_controller.py` - Handler dispatch logic
- `core/handler.py` - Handler base class
- `install.py` - Installation automation

### Documentation

- `README.md` - Installation and usage
- `DAEMON.md` - Architecture deep dive
- `CLAUDE/ARCHITECTURE.md` - Design documentation
- `CLAUDE/HANDLER_DEVELOPMENT.md` - Handler creation guide
- `CONTRIBUTING.md` - Contribution guidelines
