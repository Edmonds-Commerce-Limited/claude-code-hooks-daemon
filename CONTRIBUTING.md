# Contributing to Claude Code Hooks Daemon

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.8 or higher
- pip and venv

### Installation

```bash
# Clone the repository
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git
cd claude-code-hooks-daemon

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/unit/handlers/test_destructive_git.py

# Run with verbose output
pytest -v

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/
```

### Code Quality

We use several tools to maintain code quality:

```bash
# Run all QA checks
./scripts/qa/run_all.sh

# Or individually:
./scripts/qa/run_lint.sh      # Ruff linting
./scripts/qa/run_type_check.sh # MyPy type checking
./scripts/qa/run_format_check.sh # Black formatting
./scripts/qa/run_tests.sh     # Pytest with coverage
```

#### Pre-commit Hooks

Install pre-commit hooks to run checks automatically:

```bash
pre-commit install
```

## Creating a New Handler

### 1. Choose the Right Event

Handlers are organised by hook event type:
- `pre_tool_use/` - Before tool execution (most common)
- `post_tool_use/` - After tool execution
- `session_start/` - When Claude Code session begins
- `session_end/` - When session ends
- `pre_compact/` - Before conversation compaction
- `user_prompt_submit/` - When user submits prompt
- `permission_request/` - Permission system events
- `notification/` - Notification events
- `stop/` - Stop events
- `subagent_stop/` - Subagent completion events

### 2. Write Tests First (TDD)

Create test file before implementation:

```python
# tests/unit/handlers/test_my_handler.py
import pytest
from claude_code_hooks_daemon.handlers.pre_tool_use.my_handler import MyHandler

class TestMyHandler:
    @pytest.fixture
    def handler(self):
        return MyHandler()

    def test_init_sets_correct_properties(self, handler):
        assert handler.name == "my-handler"
        assert handler.priority == 50
        assert handler.terminal is True

    def test_matches_target_pattern(self, handler):
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "target"}}
        assert handler.matches(hook_input) is True

    def test_does_not_match_other_commands(self, handler):
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False
```

### 3. Implement Handler

```python
# src/claude_code_hooks_daemon/handlers/pre_tool_use/my_handler.py
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

class MyHandler(Handler):
    """Short description of what this handler does."""

    def __init__(self) -> None:
        super().__init__(
            name="my-handler",
            priority=50,
            terminal=True  # Set False for advisory/non-blocking handlers
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if this handler should execute."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        return "target" in command

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic."""
        return HookResult(
            decision="deny",
            reason="Explanation of why operation was blocked"
        )
```

### 4. Register Handler

Add to the appropriate entry point module:
- `src/claude_code_hooks_daemon/hooks/pre_tool_use.py`

And to the daemon controller:
- `src/claude_code_hooks_daemon/daemon/controller.py`

### 5. Add Configuration

Add handler config to default YAML template in `install.py`.

## Handler Guidelines

### Priority Ranges

- **5**: Test/debug handlers (hello_world)
- **10-20**: Safety handlers (destructive operations)
- **25-35**: Code quality handlers (linting, TDD)
- **36-55**: Workflow handlers (planning, npm)
- **56-60**: Advisory handlers (spelling)

### Terminal vs Non-Terminal

- **Terminal (`terminal=True`)**: Stops dispatch on match, returns result immediately
- **Non-Terminal (`terminal=False`)**: Continues dispatch, accumulates context

### Error Handling

Handlers should **fail open** - never block operations due to internal errors:

```python
def handle(self, hook_input: dict) -> HookResult:
    try:
        # Handler logic
        return HookResult(decision="deny", reason="...")
    except Exception:
        # Fail open on errors
        return HookResult(decision="allow")
```

## Pull Request Process

1. **Create Feature Branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make Changes**
   - Write tests first
   - Implement feature
   - Update documentation

3. **Run QA Checks**
   ```bash
   ./scripts/qa/run_all.sh
   ```

4. **Commit with Descriptive Message**
   ```bash
   git commit -m "Add MyHandler for blocking dangerous operations

   - Implements pattern matching for target commands
   - Adds comprehensive test coverage
   - Updates configuration template"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/my-feature
   ```

6. **PR Review**
   - All QA checks must pass
   - Test coverage must be maintained (95%+)
   - Documentation must be updated

## Questions?

Open an issue on GitHub or check existing documentation in `CLAUDE/` directory.
