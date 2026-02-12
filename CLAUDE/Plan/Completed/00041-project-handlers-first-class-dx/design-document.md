# Project-Level Plugin/Handler System for hooks-daemon

**Design Document - Opus Research Output**
**Date**: 2026-02-10
**Agent**: Opus 4.6 (agent ID: a4cce23)

---

## 1. Current Architecture Summary

Having read the full codebase, here is how the system currently works:

### Handler Loading Pipeline

1. **DaemonController.initialise()** is the entry point.
2. It creates a **HandlerRegistry** and calls `discover()`, which uses `pkgutil.walk_packages` to scan `claude_code_hooks_daemon.handlers.*` for all concrete `Handler` subclasses.
3. `register_all()` then iterates over event-type subdirectories (`pre_tool_use/`, `post_tool_use/`, etc.), imports modules, and instantiates Handler subclasses, registering each with the **EventRouter**.
4. The router maintains a **HandlerChain** per EventType. Chains execute handlers in priority order, supporting terminal/non-terminal semantics.
5. **Plugin loading** happens separately via `DaemonController._load_plugins()`, which calls `PluginLoader.load_from_plugins_config()`. This uses `importlib.util.spec_from_file_location` to dynamically load `.py` files from filesystem paths.

### Key Abstractions

- **Handler** (ABC): `matches()`, `handle()`, `get_acceptance_tests()` -- all abstract.
- **HookResult** (Pydantic model): `Decision.ALLOW/DENY/ASK`, `reason`, `context`, `guidance`.
- **AcceptanceTest** (dataclass): Structured test definitions that handlers must return.
- **HandlerID, Priority, HandlerTag** (constants): Centralised identifiers.

### Current Plugin System Limitations

The existing plugin system (`PluginLoader`) already supports loading handlers from arbitrary filesystem paths. However, it has significant gaps for project-level development as a first-class feature:

1. **No project scaffolding** -- projects must know how to structure handlers, where to place them, and how to import daemon internals.
2. **No test infrastructure sharing** -- project handler tests cannot easily use the daemon's test utilities, fixtures, or acceptance test infrastructure.
3. **No dependency management** -- the project must manually ensure `claude_code_hooks_daemon` is importable from the plugin Python environment.
4. **No validation CLI** -- no way for a project to verify its handlers load correctly without starting the full daemon.
5. **No handler development documentation** -- the HANDLER_DEVELOPMENT.md is oriented toward built-in handlers.
6. **Discovery is manual** -- each handler must be explicitly listed in `hooks-daemon.yaml` plugins config with its event_type.

---

## 2. Design: Project-Level Handler System

### 2.1 Directory Structure

```
project-root/
  .claude/
    hooks-daemon.yaml          # Existing config (adds project_handlers section)
    hooks-daemon/              # Daemon installation (read-only from project perspective)
    project-handlers/          # NEW: Project-specific handlers
      __init__.py              # Makes it a package
      conftest.py              # Shared pytest fixtures for handler tests
      pre_tool_use/
        __init__.py
        vendor_changes_reminder.py
        test_vendor_changes_reminder.py
      post_tool_use/
        __init__.py
        build_asset_checker.py
        test_build_asset_checker.py
      session_start/
        __init__.py
        branch_naming_enforcer.py
        test_branch_naming_enforcer.py
```

**Key decisions:**

- Handlers live in `.claude/project-handlers/` -- close to the daemon config, clearly project-scoped.
- Mirror the daemon's own directory structure (event-type subdirectories).
- Tests co-located with handlers (test files alongside implementation, not a separate tree).
- `conftest.py` at the root provides shared fixtures.

**Why `.claude/project-handlers/` and not `.claude/hooks/handlers/` or another location:**

| Option | Pros | Cons |
|--------|------|------|
| `.claude/project-handlers/` | Clear naming, parallel to `hooks-daemon/`, discoverable | New directory |
| `.claude/hooks-daemon/project/` | Co-located with daemon | Mixes installed code with project code |
| `.claude/hooks/handlers/` | Existing convention in some docs | Ambiguous, `hooks/` used for other things |
| `project-root/hooks/` | Top-level visibility | Pollutes project root, not Claude-specific |

**Recommendation:** `.claude/project-handlers/` -- clear separation, discoverable naming, parallel to `hooks-daemon/`.

### 2.2 Handler Discovery Mechanism

**Recommended approach: Convention-based auto-discovery (like HandlerRegistry already does for built-in handlers).**

The daemon already scans event-type subdirectories for Handler subclasses. The same mechanism should work for project handlers.

#### Configuration Schema Addition

```yaml
# .claude/hooks-daemon.yaml
version: "1.0"

daemon:
  idle_timeout_seconds: 600

handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}
    # ... built-in handlers

# NEW: Project-level handler configuration
project_handlers:
  enabled: true
  path: .claude/project-handlers    # Relative to workspace root
  # Auto-discovers handlers in event-type subdirectories
  # Override config per handler (same schema as built-in handlers):
  pre_tool_use:
    vendor_changes_reminder: {enabled: true, priority: 45}
  session_start:
    branch_naming_enforcer: {enabled: true, priority: 30}
```

**Discovery algorithm:**

```python
def discover_project_handlers(project_handlers_path: Path, workspace_root: Path) -> list[tuple[EventType, Handler]]:
    """Discover handlers using same convention as built-in registry."""
    results = []

    for dir_name, event_type in EVENT_TYPE_MAPPING.items():
        event_dir = project_handlers_path / dir_name
        if not event_dir.is_dir():
            continue

        for py_file in event_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name.startswith("test_"):
                continue

            # Use importlib.util.spec_from_file_location (same as PluginLoader)
            handler = load_handler_from_file(py_file)
            if handler is not None:
                results.append((event_type, handler))

    return results
```

**Why auto-discovery over explicit listing:**

| Approach | Pros | Cons |
|----------|------|------|
| Auto-discovery | Zero config for new handlers, convention-over-configuration, mirrors built-in system | Could load unintended files |
| Explicit listing | Full control, clear what's loaded | Requires config update for every new handler, error-prone |
| Hybrid (auto-discover + explicit disable) | Best of both: works by default, opt-out for specific handlers | Slightly more complex |

**Recommendation:** Hybrid -- auto-discover from convention directories, allow per-handler `enabled: false` in config. This matches how built-in handlers already work.

### 2.3 Handler Development API

Project handlers need to import from the daemon package. The daemon is installed as a Python package in `.claude/hooks-daemon/untracked/venv/`. Project handlers should import from it.

#### Base Handler for Project Handlers

The daemon already provides the `Handler` ABC. Project handlers just subclass it:

```python
"""vendor_changes_reminder.py - Remind about vendor commit workflow."""

import re
from typing import Any

from claude_code_hooks_daemon.core import Handler, HookResult, Decision
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, TestType
from claude_code_hooks_daemon.core.utils import get_bash_command


class VendorChangesReminderHandler(Handler):
    """Remind to commit+push in vendor dir before composer update."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="vendor-changes-reminder",
            priority=45,
            terminal=False,  # Advisory - don't block
            tags=["project", "vendor", "workflow"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match git commits that include vendor/ changes."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(re.search(r"\bgit\s+(add|commit)\b", command)) and "vendor/" in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Provide reminder about vendor workflow."""
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "VENDOR WORKFLOW REMINDER:",
                "When modifying first-party vendor packages (ballicom, lts):",
                "1. cd into vendor/{vendor}/{package}",
                "2. git add, commit, and push changes there FIRST",
                "3. Then in main project: composer update {vendor}/{package}",
                "4. Commit the updated composer.lock in main project",
            ],
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Acceptance tests for vendor changes reminder."""
        return [
            AcceptanceTest(
                title="Vendor git add triggers reminder",
                command='echo "git add vendor/ballicom/templates_php8/src/file.php"',
                description="Advisory reminder when staging vendor files",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"VENDOR WORKFLOW REMINDER"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.ADVISORY,
            ),
        ]
```

**What the project handler gets from the daemon library:**

- `Handler` ABC (base class with `matches`/`handle`/`get_acceptance_tests` contract)
- `HookResult`, `Decision` (response model)
- `AcceptanceTest`, `TestType` (test definition)
- `get_bash_command`, `get_file_path` and other utilities from `core.utils`
- `get_data_layer()` for handler history, session state
- `ProjectContext` for workspace root and config paths

### 2.4 Testing Infrastructure

This is where the real value lies -- making project handler testing as robust as daemon handler testing.

#### Unit Testing

Project handler tests live alongside the handler files and use pytest:

```python
"""test_vendor_changes_reminder.py"""

import pytest
from vendor_changes_reminder import VendorChangesReminderHandler
from claude_code_hooks_daemon.core.hook_result import Decision


class TestVendorChangesReminderHandler:
    """Tests for VendorChangesReminderHandler."""

    def setup_method(self) -> None:
        self.handler = VendorChangesReminderHandler()

    def test_init(self) -> None:
        assert self.handler.name == "vendor-changes-reminder"
        assert self.handler.priority == 45
        assert self.handler.terminal is False

    def test_matches_vendor_git_add(self) -> None:
        hook_input = {
            "toolName": "Bash",
            "toolInput": {"command": "git add vendor/ballicom/templates_php8/src/file.php"},
        }
        assert self.handler.matches(hook_input) is True

    def test_no_match_non_vendor(self) -> None:
        hook_input = {
            "toolName": "Bash",
            "toolInput": {"command": "git add src/Entity/Order.php"},
        }
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_advisory(self) -> None:
        hook_input = {
            "toolName": "Bash",
            "toolInput": {"command": "git add vendor/ballicom/templates_php8/src/file.php"},
        }
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any("VENDOR WORKFLOW" in ctx for ctx in result.context)

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
```

#### conftest.py -- Shared Fixtures

```python
"""conftest.py - Shared test fixtures for project handlers."""

import pytest
from typing import Any


@pytest.fixture
def bash_hook_input() -> callable:
    """Factory fixture for creating Bash tool hook inputs."""
    def _make(command: str) -> dict[str, Any]:
        return {
            "toolName": "Bash",
            "toolInput": {"command": command},
        }
    return _make


@pytest.fixture
def write_hook_input() -> callable:
    """Factory fixture for creating Write tool hook inputs."""
    def _make(file_path: str, content: str = "") -> dict[str, Any]:
        return {
            "toolName": "Write",
            "toolInput": {"file_path": file_path, "content": content},
        }
    return _make


@pytest.fixture
def edit_hook_input() -> callable:
    """Factory fixture for creating Edit tool hook inputs."""
    def _make(file_path: str, old_string: str = "", new_string: str = "") -> dict[str, Any]:
        return {
            "toolName": "Edit",
            "toolInput": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
        }
    return _make
```

#### Running Project Handler Tests

The daemon should provide a CLI command for running project handler tests:

```bash
# From project root:
.claude/hooks-daemon/untracked/venv/bin/python -m pytest \
    .claude/project-handlers/ \
    --import-mode=importlib \
    -v

# Or via a convenience script/CLI command:
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli test-project-handlers
```

#### Integration with Daemon Acceptance Testing

The daemon's playbook generator already collects acceptance tests from all loaded handlers via `get_acceptance_tests()`. Since project handlers also implement this method, they would automatically be included in the generated playbook after loading.

The `generate-playbook` CLI command should be extended to also discover and load project handlers:

```bash
# Generates playbook including project handler acceptance tests
python -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md
```

### 2.5 Handler Validation CLI

A new CLI subcommand for validating project handlers without starting the daemon:

```bash
# Validate all project handlers
python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers

# Output:
# Scanning .claude/project-handlers/...
# Found 3 handlers in 2 event types:
#   pre_tool_use/vendor_changes_reminder.py -> VendorChangesReminderHandler
#     - Name: vendor-changes-reminder
#     - Priority: 45
#     - Terminal: False
#     - Tags: [project, vendor, workflow]
#     - Acceptance tests: 1
#     - Status: OK
#
#   pre_tool_use/branch_naming_enforcer.py -> BranchNamingEnforcerHandler
#     - Name: branch-naming-enforcer
#     - Priority: 30
#     - Terminal: True
#     - Tags: [project, git, workflow]
#     - Acceptance tests: 2
#     - Status: OK
#
#   post_tool_use/build_asset_checker.py -> BuildAssetCheckerHandler
#     - Name: build-asset-checker
#     - Priority: 50
#     - Terminal: False
#     - Tags: [project, build]
#     - Acceptance tests: 1
#     - Status: OK
#
# Validation: 3/3 handlers loaded successfully
# No conflicts with built-in handlers detected
```

This command would:
1. Scan the project-handlers directory
2. Attempt to import and instantiate each handler
3. Verify it subclasses `Handler`
4. Verify `get_acceptance_tests()` returns non-empty list
5. Check for priority conflicts with built-in handlers
6. Check for name conflicts with built-in handlers

---

## 3. Use Cases

### 3.1 Vendor Changes Reminder (shown above)

Detects commits touching `vendor/` directories, provides advisory reminder about vendor commit workflow.

### 3.2 Branch Naming Enforcement

```python
class BranchNamingEnforcerHandler(Handler):
    """Block commits if branch name doesn't match pattern."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="branch-naming-enforcer",
            priority=30,
            terminal=True,
            tags=["project", "git", "workflow"],
        )
        self._branch_pattern = r"^(feature|fix|chore|docs|plan)/[A-Z]+-\d+.*$"

    def matches(self, hook_input: dict[str, Any]) -> bool:
        command = get_bash_command(hook_input)
        return bool(command and re.search(r"\bgit\s+commit\b", command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True
        )
        branch = result.stdout.strip()
        if re.match(self._branch_pattern, branch):
            return HookResult.allow()
        return HookResult.deny(
            reason=f"Branch '{branch}' doesn't match required pattern: {self._branch_pattern}"
        )
```

### 3.3 Ticket Reference Checker

```python
class TicketReferenceCheckerHandler(Handler):
    """Ensure commits reference issue numbers in commit message."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        command = get_bash_command(hook_input)
        if not command or "git commit" not in command:
            return False
        # Only match commits with -m flag (has message inline)
        return bool(re.search(r'\bgit\s+commit\s+.*-m\s+', command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        command = get_bash_command(hook_input) or ""
        # Check if commit message contains ticket reference (#NNN)
        if re.search(r'#\d+', command):
            return HookResult.allow()
        return HookResult(
            decision=Decision.ALLOW,
            context=["REMINDER: Commit messages should reference an issue number (e.g., #123)"],
        )
```

### 3.4 Build Asset Watcher (PostToolUse)

```python
class BuildAssetCheckerHandler(Handler):
    """After file writes to TS/SCSS sources, remind to rebuild."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="build-asset-checker",
            priority=50,
            terminal=False,
            tags=["project", "build", "frontend"],
        )
        self._source_patterns = [
            r"vendor/ballicom/templates_php8/web/assets/ts/",
            r"vendor/ballicom/templates_php8/web/assets/scss/",
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        file_path = hook_input.get("toolInput", {}).get("file_path", "")
        return any(pattern in file_path for pattern in self._source_patterns)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "ASSET BUILD REMINDER: You modified a TypeScript/SCSS source file.",
                "Run 'yarn build' or 'yarn watch' in vendor/ballicom/templates_php8/web/ "
                "to rebuild compiled assets before testing.",
            ],
        )
```

### 3.5 Additional Use Cases to Consider

- **Composer lock file sync checker**: After `composer.json` edits, remind to run `composer update`
- **Database migration reminder**: When editing Entity classes, remind to create/run migrations
- **API schema regeneration**: When editing API DTOs, remind to regenerate OpenAPI spec
- **PHP CS fixer reminder**: After editing PHP files, remind about running `bin/qa -t allCS`
- **Environment file protection**: Block writes to `.env` or sensitive config files
- **Test file pairing**: When creating a new PHP class, check if a test file exists

---

## 4. Technical Design Details

### 4.1 Integration Point in DaemonController

The `DaemonController.initialise()` method currently loads built-in handlers and then plugins. Project handlers should be a third phase:

```python
def initialise(self, handler_config, workspace_root, plugins_config):
    # Phase 1: Built-in handlers (existing)
    self._registry.discover()
    count = self._registry.register_all(self._router, config=handler_config, workspace_root=workspace_root)

    # Phase 2: Legacy plugins (existing)
    plugin_count = self._load_plugins(plugins_config, workspace_root)

    # Phase 3: Project handlers (NEW)
    project_count = self._load_project_handlers(workspace_root, handler_config)

    total_count = count + plugin_count + project_count
```

### 4.2 Python Path Management

The key challenge: project handler `.py` files need to import from `claude_code_hooks_daemon`. The daemon is installed in its own venv at `.claude/hooks-daemon/untracked/venv/`.

**Solution**: The daemon process already runs in this venv. When it loads project handlers via `importlib.util.spec_from_file_location`, the daemon package is already available. No additional path manipulation is needed.

For **test execution**, the project handler tests also need the daemon package available. This is solved by running tests through the daemon's venv Python:

```bash
.claude/hooks-daemon/untracked/venv/bin/python -m pytest .claude/project-handlers/
```

### 4.3 Isolation and Safety

**Project handlers run in the same process as the daemon.** This is by design (same as built-in handlers), for performance. However, this means:

- Project handler exceptions are caught by the HandlerChain's try/except (fail-open or fail-closed depending on strict_mode).
- A badly-written project handler that runs forever will block the event dispatch. The daemon's request timeout (30s default) provides a safety net.
- Project handlers have full access to the Python runtime. This is acceptable because the project developer controls both the project code and the project handlers.

### 4.4 Configuration Models Addition

New Pydantic model:

```python
class ProjectHandlersConfig(BaseModel):
    """Configuration for project-level handlers.

    Attributes:
        enabled: Master switch for project handlers
        path: Path to project handlers directory (relative to workspace root)
        handlers_config: Per-event-type handler configuration (same schema as built-in)
    """
    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Enable project handler loading")
    path: str = Field(
        default=".claude/project-handlers",
        description="Path to project handlers directory",
    )
```

And add to the root Config model:

```python
class Config(BaseModel):
    version: str = Field(default="2.0")
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    handlers: HandlersConfig = Field(default_factory=HandlersConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    project_handlers: ProjectHandlersConfig = Field(default_factory=ProjectHandlersConfig)  # NEW
```

### 4.5 Naming Conflict Resolution

If a project handler has the same `handler_id` as a built-in handler, the system should:

1. Log a warning
2. Prefer the built-in handler (safety first)
3. Report the conflict in `validate-project-handlers` output

If a project handler has a priority collision with a built-in handler for the same event, the existing alphabetical-sorting tiebreaker applies (already implemented in HandlerChain).

---

## 5. Scaffolding / Init Command

A CLI command to bootstrap the project-handlers directory:

```bash
python -m claude_code_hooks_daemon.daemon.cli init-project-handlers
```

This would:

1. Create `.claude/project-handlers/` with `__init__.py`
2. Create `conftest.py` with standard test fixtures
3. Create an example handler with test (e.g., a simple advisory handler)
4. Update `hooks-daemon.yaml` to add the `project_handlers` section if not present
5. Print instructions for next steps

Generated example:

```
Created .claude/project-handlers/
  __init__.py
  conftest.py
  pre_tool_use/
    __init__.py
    example_handler.py
    test_example_handler.py

Next steps:
  1. Edit pre_tool_use/example_handler.py with your handler logic
  2. Run tests: .claude/hooks-daemon/untracked/venv/bin/python -m pytest .claude/project-handlers/ -v
  3. Validate: python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
  4. Restart daemon: python -m claude_code_hooks_daemon.daemon.cli restart
```

---

## 6. Pros and Cons Analysis

### Approach: Convention-Based Auto-Discovery from `.claude/project-handlers/`

**Pros:**
- Mirrors the built-in handler system exactly -- developers learn one pattern
- Auto-discovery means zero config for new handlers (just add a .py file)
- Event-type subdirectories make event mapping unambiguous (no `event_type` field in config needed)
- Co-located tests reduce friction for TDD
- Full access to daemon library (Handler, HookResult, utilities)
- Acceptance tests auto-included in playbook generation
- CLI validation catches issues before daemon restart

**Cons:**
- Project handlers coupled to daemon's Python API (version changes could break them)
- Running in daemon process means bugs can affect performance
- Tests require daemon's venv Python (not the project's own Python)
- Auto-discovery could load unintended files if naming conventions not followed

### Alternative Considered: Entry-Points Based Plugin System

Using Python packaging entry points (like pytest plugins):

```toml
# project pyproject.toml
[project.entry-points."claude_code_hooks"]
vendor_reminder = "project_hooks.vendor_changes_reminder:VendorChangesReminderHandler"
```

**Why rejected:**
- Requires a full Python package structure in the project
- Requires `pip install -e .` into the daemon's venv
- Overkill for project-level handlers (this pattern is for distributable packages)
- The existing `importlib.util.spec_from_file_location` approach in PluginLoader already works well for file-based loading

### Alternative Considered: Standalone Plugin Packages

**Why deferred (not rejected):**
- This is the right pattern for handlers that span multiple projects (e.g., "PHP project safety handlers")
- Should be Phase 3 -- build on top of project-level handlers
- Use entry points for this case: `pip install claude-hooks-php-safety`

---

## 7. Implementation Phases

### Phase 1: Core Infrastructure

1. Add `ProjectHandlersConfig` to config models
2. Add `project_handlers` section to config schema validation
3. Implement `ProjectHandlerLoader` class (extends PluginLoader patterns)
4. Wire into `DaemonController.initialise()` as third loading phase
5. Unit tests for all new code
6. Integration test: project handlers loaded and dispatched correctly

### Phase 2: Developer Experience

1. `init-project-handlers` CLI command (scaffolding)
2. `validate-project-handlers` CLI command (validation)
3. `test-project-handlers` CLI command (convenience test runner)
4. Update `generate-playbook` to include project handlers
5. conftest.py template with standard fixtures

### Phase 3: Documentation

1. `CLAUDE/PROJECT_HANDLERS.md` in daemon repo -- developer guide
2. Update `CLAUDE/ARCHITECTURE.md` with project handler loading
3. Update `CLAUDE/HANDLER_DEVELOPMENT.md` to cover project handlers
4. Example handlers for common PHP project patterns

### Phase 4: Distributable Handler Packages (Future)

1. Entry-points based discovery for installed packages
2. Handler package template/cookiecutter
3. Registry/marketplace concept
4. Version compatibility checking

---

## 8. Migration Path for Existing Projects

For the checkout project specifically:

1. Run `init-project-handlers` to scaffold the directory
2. Identify project-specific logic currently in CLAUDE.md that could become handlers:
   - Vendor changes workflow reminders
   - composer.lock sync checking
   - Asset build reminders
   - PHP QA tool reminders
3. Create handlers with TDD (test first, then implement)
4. Add to `hooks-daemon.yaml` `project_handlers` config
5. Restart daemon and verify with acceptance testing

The existing `plugins` config section remains for backward compatibility but `project_handlers` becomes the recommended approach for project-level handlers.

---

## 9. Summary

The hooks-daemon already has 90% of the infrastructure needed for project-level handlers. The `PluginLoader` does dynamic file-based loading, the `Handler` ABC defines the contract, `AcceptanceTest` provides test definitions, and the `HandlerChain`/`EventRouter`/`DaemonController` pipeline handles dispatch.

What is missing is the **developer experience layer**: scaffolding, validation, test running, auto-discovery by convention, and documentation. The proposed design adds these without changing the core dispatch architecture, making project handler development as rigorous and well-supported as built-in handler development.

---

**End of Design Document**
