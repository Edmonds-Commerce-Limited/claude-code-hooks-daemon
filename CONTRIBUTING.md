# Contributing to Claude Code Hooks Daemon

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.11 or higher
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

Install pre-commit hooks to run checks automatically. `pre-commit` ships in the
`dev` extras, so it is present once the project is installed:

```bash
pre-commit install
pre-commit run --all-files   # verify the hooks work before relying on them
```

The black/ruff/mypy/bandit hooks run the tools from **this** environment rather
than from upstream mirror repos, so their versions and configuration come from
`uv.lock` and `pyproject.toml` — the same ones `scripts/qa/` uses. See the note
at the top of `.pre-commit-config.yaml` for why.

### Dependency Lockfile (`uv.lock`)

`uv.lock` is committed alongside `pyproject.toml` and is CI-gated via `uv lock --check` (runs as part of `./scripts/qa/run_dependency_check.sh`). Any change to `pyproject.toml` dependencies MUST be accompanied by a regenerated lockfile.

```bash
# After editing pyproject.toml dependencies:
uv lock

# Commit both files together:
git add pyproject.toml uv.lock
git commit -m "Add dependency X"
```

If QA fails with `uv.lock is out of sync`, regenerate with `uv lock` and commit. Do NOT hand-edit `uv.lock`.

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

Identity comes from the constants modules, never from string and integer
literals. `HandlerID` gives the handler its stable config key, `Priority` places
it in a documented band, and `HandlerTag` describes it — `terminal` is derived
from `HandlerTag.TERMINAL` rather than passed separately.

Subclass the base named after your EVENT (here `PreToolUseHandlerBase`), never
`Handler` directly — each event base narrows `handle()` to the result type its
event can deliver, and an integration test enforces this for every handler.
The base is an ABC with FOUR abstract methods; implementing only
`matches`/`handle` gives a class that cannot be instantiated. The canonical
in-depth guide is [CLAUDE/HANDLER_DEVELOPMENT.md](CLAUDE/HANDLER_DEVELOPMENT.md).

```python
# src/claude_code_hooks_daemon/handlers/pre_tool_use/my_handler.py
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command


class MyHandler(PreToolUseHandlerBase):
    """Short description of what this handler does."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MY_HANDLER,
            priority=Priority.MY_HANDLER,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this handler should execute."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        return "target" in command

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Execute handler logic."""
        return GatingResult(
            decision=Decision.DENY,
            reason="Explanation of why the operation was blocked, and what to do instead",
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance for CLAUDE.md, or None if this handler needs none."""
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Tests rendered into the release acceptance playbook."""
        return []
```

`Handler.__init__` still accepts a bare `name=` string; it is a deprecated alias
kept for older tests and must not be used in new handlers.

### 4. Register Handler

Handlers are **discovered**, not wired by hand. Add the `HandlerID` and
`Priority` members, drop the module in the event-type package under
`src/claude_code_hooks_daemon/handlers/<event_type>/`, and
`handlers/registry.py` picks it up. There is no entry-point module to edit.

### 5. Add Configuration

Add the handler to the default config template in
`src/claude_code_hooks_daemon/daemon/init_config.py` — that is what every new
install is generated from, so a handler missing there ships dormant in every
client project. `tests/integration/test_dogfooding_config.py` enforces this.

Then enable it in this repo's own `.claude/hooks-daemon.yaml` so it is
dogfooded.

(The deprecated root `install.py` carries its own copy of the template for
backward compatibility with pre-Layer-2 tags. It is not the source of truth.)

## Handler Guidelines

### Priority Ranges

The canonical statement of the bands is the
[Priority Guide](CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide) (boundaries
derive from `PriorityRange` in
`src/claude_code_hooks_daemon/constants/priority.py`). Quoted here for
convenience:

<!-- ssot-quote: CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide -->

| Priority Range | Type         | Examples                                                                                           |
| -------------- | ------------ | -------------------------------------------------------------------------------------------------- |
| 0-9            | Test         | Reserved for purpose-built test fixtures (`Priority.TEST_HANDLER`); no built-in handlers ship here |
| 10-20          | Safety       | `destructive_git`, `sed_blocker`, `secret_file_guard`                                              |
| 25-35          | Code Quality | `qa_suppression`, `lint_on_edit`, `comment_changelog`                                              |
| 36-55          | Workflow     | `lsp_enforcement`, `plan_qa_edit`, `npm_command`                                                   |
| 56-66          | Advisory     | `british_english`, `flaggable_work_advisor`, `model_fallback_detector`                             |
| 100+           | Logging      | Reserved for logging/metrics/cleanup; no built-in handlers ship here                               |

<!-- /ssot-quote -->

### Terminal vs Non-Terminal

- **Terminal (`terminal=True`)**: Stops dispatch on match, returns result immediately
- **Non-Terminal (`terminal=False`)**: Continues dispatch, accumulates context

### Error Handling

**Let exceptions propagate.** Degradation policy belongs to the dispatcher, and
a handler that swallows its own errors takes that decision away from it.

`HandlerChain.execute()` (`core/chain.py:244`) is the single place that decides
what a crash means:

- default (`strict_mode=False`) — logs the exception, appends
  `Handler exception: <Type>: <message>` to the accumulated context so the
  failure is **visible**, and continues the chain;
- `strict_mode=True` — fails closed: the operation is denied with
  `SYSTEM ERROR: Handler <name> crashed - blocking for safety`.

A `try/except Exception: return allow` inside a handler defeats both. It looks
like fail-open but is strictly worse: the exception never reaches the log, no
context is surfaced, strict mode silently stops being strict, and the handler
reports a clean ALLOW for a check it never actually performed — a guard that is
off while appearing on. This project treats that as the primary failure mode
(**FAIL FAST**, `CLAUDE.md`), and ships `error_hiding_blocker` plus
`scripts/qa/audit_error_hiding.py` to prevent it.

Catch narrowly and only where you can genuinely recover — a missing optional
file, a subprocess timeout — and always surface what happened in the result's
`context`.

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
