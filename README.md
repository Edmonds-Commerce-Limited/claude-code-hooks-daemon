# Claude Code Hooks Daemon

**High-performance daemon for Claude Code hooks using Unix socket IPC.**

Eliminates process spawn overhead (~21ms) with sub-millisecond response times after warmup.

---

**🤖 AI-Assisted Installation**: Copy and paste this into Claude Code:

```
Please read and follow the installation instructions from:
https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md
```

---

## Purpose

Provides a daemon-based hooks system with:
- **Sub-millisecond response times** after warmup (20x faster than process spawn)
- **Lazy startup** - Daemon starts on first hook call
- **Auto-shutdown** - Exits after 10 minutes of inactivity
- **Multi-project support** - Unique daemon per project directory
- **Battle-tested handlers** - 9 built-in safety and workflow handlers
- **Project extensibility** - Easy to add custom handlers

## Current Implementation Status

**Currently Implemented:**
- ✅ **PreToolUse** - 9 handlers (destructive_git, sed_blocker, absolute_path, worktree_file_copy, git_stash, eslint_disable, tdd_enforcement, web_search_year, british_english)

**Scaffolding Only (no handlers yet):**
- ⚠️ **PostToolUse** - Entry point exists, no handlers implemented
- ⚠️ **SessionStart** - Entry point exists, no handlers implemented

**Not Implemented:**
- ❌ notification, permission-request, pre-compact, session-end, stop, subagent-stop, user-prompt-submit

## Installation

### Manual Installation

Run from your project root:

```bash
# Clone daemon to .claude/hooks-daemon/
mkdir -p .claude
cd .claude
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon

# Create self-contained virtual environment
python3 -m venv untracked/venv

# Install daemon dependencies into venv
untracked/venv/bin/pip install -e .

# Run automated installer
# The installer auto-detects project root (searches upward for .claude/)
# For explicit control, use: --project-root /path/to/project
untracked/venv/bin/python install.py

# Return to project root
cd ../..
```

The installer will:
1. ✅ Backup existing `.claude/hooks/` to `.claude/hooks.bak`
2. ✅ Copy `init.sh` (daemon lifecycle functions)
3. ✅ Create forwarder scripts (route hook calls to daemon)
4. ✅ Create `.claude/settings.json` (hook registration)
5. ✅ Create `.claude/hooks-daemon.yaml` (handler + daemon config)

### Architecture

**Forwarder Pattern:**
```
Claude Code → Hook Script (forwarder) → Daemon (Unix socket) → Handlers
```

**Files Created:**
- `.claude/init.sh` - Daemon lifecycle (start/stop/ensure_daemon)
- `.claude/hooks/*` - Forwarder scripts (bash scripts that source init.sh)
- `.claude/settings.json` - Hook registration
- `.claude/hooks-daemon.yaml` - Configuration (handlers + daemon settings)

**Active Handlers:**
- ✅ **PreToolUse** - 9 handlers (destructive_git, sed_blocker, absolute_path, etc.)
- ⚠️ **PostToolUse** - No handlers yet (pass-through)
- ⚠️ **SessionStart** - No handlers yet (pass-through)

## Daemon Management

```bash
# All commands use the venv Python (NOT system Python)
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Start daemon manually (usually not needed - lazy startup)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start

# Stop daemon
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# Check status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Restart
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

**Note**: Daemon starts automatically on first hook call (lazy startup).

## Coexistence with Traditional Hooks

This daemon system is designed to **coexist** with traditional Claude Code hook scripts. You're not forced into this approach - it runs alongside existing hooks.

### Backup & Restore

During installation, existing hooks are backed up:
```
.claude/hooks/      → .claude/hooks.bak/
```

To restore traditional hooks:
```bash
# Full rollback to traditional hooks
rm -rf .claude/hooks/
mv .claude/hooks.bak .claude/hooks/
```

### Running Both Side-by-Side

Claude Code's `settings.json` supports **multiple hooks per event type**. You can register both daemon forwarders AND traditional scripts:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          { "type": "command", "command": ".claude/hooks/pre-tool-use", "timeout": 60 },
          { "type": "command", "command": ".claude/legacy-hooks/my-custom-check.sh", "timeout": 30 }
        ]
      }
    ]
  }
}
```

### Integration Options

1. **Full Daemon**: Use daemon for all hooks (recommended for performance)
2. **Hybrid**: Daemon for complex handlers, traditional scripts for simple checks
3. **Traditional Only**: Rollback to backup if daemon doesn't suit your workflow

### Project Handlers

For project-specific logic that should run through the daemon, create handlers in:
```
.claude/hooks/handlers/pre_tool_use/my_handler.py
```

See `CONTRIBUTING.md` for handler development guide.

## Architecture

### Core Components

1. **Front Controller Engine** - Efficient pattern-based dispatch
2. **Handler Library** - Collection of reusable handlers
3. **Configuration System** - Per-project handler selection and customisation
4. **Plugin System** - Easy addition of custom handlers

### Handler Categories

**General Utility Handlers** (daemon):
- `DestructiveGitHandler` - Blocks dangerous git operations
- `GitStashHandler` - Discourages git stash usage
- `AbsolutePathHandler` - Enforces relative paths
- `WebSearchYearHandler` - Ensures current year in searches
- `BritishEnglishHandler` - Warns on American spellings
- `EslintDisableHandler` - Blocks ESLint suppression comments
- `TddEnforcementHandler` - Enforces test-driven development
- `SedBlockerHandler` - Blocks unsafe sed operations
- `WorktreeFileCopyHandler` - Prevents cross-worktree file copies

**Project-Specific Handlers** (keep in projects):
- `NpmCommandHandler` - Project-specific npm command patterns
- `AdHocScriptHandler` - Project-specific script inventory
- `MarkdownOrganizationHandler` - Project-specific documentation structure
- `ClaudeReadmeHandler` - Project-specific content rules
- `OfficialPlanCommandHandler` - Project-specific planning workflow
- `PlanTimeEstimatesHandler` - Project planning conventions
- `ValidatePlanNumberHandler` - Project plan numbering
- `PlanWorkflowHandler` - Project workflow patterns
- `PromptLibraryDirectEditHandler` - Project prompt library rules
- `EnforceControllerPatternHandler` - Hook architecture enforcement


## Configuration

Create `.claude/hooks-daemon.yaml` in your project:

```yaml
version: 1.0

# Global settings
settings:
  logging_level: INFO
  log_file: .claude/hooks/daemon.log

# Handler configuration
handlers:
  pre_tool_use:
    # Enable/disable handlers
    destructive_git:
      enabled: true
      priority: 10

    git_stash:
      enabled: true
      priority: 20
      escape_hatch: "I HAVE ABSOLUTELY CONFIRMED THAT STASH IS THE ONLY OPTION"

    absolute_path:
      enabled: true
      priority: 12
      blocked_prefixes:
        - /container-mount/
        - /tmp/claude-code/

    web_search_year:
      enabled: true
      priority: 55
      allow_historical: false  # Future: allow year ranges for historical research

    british_english:
      enabled: true
      priority: 60
      mode: warn  # warn or block
      excluded_dirs:
        - node_modules/
        - dist/

    eslint_disable:
      enabled: true
      priority: 30

    tdd_enforcement:
      enabled: true
      priority: 15
      test_file_patterns:
        - "**/*.test.ts"
        - "**/*.spec.ts"

    sed_blocker:
      enabled: true
      priority: 10

    worktree_file_copy:
      enabled: true
      priority: 15

  # Future: other hook events
  post_tool_use:
    enabled: false

  session_start:
    enabled: false

# Plugin handlers (project-specific)
plugins:
  - path: .claude/hooks/controller/handlers
    handlers:
      - npm_command_handler
      - ad_hoc_script_handler
      - markdown_organization_handler
```

## Usage

### With Claude Code

Register in `.claude/settings.local.json`:

```json
{
  "hooks": {
    "preToolUse": "python3 -m claude_code_hooks_daemon.hooks.pre_tool_use"
  }
}
```

### Programmatic Usage

```python
from claude_code_hooks_daemon import HooksDaemon, HookResult

# Initialize daemon with config
daemon = HooksDaemon.from_config(".claude/hooks-daemon.yaml")

# Process a tool call
hook_input = {
    "toolName": "Bash",
    "toolInput": {"command": "git reset --hard"}
}

result = daemon.dispatch("pre_tool_use", hook_input)
print(result.to_json("PreToolUse"))
# Output: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
```

## Development

### Project Structure

```
claude-code-hooks-daemon/
├── src/
│   └── claude_code_hooks_daemon/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── front_controller.py   # Core dispatch engine
│       │   ├── handler.py            # Handler base class
│       │   ├── hook_result.py        # Result types
│       │   └── utils.py              # Utility functions
│       ├── config/
│       │   ├── __init__.py
│       │   ├── loader.py             # YAML/JSON config loading
│       │   └── schema.py             # Configuration validation
│       ├── handlers/
│       │   ├── __init__.py
│       │   ├── pre_tool_use/
│       │   │   ├── __init__.py
│       │   │   ├── destructive_git.py
│       │   │   ├── git_stash.py
│       │   │   ├── absolute_path.py
│       │   │   ├── web_search_year.py
│       │   │   ├── british_english.py
│       │   │   ├── eslint_disable.py
│       │   │   ├── tdd_enforcement.py
│       │   │   ├── sed_blocker.py
│       │   │   └── worktree_file_copy.py
│       │   ├── post_tool_use/
│       │   │   └── __init__.py
│       │   └── session_start/
│       │       └── __init__.py
│       ├── plugins/
│       │   ├── __init__.py
│       │   └── loader.py             # Dynamic handler loading
│       └── hooks/
│           ├── __init__.py
│           ├── pre_tool_use.py       # Entry point
│           ├── post_tool_use.py      # Entry point
│           └── session_start.py      # Entry point
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_front_controller.py
│   │   └── test_handlers/
│   │       ├── test_destructive_git.py
│   │       ├── test_git_stash.py
│   │       └── ...
│   ├── integration/
│   │   ├── test_config_loading.py
│   │   └── test_plugin_system.py
│   └── fixtures/
│       ├── sample_config.yaml
│       └── test_inputs.json
├── docs/
│   ├── architecture.md
│   ├── handler_development.md
│   ├── configuration.md
│   └── migration_guide.md
├── examples/
│   ├── basic_setup/
│   ├── custom_handlers/
│   └── multi_project/
├── pyproject.toml
├── setup.py
├── README.md
├── LICENSE
└── CHANGELOG.md
```

### Adding Custom Handlers

1. Create handler class extending `Handler`
2. Implement `matches()` and `handle()` methods
3. Register via config or programmatically

Example:

```python
from claude_code_hooks_daemon.core import Handler, HookResult

class CustomHandler(Handler):
    def __init__(self):
        super().__init__(name="custom-handler", priority=50)

    def matches(self, hook_input: dict) -> bool:
        # Your matching logic
        return hook_input.get("toolName") == "Write"

    def handle(self, hook_input: dict) -> HookResult:
        # Your handling logic
        return HookResult(decision="allow", context="Custom context")
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=claude_code_hooks_daemon --cov-report=html

# Run specific handler tests
pytest tests/unit/test_handlers/test_destructive_git.py
```

## Performance

- **Cold start**: ~50ms (config load + handler init)
- **Warm dispatch**: ~20ms (cached handlers)
- **Memory**: ~15MB (loaded handlers)

Compare to standalone hooks: ~200ms per hook (process spawn overhead)

## Roadmap

### v1.0 (Current)
- [x] Core front controller engine
- [x] 9 general utility handlers
- [x] YAML configuration system
- [x] Basic plugin system

### v1.1 (Next)
- [ ] Handler hot-reload
- [ ] Metrics and monitoring
- [ ] Handler marketplace/registry
- [ ] Advanced configuration (per-handler overrides)

### v2.0 (Future)
- [ ] Multi-event coordination (PreToolUse → PostToolUse chains)
- [ ] Async handler support
- [ ] Handler dependency management
- [ ] Web UI for configuration

## Troubleshooting

### Hook Not Running

**Check hook is executable**:
```bash
ls -la .claude/hooks/pre-tool-use
# Should show: -rwxr-xr-x (executable)

# If not executable:
chmod +x .claude/hooks/pre-tool-use
```

**Test hook manually**:
```bash
echo '{"tool_name": "Bash", "tool_input": {"command": "ls"}}' | .claude/hooks/pre-tool-use
# Should output: {} (empty JSON = allow)
```

**Check daemon is importable**:
```bash
.claude/hooks-daemon/untracked/venv/bin/python -c "from claude_code_hooks_daemon.hooks.pre_tool_use import main; print('✅ OK')"
```

### Import Errors

**ModuleNotFoundError: No module named 'claude_code_hooks_daemon'**

- **Solution**: Ensure venv exists and dependencies are installed:
  ```bash
  cd .claude/hooks-daemon
  python3 -m venv untracked/venv
  untracked/venv/bin/pip install -e .
  ```

### Dependencies Missing

**ModuleNotFoundError: No module named 'yaml'**

Install daemon dependencies into venv:
```bash
cd .claude/hooks-daemon
untracked/venv/bin/pip install -e .  # Installs pyyaml, jsonschema
```

### Configuration Not Loading

**Check config file location**:
```bash
# Should be at project root or .claude/
ls .claude/hooks-daemon.yaml  # Preferred location
ls hooks-daemon.yaml          # Alternative location
```

**Validate YAML syntax**:
```bash
.claude/hooks-daemon/untracked/venv/bin/python -c "import yaml; yaml.safe_load(open('.claude/hooks-daemon.yaml'))"
# Should print config or show syntax error
```

### Handlers Not Blocking

**Check handler is enabled in config**:
```yaml
handlers:
  pre_tool_use:
    destructive_git:
      enabled: true  # ← Must be true
```

**Check handler priority** (lower = runs first):
```yaml
handlers:
  pre_tool_use:
    your_handler:
      priority: 10  # Runs before priority 20
```

**Enable debug logging**:
```yaml
settings:
  logging_level: DEBUG
  log_file: .claude/hooks/daemon.log
```

Then check logs:
```bash
tail -f .claude/hooks/daemon.log
```

### Performance Issues

**Hook running slowly?**

Check number of enabled handlers:
```bash
grep -A 2 "enabled: true" .claude/hooks-daemon.yaml | wc -l
```

Disable unused handlers to improve performance.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT License - See [LICENSE](LICENSE)

## Support

- GitHub Issues: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
- Discussions: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/discussions

## Credits

Developed by Edmonds Commerce (https://edmondscommerce.co.uk)

Based on production hook system refined across multiple enterprise projects.
